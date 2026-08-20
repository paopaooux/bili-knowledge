from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from queue import Queue
from urllib.parse import parse_qs, urlparse

import httpx
import yt_dlp

from .ai import chat, transcribe_audio
from .config import Settings
from .constants import STAGES
from .database import Database, utcnow
from .knowledge import organize_document
from .prompting import render_prompt
from .subtitles import normalize_segments, parse_subtitle
from .utils import safe_filename
from .video import BROWSER_HEADERS, BVID_PATTERN

logger = logging.getLogger("uvicorn.error")
PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


class Cancelled(RuntimeError):
    pass


def _json_read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


class Pipeline:
    def __init__(self, db: Database, settings: Settings):
        self.db = db
        self.settings = settings
        # Routing and organizing update a shared topic catalog and shared Markdown files.
        # Keep this critical section serial while allowing all earlier stages to overlap.
        self.knowledge_write_lock = threading.Lock()

    def _cancel_guard(self, job_id: str) -> None:
        job = self.db.one("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,))
        if not job or job["cancel_requested"]:
            raise Cancelled("任务已取消")

    def _paths(self, job: dict, part: dict) -> dict[str, Path]:
        directory_name = safe_filename(f"{job['video_title']}-{job['bvid']}", 110)
        root = self.settings.source_output_dir / directory_name
        legacy_root = self.settings.knowledge_base_dir / directory_name
        # Existing jobs created before source/knowledge storage was split keep using their
        # original artifacts, so preview and organize-only retries continue to work.
        if legacy_root.is_dir() and any(item.is_file() for item in legacy_root.rglob("*")):
            root = legacy_root
        part_dir = root / "parts" / safe_filename(f"P{part['part_index']:02d}-{part['title']}", 100)
        temp = self.settings.temp_dir / job["id"] / part["id"]
        return {
            "root": root,
            "part": part_dir,
            "transcript": part_dir / "transcript.json",
            "metadata": part_dir / "metadata.json",
            "document": part_dir / "document.md",
            "knowledge_update": part_dir / "knowledge-update.json",
            "temp": temp,
            "audio": temp / "audio.mp3",
        }

    def run(self, job_id: str) -> None:
        job = self.db.job_detail(job_id)
        if not job:
            return
        logger.info("Job started job_id=%s bvid=%s parts=%d", job_id, job["bvid"], len(job["parts"]))
        self.db.execute(
            "UPDATE jobs SET status='running',error=NULL,updated_at=? WHERE id=?",
            (utcnow(), job_id),
        )
        try:
            for part in job["parts"]:
                self._cancel_guard(job_id)
                self.db.execute(
                    "UPDATE job_parts SET status='running' WHERE job_id=? AND part_id=?",
                    (job_id, part["id"]),
                )
                self._run_part(job, part)
                self.db.execute(
                    "UPDATE job_parts SET status='completed' WHERE job_id=? AND part_id=?",
                    (job_id, part["id"]),
                )
            self.db.execute(
                "UPDATE jobs SET status='completed',error=NULL,completed_at=?,updated_at=? WHERE id=?",
                (utcnow(), utcnow(), job_id),
            )
            logger.info("Job completed job_id=%s", job_id)
            shutil.rmtree(self.settings.temp_dir / job_id, ignore_errors=True)
        except Cancelled as exc:
            self.db.execute(
                "UPDATE jobs SET status='cancelled',error=?,updated_at=? WHERE id=?",
                (str(exc), utcnow(), job_id),
            )
        except Exception as exc:
            logger.exception("Job %s failed", job_id)
            self.db.execute(
                "UPDATE jobs SET status='failed',error=?,updated_at=? WHERE id=?",
                (str(exc), utcnow(), job_id),
            )

    def _run_part(self, job: dict, part: dict) -> None:
        paths = self._paths(job, part)
        paths["part"].mkdir(parents=True, exist_ok=True)
        paths["temp"].mkdir(parents=True, exist_ok=True)
        handlers = {
            "parse": lambda: self._parse(job, part, paths),
            "acquire": lambda: self._acquire(job, part, paths),
            "transcribe": lambda: self._transcribe(job, part, paths),
            "generate": lambda: self._generate(job, part, paths),
            "organize": lambda: self._organize(job, part, paths),
            "publish": lambda: self._publish(job, part, paths),
        }
        for stage in STAGES:
            current = self.db.one(
                "SELECT status FROM job_stages WHERE job_id=? AND part_id=? AND stage=?",
                (job["id"], part["id"], stage),
            )
            if current and current["status"] in {"completed", "skipped"}:
                continue
            self._cancel_guard(job["id"])
            logger.info(
                "Stage started job_id=%s part_id=%s stage=%s",
                job["id"],
                part["id"],
                stage,
            )
            self.db.set_stage(job["id"], part["id"], stage, "running")
            try:
                status = handlers[stage]() or "completed"
                self.db.set_stage(job["id"], part["id"], stage, status)
                logger.info(
                    "Stage finished job_id=%s part_id=%s stage=%s status=%s",
                    job["id"],
                    part["id"],
                    stage,
                    status,
                )
            except Exception as exc:
                self.db.set_stage(job["id"], part["id"], stage, "failed", str(exc))
                self.db.execute(
                    "UPDATE job_parts SET status='failed' WHERE job_id=? AND part_id=?",
                    (job["id"], part["id"]),
                )
                raise

    def _parse(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if not part.get("url"):
            raise RuntimeError("分 P 缺少来源链接，请重新解析")
        metadata = {
            "title": part["title"],
            "video_title": job["video_title"],
            "bvid": job["bvid"],
            "part": part["part_index"],
            "source_url": part["url"],
            "uploader": None,
            "published_at": None,
            "duration": part.get("duration"),
            "language": "unknown",
            "subtitle_source": None,
            "generated_at": None,
            "model": self.settings.llm_model,
        }
        video = self.db.one(
            "SELECT uploader,published_at FROM videos WHERE id=?", (job["video_id"],)
        )
        metadata.update(video or {})
        _json_write(paths["metadata"], metadata)
        self.db.save_artifact(job["id"], part["id"], "metadata", paths["metadata"])
        return "completed"

    def _acquire(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if paths["transcript"].exists() and _json_read(paths["transcript"]):
            self.db.save_artifact(job["id"], part["id"], "transcript", paths["transcript"])
            return "completed"
        subtitles = json.loads(
            self.db.one("SELECT subtitle_json FROM parts WHERE id=?", (part["id"],))[
                "subtitle_json"
            ]
        )
        subtitles.sort(
            key=lambda item: (
                0 if str(item.get("language", "")).lower().startswith("zh") else 1,
                0 if item.get("kind") == "manual" else 1,
            )
        )
        for item in subtitles:
            url = item["url"]
            if url.startswith("//"):
                url = "https:" + url
            try:
                response = httpx.get(url, timeout=30, follow_redirects=True)
                response.raise_for_status()
                segments = parse_subtitle(response.text, item.get("extension", "vtt"), "subtitle")
                if segments:
                    _json_write(paths["transcript"], segments)
                    self._update_metadata(
                        paths, subtitle_source="subtitle", language=item.get("language", "unknown")
                    )
                    self.db.save_artifact(job["id"], part["id"], "transcript", paths["transcript"])
                    return "completed"
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                # 某种字幕格式或地址失败后继续尝试同语言的其他格式。
                continue
        self._download_audio(part["url"], paths["audio"])
        self.db.save_artifact(job["id"], part["id"], "audio_temp", paths["audio"])
        return "completed"

    def _download_audio(self, url: str, destination: Path) -> None:
        options = {
            "quiet": True,
            "no_warnings": True,
            "ignoreconfig": True,
            "format": "bestaudio/best",
            "outtmpl": str(destination.with_suffix(".%(ext)s")),
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "96"}
            ],
            "http_headers": BROWSER_HEADERS,
        }
        if self.settings.cookie_file:
            options["cookiefile"] = str(self.settings.cookie_file)
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([url])
        except Exception as exc:  # noqa: BLE001 - yt-dlp extractors raise varied exceptions
            try:
                self._download_audio_via_api(url, destination)
            except (httpx.HTTPError, ValueError, KeyError, RuntimeError, OSError) as fallback_exc:
                raise RuntimeError(
                    f"字幕不可用且音频下载失败：{exc}；API 备用下载也失败：{fallback_exc}"
                ) from exc
        if not destination.exists():
            matches = list(destination.parent.glob("audio*.mp3"))
            if matches:
                matches[0].replace(destination)
        if not destination.exists():
            raise RuntimeError("音频下载完成但未找到输出文件，请检查 ffmpeg")

    def _download_audio_via_api(self, url: str, destination: Path) -> None:
        match = BVID_PATTERN.search(url)
        if not match:
            raise RuntimeError("来源链接缺少 BV 号")
        bvid = "BV" + match.group(0)[2:]
        page_number = int((parse_qs(urlparse(url).query).get("p") or ["1"])[0])
        with httpx.Client(headers=BROWSER_HEADERS, timeout=30) as client:
            view = client.get(
                "https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}
            )
            view.raise_for_status()
            view_payload = view.json()
            pages = (view_payload.get("data") or {}).get("pages") or []
            page = next(
                (item for item in pages if int(item.get("page") or 0) == page_number), None
            )
            if not page:
                raise RuntimeError("Bilibili API 未返回对应分 P")
            play = client.get(
                "https://api.bilibili.com/x/player/playurl",
                params={"bvid": bvid, "cid": page["cid"], "fnval": 16, "qn": 64},
            )
            play.raise_for_status()
            play_payload = play.json()
            audio_streams = ((play_payload.get("data") or {}).get("dash") or {}).get("audio") or []
            if play_payload.get("code") != 0 or not audio_streams:
                raise RuntimeError(play_payload.get("message") or "Bilibili API 未返回音频流")
            stream = max(audio_streams, key=lambda item: item.get("bandwidth") or 0)
            candidates = [stream.get("baseUrl") or stream.get("base_url")]
            candidates.extend(stream.get("backupUrl") or stream.get("backup_url") or [])
            source = destination.with_suffix(".m4s")
            download_error: Exception | None = None
            for candidate in filter(None, candidates):
                try:
                    with client.stream(
                        "GET",
                        candidate,
                        headers={"Referer": f"https://www.bilibili.com/video/{bvid}"},
                    ) as response:
                        response.raise_for_status()
                        with source.open("wb") as handle:
                            for chunk in response.iter_bytes():
                                handle.write(chunk)
                    break
                except httpx.HTTPError as exc:
                    download_error = exc
            else:
                raise RuntimeError(f"Bilibili 音频流不可下载：{download_error}")
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame",
                    "-b:a", "96k", str(destination),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr.strip()[-500:] or "ffmpeg 转换失败")
        finally:
            source.unlink(missing_ok=True)

    def _transcribe(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if paths["transcript"].exists() and _json_read(paths["transcript"]):
            return "skipped"
        if not paths["audio"].exists():
            raise RuntimeError("缺少待转写音频；请从获取字幕/下载音频阶段重试")
        chunks = self._split_audio(paths["audio"], paths["temp"] / "chunks")
        segments = []
        detected_language = None
        previous_text = ""
        for index, (chunk, start, duration) in enumerate(chunks, 1):
            self._cancel_guard(job["id"])
            logger.info(
                "Transcribing audio chunk job_id=%s part_id=%s chunk=%d/%d start=%.3fs duration=%.3fs",
                job["id"],
                part["id"],
                index,
                len(chunks),
                start,
                duration,
            )
            payload = transcribe_audio(chunk, self.settings)
            detected_language = detected_language or payload.get("language")
            raw_text = str(payload.get("text") or "").strip()
            if self.settings.stt_provider == "dashscope_flash" and previous_text:
                payload["text"] = self._trim_transcript_overlap(previous_text, raw_text)
            raw_segments = payload.get("segments") or [
                {"start": 0, "end": duration, "text": payload.get("text", "")}
            ]
            normalized = normalize_segments(raw_segments, "stt")
            for segment in normalized:
                segment["start"] = round(segment["start"] + start, 3)
                segment["end"] = round(segment["end"] + start, 3)
            segments.extend(normalized)
            previous_text = raw_text
        if not segments:
            raise RuntimeError("所有音频切片均未产生转写文本")
        _json_write(paths["transcript"], segments)
        self._update_metadata(paths, subtitle_source="stt", language=detected_language or "unknown")
        self.db.save_artifact(job["id"], part["id"], "transcript", paths["transcript"])
        return "completed"

    def _split_audio(self, audio: Path, output: Path) -> list[tuple[Path, float, float]]:
        output.mkdir(parents=True, exist_ok=True)
        total_duration = self._probe_duration(audio)
        if total_duration <= 0:
            raise RuntimeError("无法读取音频时长，不能安全切片")
        limited_provider = self.settings.stt_provider in {"dashscope_realtime", "dashscope_flash"}
        chunk_seconds = min(self.settings.audio_chunk_seconds, 240) if limited_provider else self.settings.audio_chunk_seconds
        overlap = min(5.0, chunk_seconds / 10) if self.settings.stt_provider == "dashscope_flash" else 0.0
        step = chunk_seconds - overlap
        chunks = []
        start = 0.0
        index = 0
        while start < total_duration - 0.01:
            requested_duration = min(float(chunk_seconds), total_duration - start)
            destination = output / f"chunk-{index:04d}.mp3"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(audio),
                "-ss",
                f"{start:.3f}",
                "-t",
                f"{requested_duration:.3f}",
                "-vn",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "96k",
                str(destination),
            ]
            try:
                subprocess.run(command, check=True, capture_output=True, text=True)
            except FileNotFoundError as exc:
                raise RuntimeError("未找到 ffmpeg，请安装后再重试") from exc
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(f"音频切片失败：{exc.stderr[-500:]}") from exc
            actual_duration = self._probe_duration(destination)
            if actual_duration <= 0:
                raise RuntimeError(f"音频切片 {index + 1} 没有有效时长")
            chunks.append((destination, start, actual_duration))
            if start + requested_duration >= total_duration - 0.01:
                break
            start += step
            index += 1
        logger.info(
            "Audio split completed provider=%s total=%.3fs chunks=%d chunk_limit=%.1fs overlap=%.1fs",
            self.settings.stt_provider,
            total_duration,
            len(chunks),
            float(chunk_seconds),
            overlap,
        )
        return chunks

    @staticmethod
    def _trim_transcript_overlap(previous: str, current: str) -> str:
        def compact(value: str) -> tuple[str, list[int]]:
            characters = []
            positions = []
            for position, character in enumerate(value):
                if character.isalnum():
                    characters.append(character.casefold())
                    positions.append(position)
            return "".join(characters), positions

        previous_compact, _ = compact(previous)
        current_compact, current_positions = compact(current)
        maximum = min(160, len(previous_compact), len(current_compact))
        for size in range(maximum, 3, -1):
            if previous_compact[-size:] == current_compact[:size]:
                cut = current_positions[size - 1] + 1
                trimmed = current[cut:].lstrip(" ，。！？；：、,.!?;:\n\t")
                logger.info(
                    "Trimmed exact ASR chunk overlap matched_chars=%d removed_chars=%d",
                    size,
                    cut,
                )
                return trimmed
        return current

    @staticmethod
    def _probe_duration(path: Path) -> float:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    str(path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            return float(result.stdout.strip())
        except (OSError, subprocess.SubprocessError, ValueError):
            return 0.0

    def _generate(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        segments = _json_read(paths["transcript"])
        if not isinstance(segments, list) or not segments:
            raise RuntimeError("转写为空，无法生成知识稿")
        transcript = "\n".join(segment["text"] for segment in segments)
        logger.info(
            "Generating knowledge draft job_id=%s part_id=%s segments=%d transcript_chars=%d",
            job["id"],
            part["id"],
            len(segments),
            len(transcript),
        )
        self._cancel_guard(job["id"])
        metadata = _json_read(paths["metadata"])
        messages = [
            {
                "role": "system",
                "content": render_prompt(PROMPTS_DIR / "knowledge-draft-system.md"),
            },
            {
                "role": "user",
                "content": render_prompt(
                    PROMPTS_DIR / "knowledge-draft-user.md",
                    transcript=transcript,
                ),
            },
        ]
        title, body = "", ""
        last_error: RuntimeError | None = None
        for attempt in range(2):
            self._cancel_guard(job["id"])
            response = chat(
                messages,
                self.settings,
                max_tokens=self.settings.knowledge_draft_max_tokens,
            )
            try:
                title, body = self._parse_knowledge_draft(response, metadata)
                break
            except RuntimeError as exc:
                if "没有返回有效的 title/body JSON" not in str(exc):
                    raise
                last_error = exc
                logger.warning(
                    "Knowledge draft returned invalid JSON job_id=%s part_id=%s attempt=%d snippet=%r",
                    job["id"],
                    part["id"],
                    attempt + 1,
                    response[:120],
                )
                messages.append({"role": "assistant", "content": response[:4000]})
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "刚才的输出不是有效的 JSON 对象。请只输出一个 JSON 对象："
                            '{"title":"知识主题标题","body":"Markdown 正文"}，'
                            "不要输出代码围栏、解释或任何其他内容。"
                        ),
                    }
                )
        else:
            assert last_error is not None
            raise last_error
        metadata["generated_at"] = utcnow()
        metadata["model"] = self.settings.llm_model
        _json_write(paths["metadata"], metadata)
        markdown = self._render_document(title, body)
        paths["document"].write_text(markdown, encoding="utf-8")
        logger.info(
            "Knowledge document written job_id=%s part_id=%s title=%r chars=%d path=%s",
            job["id"],
            part["id"],
            title,
            len(markdown),
            paths["document"],
        )
        self.db.save_artifact(job["id"], part["id"], "document", paths["document"])
        summary = body[:500]
        self.db.execute(
            "UPDATE job_parts SET summary=? WHERE job_id=? AND part_id=?",
            (summary, job["id"], part["id"]),
        )
        return "completed"

    @staticmethod
    def _parse_knowledge_draft(response: str, metadata: dict) -> tuple[str, str]:
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE).strip()
        # 优先按 JSON 解析：取第一个 { 到最后一个 } 之间的内容，容忍前后多余文字与重复键。
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
                title = str(payload.get("title") or "").strip()
                body = str(payload.get("body") or "").strip()
            except (json.JSONDecodeError, TypeError, ValueError):
                payload = None
            if payload is not None and (title or body):
                return Pipeline._finish_knowledge_draft(title, body, metadata)
        # 模型没有按 JSON 输出时，回退为 Markdown：第一个一级标题作为主题标题，其余为正文。
        heading = re.search(r"(?m)^#\s+([^\n]+)", text)
        if heading:
            title = heading.group(1).strip()
            body = text[heading.end() :].strip()
            if title and body:
                return Pipeline._finish_knowledge_draft(title, body, metadata)
        raise RuntimeError("知识稿模型没有返回有效的 title/body JSON，输出开头为：" + text[:120])

    @staticmethod
    def _finish_knowledge_draft(title: str, body: str, metadata: dict) -> tuple[str, str]:
        if not title or "\n" in title or len(title) > 100:
            raise RuntimeError("知识稿标题为空、过长或包含换行")
        video_titles = {
            str(metadata.get("title") or "").strip(),
            str(metadata.get("video_title") or "").strip(),
        }
        if title in video_titles:
            raise RuntimeError("知识稿模型照抄了视频标题，没有生成知识主题标题")
        if not body:
            raise RuntimeError("知识稿正文为空")
        body = re.sub(r"^#\s+[^\n]+\n+", "", body).strip()
        return title, body

    @staticmethod
    def _render_document(title: str, body: str) -> str:
        return f"# {title}\n\n{body.strip()}\n"

    def _publish(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if not paths["document"].exists():
            raise RuntimeError("知识稿文件不存在")
        self.db.save_artifact(job["id"], part["id"], "document", paths["document"])
        return "completed"

    def _organize(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if not paths["document"].exists():
            raise RuntimeError("知识稿文件不存在，无法归档知识")
        with self.knowledge_write_lock:
            result = organize_document(
                paths["document"],
                self.settings,
                profile=self.db.active_knowledge_profile(),
            )
            logger.info(
                "Knowledge organized job_id=%s part_id=%s updates=%d targets=%s",
                job["id"],
                part["id"],
                len(result["updates"]),
                [update["plan"]["target_path"] for update in result["updates"]],
            )
            _json_write(paths["knowledge_update"], result)
            self.db.save_artifact(
                job["id"], part["id"], "knowledge_update", paths["knowledge_update"]
            )
            for update in result["updates"]:
                topic_path = Path(update["topic_path"])
                relative_path = topic_path.relative_to(
                    self.settings.knowledge_base_dir / "topics"
                ).as_posix()
                self.db.save_topic_state(
                    relative_path,
                    job.get("bvid"),
                    update["plan"]["action"],
                    update["updated_at"],
                )
                self.db.save_artifact(job["id"], part["id"], "topic", topic_path)
        return "completed"

    @staticmethod
    def _update_metadata(paths: dict[str, Path], **values: object) -> None:
        metadata = _json_read(paths["metadata"])
        metadata.update(values)
        _json_write(paths["metadata"], metadata)


class JobWorker:
    def __init__(self, pipeline: Pipeline, concurrency: int = 8):
        self.pipeline = pipeline
        self.queue: Queue[str | tuple[str, ...] | None] = Queue()
        self.concurrency = max(1, min(32, int(concurrency)))
        self.threads: list[threading.Thread] = []
        self._queued: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if any(thread.is_alive() for thread in self.threads):
                return
            self.threads = [
                threading.Thread(
                    target=self._loop,
                    name=f"job-worker-{index + 1}",
                    daemon=True,
                )
                for index in range(self.concurrency)
            ]
            for thread in self.threads:
                thread.start()

    def stop(self) -> None:
        threads = [thread for thread in self.threads if thread.is_alive()]
        for _ in threads:
            self.queue.put(None)
        for thread in threads:
            thread.join(timeout=5)

    @property
    def alive_count(self) -> int:
        return sum(thread.is_alive() for thread in self.threads)

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._queued:
                return
            self._queued.add(job_id)
            self.queue.put(job_id)

    def enqueue_serial(self, job_ids: list[str]) -> None:
        """Run an ordered maintenance batch in one worker instead of spreading it across the pool."""
        with self._lock:
            pending = tuple(job_id for job_id in dict.fromkeys(job_ids) if job_id not in self._queued)
            if not pending:
                return
            self._queued.update(pending)
            self.queue.put(pending)

    def _loop(self) -> None:
        while True:
            job_id = self.queue.get()
            if job_id is None:
                self.queue.task_done()
                return
            job_ids = job_id if isinstance(job_id, tuple) else (job_id,)
            try:
                for current_job_id in job_ids:
                    try:
                        self.pipeline.run(current_job_id)
                    except Exception:
                        # Pipeline.run normally records failures itself. Keep a worker alive if
                        # an unexpected error escapes so the rest of the queue is still serviced.
                        logger.exception("Unhandled worker error job_id=%s", current_job_id)
                    finally:
                        with self._lock:
                            self._queued.discard(current_job_id)
            finally:
                self.queue.task_done()
