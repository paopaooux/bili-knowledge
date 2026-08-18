from __future__ import annotations

import json
import logging
import shutil
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from .ai import AIServiceError, chat, test_service
from .config import Settings, load_settings
from .constants import STAGES
from .database import Database, utcnow
from .knowledge import KnowledgeOrganizerError, refactor_topic_document
from .knowledge_profile import (
    KnowledgeProfileError,
    default_topic_path,
    load_knowledge_profile,
    normalize_knowledge_profile,
    validate_topic_path,
)
from .pipeline import JobWorker, Pipeline
from .prompting import render_prompt
from .schemas import (
    CreateJobRequest,
    InspectRequest,
    KnowledgeProfileRequest,
    RetryRequest,
    SettingsTestRequest,
    TopicSuggestionRequest,
)
from .utils import within_directory
from .video import VideoInspectionError, inspect_video

logger = logging.getLogger("uvicorn.error")
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def create_app(settings: Settings | None = None, start_worker: bool = True) -> FastAPI:
    config = settings or load_settings()
    db = Database(config.database_path)
    db.migrate()
    db.seed_knowledge_profile(load_knowledge_profile(config.knowledge_profile_path))
    worker = JobWorker(Pipeline(db, config), concurrency=config.job_worker_concurrency)

    def prepare_profile(request: KnowledgeProfileRequest) -> dict:
        raw = request.model_dump()
        used = {item["path"] for item in raw["preferred_topics"] if item.get("path")}
        context = {"preferred_topics": raw["preferred_topics"]}
        for topic in raw["preferred_topics"]:
            if not topic.get("path"):
                topic["path"] = default_topic_path(context, topic["name"], used)
                used.add(topic["path"])
        try:
            return normalize_knowledge_profile(raw)
        except KnowledgeProfileError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        queued = db.recover_interrupted()
        if start_worker:
            worker.start()
            for job_id in queued:
                worker.enqueue(job_id)
        yield
        if start_worker:
            worker.stop()

    app = FastAPI(title="Bilibili 视频转知识文档", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5175", "http://127.0.0.1:5175"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.settings = config
    app.state.db = db
    app.state.worker = worker

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "worker": "running" if worker.alive_count else "stopped",
            "worker_concurrency": worker.concurrency,
            "active_workers": worker.alive_count,
        }

    @app.post("/api/videos/inspect")
    def inspect(request: InspectRequest) -> dict:
        try:
            metadata = inspect_video(str(request.url), config)
            return db.save_inspection(metadata)
        except VideoInspectionError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/api/jobs", status_code=201)
    def create_job(request: CreateJobRequest) -> dict:
        video = db.one("SELECT id FROM videos WHERE id=?", (request.video_id,))
        if not video:
            raise HTTPException(status_code=404, detail="视频解析记录不存在，请重新解析")
        unique_ids = list(dict.fromkeys(request.part_ids))
        part_count = db.one(
            "SELECT COUNT(*) AS count FROM parts WHERE video_id=?", (request.video_id,)
        )["count"]
        if part_count != 1 or len(unique_ids) != 1:
            raise HTTPException(status_code=422, detail="当前版本仅支持单 P 视频")
        placeholders = ",".join("?" for _ in unique_ids)
        parts = db.all(
            f"SELECT id FROM parts WHERE video_id=? AND id IN ({placeholders})",
            (request.video_id, *unique_ids),
        )
        if len(parts) != len(unique_ids):
            raise HTTPException(status_code=422, detail="包含不属于该视频的分 P")
        job_id, created = db.create_job_if_absent(request.video_id, unique_ids)
        if not created:
            raise HTTPException(
                status_code=409,
                detail="相同视频任务已存在，请在历史任务中查看；失败任务可直接重试",
            )
        if start_worker:
            worker.enqueue(job_id)
        return db.job_detail(job_id)

    @app.get("/api/jobs")
    def jobs() -> list[dict]:
        return db.list_jobs()

    @app.get("/api/jobs/{job_id}")
    def job_detail(job_id: str) -> dict:
        job = db.job_detail(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        return job

    @app.post("/api/knowledge/regenerate")
    def regenerate_knowledge_base() -> dict:
        active_jobs = db.one(
            "SELECT COUNT(*) AS count FROM jobs WHERE status IN ('queued','running')"
        )["count"]
        if active_jobs:
            raise HTTPException(
                status_code=409,
                detail="仍有任务正在排队或处理，请等待全部结束后再重新生成知识库",
            )

        eligible_parts: list[tuple[str, str]] = []
        generated_paths: set[Path] = set()
        jobs_to_queue: list[str] = []
        # Process old jobs first so the rebuilt topics evolve in their original order.
        for job in sorted(db.list_jobs(), key=lambda item: (item["created_at"], item["id"])):
            for part in job["parts"]:
                paths = worker.pipeline._paths(job, part)
                if paths["transcript"].is_file() and paths["metadata"].is_file():
                    eligible_parts.append((job["id"], part["id"]))
                    if job["id"] not in jobs_to_queue:
                        jobs_to_queue.append(job["id"])
                for artifact in part["artifacts"]:
                    if artifact["kind"] in {"document", "knowledge_update", "index"}:
                        generated_paths.add(Path(artifact["path"]))

        if not eligible_parts:
            raise HTTPException(
                status_code=409,
                detail="没有可重新生成的历史任务；至少需要保留完整的转写和元数据",
            )

        for path in generated_paths:
            if within_directory(path, config.source_output_dir) or within_directory(
                path, config.knowledge_base_dir
            ):
                with suppress(OSError):
                    path.unlink(missing_ok=True)
        topics_directory = config.knowledge_base_dir / "topics"
        shutil.rmtree(topics_directory, ignore_errors=True)
        topics_directory.mkdir(parents=True, exist_ok=True)

        now = utcnow()
        with db.transaction() as connection:
            connection.execute(
                "DELETE FROM artifacts WHERE kind IN ('document','topic','knowledge_update','index')"
            )
            connection.execute("DELETE FROM knowledge_topics")
            for job_id, part_id in eligible_parts:
                connection.execute(
                    """UPDATE job_stages SET status='pending',error=NULL,started_at=NULL,
                    finished_at=NULL,retries=retries+CASE WHEN stage='generate' THEN 1 ELSE 0 END
                    WHERE job_id=? AND part_id=? AND stage IN ('generate','organize','publish')""",
                    (job_id, part_id),
                )
                connection.execute(
                    "UPDATE job_parts SET status='queued',summary=NULL WHERE job_id=? AND part_id=?",
                    (job_id, part_id),
                )
            for job_id in jobs_to_queue:
                connection.execute(
                    """UPDATE jobs SET status='queued',cancel_requested=0,error=NULL,
                    completed_at=NULL,updated_at=? WHERE id=?""",
                    (now, job_id),
                )

        if start_worker:
            worker.enqueue_serial(jobs_to_queue)
        logger.info(
            "Knowledge base regeneration queued jobs=%d parts=%d",
            len(jobs_to_queue),
            len(eligible_parts),
        )
        return {"queued_jobs": len(jobs_to_queue), "queued_parts": len(eligible_parts)}

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str, request: RetryRequest) -> dict:
        job = db.job_detail(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        retrying_completed_organize = job["status"] == "completed" and request.stage == "organize"
        if job["status"] not in {"failed", "cancelled"} and not retrying_completed_organize:
            raise HTTPException(
                status_code=409,
                detail="仅失败、已取消的任务，或已完成任务的归档知识阶段可以重试",
            )
        selected = [
            part for part in job["parts"] if not request.part_id or part["id"] == request.part_id
        ]
        if not selected:
            raise HTTPException(status_code=422, detail="指定分 P 不属于该任务")
        stage_index = STAGES.index(request.stage)
        with db.transaction() as connection:
            for part in selected:
                if request.stage == "organize":
                    connection.execute(
                        "DELETE FROM artifacts WHERE job_id=? AND part_id=? AND kind='topic'",
                        (job_id, part["id"]),
                    )
                for stage in STAGES[stage_index:]:
                    connection.execute(
                        """UPDATE job_stages SET status='pending',error=NULL,started_at=NULL,finished_at=NULL,
                        retries=retries+CASE WHEN stage=? THEN 1 ELSE 0 END
                        WHERE job_id=? AND part_id=? AND stage=?""",
                        (request.stage, job_id, part["id"], stage),
                    )
                connection.execute(
                    "UPDATE job_parts SET status='queued' WHERE job_id=? AND part_id=?",
                    (job_id, part["id"]),
                )
            connection.execute(
                """UPDATE jobs SET status='queued',cancel_requested=0,error=NULL,completed_at=NULL,updated_at=?
                WHERE id=?""",
                (utcnow(), job_id),
            )
        if start_worker:
            worker.enqueue(job_id)
        return db.job_detail(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> dict:
        job = db.job_detail(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] in {"completed", "failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="任务已经结束")
        db.execute("UPDATE jobs SET cancel_requested=1,updated_at=? WHERE id=?", (utcnow(), job_id))
        return {"ok": True, "message": "已请求取消；当前网络或转码操作结束后生效"}

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_finished_job(job_id: str) -> None:
        removable_kinds = {"metadata", "transcript", "audio_temp", "knowledge_update"}
        removable_paths: list[Path] = []
        with db.transaction() as connection:
            jobs_before = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            job = connection.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise HTTPException(status_code=404, detail="任务不存在")
            if job["status"] not in {"failed", "cancelled"}:
                raise HTTPException(status_code=409, detail="只能删除失败或已取消的任务")
            artifacts = connection.execute(
                "SELECT kind,path FROM artifacts WHERE job_id=?", (job_id,)
            ).fetchall()
            if any(item["kind"] in {"document", "topic", "index"} for item in artifacts):
                raise HTTPException(
                    status_code=409,
                    detail="该任务已经生成知识文档或写入主题知识，不能删除任务记录",
                )
            for artifact in artifacts:
                if artifact["kind"] not in removable_kinds:
                    continue
                shared = connection.execute(
                    "SELECT 1 FROM artifacts WHERE job_id<>? AND path=? LIMIT 1",
                    (job_id, artifact["path"]),
                ).fetchone()
                if not shared:
                    removable_paths.append(Path(artifact["path"]))
            deleted = connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            jobs_after = connection.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
            if deleted.rowcount != 1 or jobs_after != jobs_before - 1:
                raise RuntimeError("删除任务的影响范围异常，操作已回滚")

        shutil.rmtree(config.temp_dir / job_id, ignore_errors=True)
        for path in removable_paths:
            if within_directory(path, config.source_output_dir) or within_directory(
                path, config.knowledge_base_dir
            ) or within_directory(
                path, config.temp_dir
            ):
                with suppress(OSError):
                    path.unlink(missing_ok=True)
        logger.info("Deleted failed or cancelled job %s; remaining jobs: %s", job_id, jobs_after)

    def document_artifact(artifact_id: str) -> tuple[dict, Path]:
        artifact = db.one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not artifact or artifact["kind"] not in {
            "document",
            "index",
            "topic",
            "knowledge_update",
        }:
            raise HTTPException(status_code=404, detail="文档不存在")
        path = Path(artifact["path"])
        if not (
            within_directory(path, config.source_output_dir)
            or within_directory(path, config.knowledge_base_dir)
        ) or not path.is_file():
            raise HTTPException(status_code=404, detail="文档文件不存在或路径无效")
        return artifact, path

    @app.get("/api/documents/{artifact_id}", response_class=PlainTextResponse)
    def document(artifact_id: str) -> str:
        _, path = document_artifact(artifact_id)
        return path.read_text(encoding="utf-8")

    @app.get("/api/documents/{artifact_id}/download")
    def download_document(artifact_id: str) -> FileResponse:
        _, path = document_artifact(artifact_id)
        return FileResponse(path, media_type="text/markdown", filename=path.name)

    def transcript_artifact(artifact_id: str) -> tuple[dict, Path]:
        artifact = db.one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not artifact or artifact["kind"] != "transcript":
            raise HTTPException(status_code=404, detail="转写产物不存在")
        path = Path(artifact["path"])
        if not (
            within_directory(path, config.source_output_dir)
            or within_directory(path, config.knowledge_base_dir)
        ) or not path.is_file():
            raise HTTPException(status_code=404, detail="转写文件不存在或路径无效")
        return artifact, path

    @app.get("/api/transcripts/{artifact_id}")
    def transcript(artifact_id: str) -> list[dict]:
        _, path = transcript_artifact(artifact_id)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=500, detail="转写文件已损坏") from exc
        if not isinstance(payload, list):
            raise HTTPException(status_code=500, detail="转写文件格式无效")
        return payload

    @app.get("/api/transcripts/{artifact_id}/download")
    def download_transcript(artifact_id: str) -> FileResponse:
        _, path = transcript_artifact(artifact_id)
        return FileResponse(path, media_type="application/json", filename=path.name)

    @app.get("/api/settings")
    def get_settings() -> dict:
        return config.public_dict()

    @app.post("/api/settings/test")
    def settings_test(request: SettingsTestRequest) -> dict:
        try:
            return test_service(request.service, config)
        except AIServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    def knowledge_file(relative_path: str) -> Path:
        if not relative_path or Path(relative_path).is_absolute():
            raise HTTPException(status_code=400, detail="知识库文件路径无效")
        path = config.knowledge_base_dir / relative_path
        topics_directory = config.knowledge_base_dir / "topics"
        if not within_directory(path, topics_directory) or not path.is_file():
            raise HTTPException(status_code=404, detail="知识库文件不存在或路径无效")
        return path

    @app.get("/api/knowledge/files")
    def knowledge_files() -> list[dict]:
        topics_directory = config.knowledge_base_dir / "topics"
        topics_directory.mkdir(parents=True, exist_ok=True)

        def entries(directory: Path) -> list[dict]:
            result = []
            try:
                children = sorted(
                    directory.iterdir(),
                    key=lambda item: (not item.is_dir(), item.name.casefold()),
                )
            except OSError:
                return result
            for child in children:
                # Do not follow symlinks: a link inside the knowledge base may point outside it.
                if child.is_symlink():
                    continue
                if child.is_file() and child.suffix.lower() not in {".md", ".markdown"}:
                    continue
                relative = child.relative_to(config.knowledge_base_dir).as_posix()
                try:
                    stat = child.stat()
                except OSError:
                    continue
                nested = entries(child) if child.is_dir() else None
                # A category without topic documents is not part of the visible knowledge base.
                if child.is_dir() and not nested:
                    continue
                item: dict = {
                    "name": child.name,
                    "path": relative,
                    "type": "directory" if child.is_dir() else "file",
                    "size": None if child.is_dir() else stat.st_size,
                    "modified_at": datetime.fromtimestamp(
                        stat.st_mtime, tz=UTC
                    ).isoformat(),
                    "previewable": child.is_file(),
                }
                if child.is_dir():
                    item["children"] = nested
                result.append(item)
            return result

        # Remove only genuinely empty legacy task directories. Directories containing any file
        # remain untouched, even though task artifacts are intentionally hidden from this API.
        for directory in sorted(
            (item for item in config.knowledge_base_dir.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            if directory == topics_directory or within_directory(directory, topics_directory):
                continue
            with suppress(OSError):
                directory.rmdir()

        profile = db.active_knowledge_profile()
        name = profile["name"] if profile else "知识库"
        children = entries(topics_directory)
        return [{
            "name": name,
            "path": "@knowledge-base",
            "type": "directory",
            "size": None,
            "modified_at": datetime.fromtimestamp(
                topics_directory.stat().st_mtime, tz=UTC
            ).isoformat(),
            "previewable": False,
            "children": children,
        }]

    @app.get("/api/knowledge/file", response_class=PlainTextResponse)
    def read_knowledge_file(path: str) -> str:
        file_path = knowledge_file(path)
        if file_path.suffix.lower() not in {".md", ".markdown", ".txt", ".json"}:
            raise HTTPException(status_code=415, detail="该文件类型不支持在线预览")
        if file_path.stat().st_size > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件超过 2 MB，请下载后查看")
        try:
            return file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=415, detail="该文件不是 UTF-8 文本") from exc

    @app.get("/api/knowledge/file/download")
    def download_knowledge_file(path: str) -> FileResponse:
        file_path = knowledge_file(path)
        return FileResponse(file_path, filename=file_path.name)

    @app.post("/api/knowledge/file/refactor", response_class=PlainTextResponse)
    def refactor_knowledge_file(path: str) -> str:
        file_path = knowledge_file(path)
        if file_path.suffix.lower() not in {".md", ".markdown"}:
            raise HTTPException(status_code=415, detail="只能重构 Markdown 主题")
        try:
            with worker.pipeline.knowledge_write_lock:
                return refactor_topic_document(file_path, config)
        except (KnowledgeOrganizerError, AIServiceError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/knowledge/profiles")
    def knowledge_profiles() -> list[dict]:
        return db.list_knowledge_profiles()

    @app.post("/api/knowledge/profiles", status_code=201)
    def create_knowledge_profile(request: KnowledgeProfileRequest) -> dict:
        return db.save_knowledge_profile(prepare_profile(request))

    @app.put("/api/knowledge/profiles/{profile_id}")
    def update_knowledge_profile(profile_id: str, request: KnowledgeProfileRequest) -> dict:
        if not db.get_knowledge_profile(profile_id):
            raise HTTPException(status_code=404, detail="知识库 Profile 不存在")
        return db.save_knowledge_profile(prepare_profile(request), profile_id)

    @app.post("/api/knowledge/profiles/{profile_id}/activate")
    def activate_knowledge_profile(profile_id: str) -> dict:
        profile = db.activate_knowledge_profile(profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="知识库 Profile 不存在")
        return profile

    @app.delete("/api/knowledge/profiles/{profile_id}", status_code=204)
    def delete_knowledge_profile(profile_id: str) -> None:
        if not db.get_knowledge_profile(profile_id):
            raise HTTPException(status_code=404, detail="知识库 Profile 不存在")
        if not db.delete_knowledge_profile(profile_id):
            raise HTTPException(status_code=409, detail="不能删除当前启用或唯一的 Profile")

    @app.post("/api/knowledge/topic-suggestion")
    def suggest_knowledge_topic(request: TopicSuggestionRequest) -> dict:
        profile = db.get_knowledge_profile(request.profile_id)
        if not profile:
            raise HTTPException(status_code=404, detail="知识库 Profile 不存在")
        existing = [
            {
                "name": item["name"],
                "path": item["path"],
                "description": item["description"],
            }
            for item in profile["preferred_topics"]
        ]
        try:
            response = chat(
                [
                    {
                        "role": "system",
                        "content": render_prompt(PROMPTS_DIR / "topic-suggestion-system.md"),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "profile": {
                                    "name": profile["name"],
                                    "mode": profile["mode"],
                                    "scope": profile["scope"],
                                },
                                "existing_topics": existing,
                                "new_topic": {
                                    "name": request.name,
                                    "description": request.description,
                                },
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                config,
                max_tokens=2000,
            )
            start, end = response.find("{"), response.rfind("}")
            suggestion = json.loads(response[start : end + 1])
            action = str(suggestion.get("action"))
            path = validate_topic_path(suggestion.get("path"))
            known_paths = {item["path"] for item in existing}
            if action == "use_existing" and path not in known_paths:
                raise KnowledgeProfileError("AI 推荐了不存在的已有主题")
            if action not in {"use_existing", "create"}:
                raise KnowledgeProfileError("AI 返回了无效动作")
            if path in known_paths:
                action = "use_existing"
            return {
                "action": action,
                "path": path,
                "reason": str(suggestion.get("reason") or "").strip()[:300],
            }
        except AIServiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except (KnowledgeProfileError, json.JSONDecodeError, TypeError) as exc:
            fallback = default_topic_path(profile, request.name)
            return {
                "action": "create",
                "path": fallback,
                "reason": f"AI 建议不可用，已生成安全路径：{exc}",
            }

    return app


app = create_app()
