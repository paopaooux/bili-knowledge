from __future__ import annotations

import json
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from .ai import AIServiceError, chat, test_service
from .config import Settings, load_settings
from .constants import STAGES
from .database import Database, utcnow
from .knowledge_profile import (
    KnowledgeProfileError,
    default_topic_path,
    load_knowledge_profile,
    normalize_knowledge_profile,
    validate_topic_path,
)
from .pipeline import JobWorker, Pipeline
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


def create_app(settings: Settings | None = None, start_worker: bool = True) -> FastAPI:
    config = settings or load_settings()
    db = Database(config.database_path)
    db.migrate()
    db.seed_knowledge_profile(load_knowledge_profile(config.knowledge_profile_path))
    worker = JobWorker(Pipeline(db, config))

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
            "worker": "running" if worker.thread and worker.thread.is_alive() else "stopped",
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
        job_id = db.create_job(request.video_id, unique_ids)
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

    @app.post("/api/jobs/{job_id}/retry")
    def retry(job_id: str, request: RetryRequest) -> dict:
        job = db.job_detail(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="任务不存在")
        if job["status"] not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="仅失败或已取消的任务可以重试")
        selected = [
            part for part in job["parts"] if not request.part_id or part["id"] == request.part_id
        ]
        if not selected:
            raise HTTPException(status_code=422, detail="指定分 P 不属于该任务")
        stage_index = STAGES.index(request.stage)
        with db.transaction() as connection:
            for part in selected:
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

    def document_artifact(artifact_id: str) -> tuple[dict, Path]:
        artifact = db.one("SELECT * FROM artifacts WHERE id=?", (artifact_id,))
        if not artifact or artifact["kind"] not in {"document", "index", "topic"}:
            raise HTTPException(status_code=404, detail="文档不存在")
        path = Path(artifact["path"])
        if not within_directory(path, config.knowledge_base_dir) or not path.is_file():
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
        if not within_directory(path, config.knowledge_base_dir) or not path.is_file():
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

    @app.post("/api/settings/open-output")
    def open_output() -> dict:
        try:
            if sys.platform == "darwin":
                command = ["open", str(config.knowledge_base_dir)]
            elif sys.platform.startswith("win"):
                command = ["explorer", str(config.knowledge_base_dir)]
            else:
                command = ["xdg-open", str(config.knowledge_base_dir)]
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return {"ok": True}
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"无法打开输出目录：{exc}") from exc

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
                        "content": (
                            "你为 Markdown 知识库推荐主题位置。判断新主题是否应复用已有主题；否则生成最多四层的安全相对 .md 路径。"
                            '只输出 JSON：{"action":"use_existing|create","path":"...md","reason":"简短理由"}。'
                        ),
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
                max_tokens=500,
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
