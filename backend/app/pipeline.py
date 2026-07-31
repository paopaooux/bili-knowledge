from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import threading
from pathlib import Path
from queue import Queue

import httpx
import yt_dlp

from .ai import chat, transcribe_audio
from .config import Settings
from .constants import STAGES
from .database import Database, utcnow
from .knowledge import organize_document
from .subtitles import normalize_segments, parse_subtitle
from .utils import format_timestamp, safe_filename, timestamp_url

logger = logging.getLogger(__name__)
TIME_RANGE_PATTERN = re.compile(
    r"\[(?P<start>\d{1,2}:\d{2}(?::\d{2})?)\s*[-–—]\s*"
    r"(?P<end>\d{1,2}:\d{2}(?::\d{2})?)\](?!\()"
)


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

    def _cancel_guard(self, job_id: str) -> None:
        job = self.db.one("SELECT cancel_requested FROM jobs WHERE id=?", (job_id,))
        if not job or job["cancel_requested"]:
            raise Cancelled("任务已取消")

    def _paths(self, job: dict, part: dict) -> dict[str, Path]:
        root = self.settings.knowledge_base_dir / safe_filename(
            f"{job['video_title']}-{job['bvid']}", 110
        )
        part_dir = root / "parts" / safe_filename(f"P{part['part_index']:02d}-{part['title']}", 100)
        temp = self.settings.temp_dir / job["id"] / part["id"]
        return {
            "root": root,
            "part": part_dir,
            "transcript": part_dir / "transcript.json",
            "metadata": part_dir / "metadata.json",
            "document": part_dir / "document.md",
            "knowledge_update": part_dir / "knowledge-update.json",
            "index": root / "README.md",
            "temp": temp,
            "audio": temp / "audio.mp3",
        }

    def run(self, job_id: str) -> None:
        job = self.db.job_detail(job_id)
        if not job:
            return
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
            self._publish_index(job_id)
            self.db.execute(
                "UPDATE jobs SET status='completed',error=NULL,completed_at=?,updated_at=? WHERE id=?",
                (utcnow(), utcnow(), job_id),
            )
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
            self.db.set_stage(job["id"], part["id"], stage, "running")
            try:
                status = handlers[stage]() or "completed"
                self.db.set_stage(job["id"], part["id"], stage, status)
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
        }
        if self.settings.cookie_file:
            options["cookiefile"] = str(self.settings.cookie_file)
        try:
            with yt_dlp.YoutubeDL(options) as downloader:
                downloader.download([url])
        except Exception as exc:
            raise RuntimeError(f"字幕不可用且音频下载失败：{exc}") from exc
        if not destination.exists():
            matches = list(destination.parent.glob("audio*.mp3"))
            if matches:
                matches[0].replace(destination)
        if not destination.exists():
            raise RuntimeError("音频下载完成但未找到输出文件，请检查 ffmpeg")

    def _transcribe(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if paths["transcript"].exists() and _json_read(paths["transcript"]):
            return "skipped"
        if not paths["audio"].exists():
            raise RuntimeError("缺少待转写音频；请从获取字幕/下载音频阶段重试")
        chunks = self._split_audio(paths["audio"], paths["temp"] / "chunks")
        segments = []
        offset = 0.0
        detected_language = None
        for chunk, duration in chunks:
            self._cancel_guard(job["id"])
            payload = transcribe_audio(chunk, self.settings)
            detected_language = detected_language or payload.get("language")
            raw_segments = payload.get("segments") or [
                {"start": 0, "end": duration, "text": payload.get("text", "")}
            ]
            normalized = normalize_segments(raw_segments, "stt")
            for segment in normalized:
                segment["start"] = round(segment["start"] + offset, 3)
                segment["end"] = round(segment["end"] + offset, 3)
            segments.extend(normalized)
            offset += duration
        if not segments:
            raise RuntimeError("所有音频切片均未产生转写文本")
        _json_write(paths["transcript"], segments)
        self._update_metadata(paths, subtitle_source="stt", language=detected_language or "unknown")
        self.db.save_artifact(job["id"], part["id"], "transcript", paths["transcript"])
        return "completed"

    def _split_audio(self, audio: Path, output: Path) -> list[tuple[Path, float]]:
        output.mkdir(parents=True, exist_ok=True)
        pattern = output / "chunk-%04d.mp3"
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(audio),
            "-f",
            "segment",
            "-segment_time",
            str(
                min(self.settings.audio_chunk_seconds, 300)
                if self.settings.stt_provider in {"dashscope_realtime", "dashscope_flash"}
                else self.settings.audio_chunk_seconds
            ),
            "-c:a",
            "libmp3lame",
            "-b:a",
            "96k",
            str(pattern),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError("未找到 ffmpeg，请安装后再重试") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"音频切片失败：{exc.stderr[-500:]}") from exc
        chunks = sorted(output.glob("chunk-*.mp3"))
        if not chunks:
            raise RuntimeError("ffmpeg 未生成音频切片")
        return [(item, self._probe_duration(item)) for item in chunks]

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
        chunks, current, size = [], [], 0
        for segment in segments:
            line = f"[{format_timestamp(segment['start'])}-{format_timestamp(segment['end'])}] {segment['text']}"
            if current and size + len(line) > self.settings.transcript_chunk_chars:
                chunks.append("\n".join(current))
                current, size = [], 0
            current.append(line)
            size += len(line)
        if current:
            chunks.append("\n".join(current))
        notes = []
        for index, chunk in enumerate(chunks, 1):
            self._cancel_guard(job["id"])
            notes.append(
                chat(
                    [
                        {
                            "role": "system",
                            "content": "你是严谨的知识编辑。只依据转写提炼；不得补充外部事实；不确定或听不清处明确标注。保留关键时间范围。",
                        },
                        {
                            "role": "user",
                            "content": f"这是第 {index}/{len(chunks)} 段转写。提炼摘要、观点、概念和可引用依据：\n\n{chunk}",
                        },
                    ],
                    self.settings,
                )
            )
        body = chat(
            [
                {
                    "role": "system",
                    "content": (
                        "你是严谨的中文知识编辑。仅依据所给分段笔记撰写 Markdown。必须依次包含："
                        "## 内容摘要、## 核心观点与结论、## 主题正文（可有三级标题）、## 术语与概念、## 依据引用。"
                        "依据引用必须保留 [开始-结束] 时间范围。不确定内容明确标注，不得编造。不要输出 YAML，也不要输出完整转写。"
                    ),
                },
                {"role": "user", "content": "合并以下分段笔记：\n\n" + "\n\n---\n\n".join(notes)},
            ],
            self.settings,
            max_tokens=5000,
        )
        body = self._link_evidence_timestamps(body, part["url"])
        metadata = _json_read(paths["metadata"])
        metadata["generated_at"] = utcnow()
        metadata["model"] = self.settings.llm_model
        _json_write(paths["metadata"], metadata)
        markdown = self._render_document(metadata, body, segments)
        paths["document"].write_text(markdown, encoding="utf-8")
        self.db.save_artifact(job["id"], part["id"], "document", paths["document"])
        summary = notes[0][:500] if notes else ""
        self.db.execute(
            "UPDATE job_parts SET summary=? WHERE job_id=? AND part_id=?",
            (summary, job["id"], part["id"]),
        )
        return "completed"

    @staticmethod
    def _link_evidence_timestamps(body: str, source_url: str) -> str:
        def seconds(value: str) -> int:
            units = [int(item) for item in value.split(":")]
            return units[-1] + units[-2] * 60 + (units[-3] * 3600 if len(units) == 3 else 0)

        def replacement(match: re.Match[str]) -> str:
            label = f"{match.group('start')}–{match.group('end')}"
            return f"[{label}]({timestamp_url(source_url, seconds(match.group('start')))})"

        return TIME_RANGE_PATTERN.sub(replacement, body)

    def _render_document(self, metadata: dict, body: str, segments: list[dict]) -> str:
        yaml_lines = ["---"]
        fields = [
            "title",
            "video_title",
            "bvid",
            "part",
            "source_url",
            "uploader",
            "published_at",
            "duration",
            "language",
            "subtitle_source",
            "generated_at",
            "model",
        ]
        for key in fields:
            yaml_lines.append(f"{key}: {json.dumps(metadata.get(key), ensure_ascii=False)}")
        yaml_lines.extend(["---", "", f"# {metadata['title']}", ""])
        transcript = ["## 完整带时间戳转写", ""]
        for segment in segments:
            label = f"{format_timestamp(segment['start'])}–{format_timestamp(segment['end'])}"
            transcript.append(
                f"- [{label}]({timestamp_url(metadata['source_url'], segment['start'])}) {segment['text']}"
            )
        return "\n".join(yaml_lines) + body.strip() + "\n\n" + "\n".join(transcript) + "\n"

    def _publish(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if not paths["document"].exists():
            raise RuntimeError("知识稿文件不存在")
        self.db.save_artifact(job["id"], part["id"], "document", paths["document"])
        return "completed"

    def _organize(self, job: dict, part: dict, paths: dict[str, Path]) -> str:
        if not paths["document"].exists():
            raise RuntimeError("知识稿文件不存在，无法归档知识")
        result = organize_document(
            paths["document"],
            self.settings,
            profile=self.db.active_knowledge_profile(),
        )
        _json_write(paths["knowledge_update"], result)
        self.db.save_artifact(job["id"], part["id"], "knowledge_update", paths["knowledge_update"])
        if result.get("topic_path"):
            topic_path = Path(result["topic_path"])
            relative_path = topic_path.relative_to(
                self.settings.knowledge_base_dir / "topics"
            ).as_posix()
            self.db.save_topic_state(
                relative_path,
                job.get("bvid"),
                result["plan"]["action"],
                result["updated_at"],
            )
            self.db.save_artifact(job["id"], part["id"], "topic", topic_path)
        return "completed"

    def _publish_index(self, job_id: str) -> None:
        job = self.db.job_detail(job_id)
        if not job:
            return
        first_paths = self._paths(job, job["parts"][0])
        lines = [
            f"# {job['video_title']}",
            "",
            f"- BV 号：{job['bvid']}",
            f"- 来源：[{job['video_url']}]({job['video_url']})",
            "",
            "## 知识文档",
            "",
        ]
        for part in job["parts"]:
            paths = self._paths(job, part)
            relative = paths["document"].relative_to(first_paths["root"]).as_posix()
            summary = (part.get("summary") or "").replace("\n", " ")[:160]
            lines.append(f"- [{part['title']}]({relative}) — {part['status']} {summary}")
        first_paths["index"].parent.mkdir(parents=True, exist_ok=True)
        first_paths["index"].write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.db.save_artifact(job_id, None, "index", first_paths["index"])

    @staticmethod
    def _update_metadata(paths: dict[str, Path], **values: object) -> None:
        metadata = _json_read(paths["metadata"])
        metadata.update(values)
        _json_write(paths["metadata"], metadata)


class JobWorker:
    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.queue: Queue[str | None] = Queue()
        self.thread: threading.Thread | None = None
        self._queued: set[str] = set()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="job-worker", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        if self.thread and self.thread.is_alive():
            self.queue.put(None)
            self.thread.join(timeout=5)

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            if job_id in self._queued:
                return
            self._queued.add(job_id)
            self.queue.put(job_id)

    def _loop(self) -> None:
        while True:
            job_id = self.queue.get()
            if job_id is None:
                self.queue.task_done()
                return
            try:
                self.pipeline.run(job_id)
            finally:
                with self._lock:
                    self._queued.discard(job_id)
                self.queue.task_done()
