from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class Settings:
    data_dir: Path = ROOT_DIR / "data"
    source_output_dir: Path = ROOT_DIR / "source-output"
    knowledge_base_dir: Path = ROOT_DIR / "knowledge-base"
    knowledge_profile_path: Path | None = None
    cookie_file: Path | None = None
    stt_provider: str = "dashscope_flash"
    stt_base_url: str = ""
    stt_model: str = ""
    stt_api_key: str | None = None
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_prefix: str = "bili-knowledge-stt"
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str | None = None
    llm_enable_thinking: bool | None = None
    audio_chunk_seconds: int = 900
    knowledge_draft_max_tokens: int = 10_000
    request_timeout_seconds: int = 1_200
    stt_poll_timeout_seconds: int = 7200
    auto_refactor_topics: bool = True
    job_worker_concurrency: int = 8

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def public_dict(self) -> dict:
        return {
            "source_output_dir": str(self.source_output_dir),
            "knowledge_base_dir": str(self.knowledge_base_dir),
            "knowledge_profile_path": (
                str(self.knowledge_profile_path) if self.knowledge_profile_path else None
            ),
            "cookie_file": str(self.cookie_file) if self.cookie_file else None,
            "cookie_configured": bool(self.cookie_file),
            "stt_provider": self.stt_provider,
            "stt_base_url": self.stt_base_url,
            "stt_model": self.stt_model,
            "stt_key_configured": bool(self.stt_api_key),
            "oss_endpoint": self.oss_endpoint,
            "oss_bucket": self.oss_bucket,
            "oss_configured": all(
                [
                    self.oss_endpoint,
                    self.oss_bucket,
                    self.oss_access_key_id,
                    self.oss_access_key_secret,
                ]
            ),
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_key_configured": bool(self.llm_api_key),
            "llm_enable_thinking": self.llm_enable_thinking,
        }


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def load_settings() -> Settings:
    _load_dotenv(ROOT_DIR / "config.env")

    path_fields = {
        "data_dir", "source_output_dir", "knowledge_base_dir",
        "knowledge_profile_path", "cookie_file",
    }
    defaults = asdict(Settings())
    values = {
        key: value
        for key, value in defaults.items()
        if key not in {"stt_api_key", "llm_api_key"}
    }
    env_map = {
        "data_dir": "DATA_DIR",
        "source_output_dir": "SOURCE_OUTPUT_DIR",
        "knowledge_base_dir": "KNOWLEDGE_BASE_DIR",
        "knowledge_profile_path": "KNOWLEDGE_PROFILE_PATH",
        "cookie_file": "COOKIE_FILE",
        "stt_provider": "STT_PROVIDER",
        "stt_base_url": "STT_BASE_URL",
        "stt_model": "STT_MODEL",
        "oss_endpoint": "OSS_ENDPOINT",
        "oss_bucket": "OSS_BUCKET",
        "oss_prefix": "OSS_PREFIX",
        "llm_base_url": "LLM_BASE_URL",
        "llm_model": "LLM_MODEL",
        "audio_chunk_seconds": "AUDIO_CHUNK_SECONDS",
        "knowledge_draft_max_tokens": "KNOWLEDGE_DRAFT_MAX_TOKENS",
        "request_timeout_seconds": "REQUEST_TIMEOUT_SECONDS",
        "stt_poll_timeout_seconds": "STT_POLL_TIMEOUT_SECONDS",
        "job_worker_concurrency": "JOB_WORKER_CONCURRENCY",
    }
    for key, env_name in env_map.items():
        if os.getenv(env_name):
            values[key] = os.environ[env_name]
    for key in path_fields:
        if values.get(key):
            path = Path(values[key]).expanduser()
            values[key] = path if path.is_absolute() else (ROOT_DIR / path).resolve()
        elif key in {"cookie_file", "knowledge_profile_path"}:
            values[key] = None
    for key in (
        "audio_chunk_seconds",
        "knowledge_draft_max_tokens",
        "request_timeout_seconds",
        "stt_poll_timeout_seconds",
        "job_worker_concurrency",
    ):
        values[key] = int(values[key])
    values["job_worker_concurrency"] = max(
        1, min(32, values["job_worker_concurrency"])
    )
    raw_refactor = os.getenv("AUTO_REFACTOR_TOPICS")
    if raw_refactor is not None:
        values["auto_refactor_topics"] = raw_refactor.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    raw_llm_thinking = os.getenv("LLM_ENABLE_THINKING")
    if raw_llm_thinking is not None:
        values["llm_enable_thinking"] = raw_llm_thinking.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    dashscope_api_key = os.getenv("DASHSCOPE_API_KEY")
    values["stt_api_key"] = os.getenv("STT_API_KEY") or dashscope_api_key
    if "dashscope.aliyuncs.com" in str(values["llm_base_url"]):
        values["llm_api_key"] = (
            dashscope_api_key or os.getenv("STT_API_KEY") or os.getenv("LLM_API_KEY")
        )
    else:
        values["llm_api_key"] = os.getenv("LLM_API_KEY")
    values["oss_access_key_id"] = os.getenv("OSS_ACCESS_KEY_ID")
    values["oss_access_key_secret"] = os.getenv("OSS_ACCESS_KEY_SECRET")
    settings = Settings(**values)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.source_output_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    return settings
