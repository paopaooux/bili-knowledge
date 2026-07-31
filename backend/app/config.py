from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]


@dataclass(slots=True)
class Settings:
    data_dir: Path = ROOT_DIR / "data"
    knowledge_base_dir: Path = ROOT_DIR / "knowledge-base"
    knowledge_profile_path: Path | None = None
    cookie_file: Path | None = None
    stt_provider: str = "openai_compatible"
    stt_base_url: str = "https://api.openai.com/v1"
    stt_model: str = "whisper-1"
    stt_api_key: str | None = None
    oss_endpoint: str | None = None
    oss_bucket: str | None = None
    oss_access_key_id: str | None = None
    oss_access_key_secret: str | None = None
    oss_prefix: str = "bili-knowledge-stt"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str | None = None
    audio_chunk_seconds: int = 900
    transcript_chunk_chars: int = 12_000
    request_timeout_seconds: int = 120
    stt_poll_timeout_seconds: int = 7200

    @property
    def database_path(self) -> Path:
        return self.data_dir / "app.sqlite3"

    @property
    def temp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def public_dict(self) -> dict:
        return {
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


def load_settings(config_path: Path | None = None) -> Settings:
    _load_dotenv(ROOT_DIR / "config.env")
    config_file = config_path or ROOT_DIR / "config.json"
    raw: dict = {}
    if config_file.exists():
        raw = json.loads(config_file.read_text(encoding="utf-8"))

    path_fields = {"data_dir", "knowledge_base_dir", "knowledge_profile_path", "cookie_file"}
    defaults = asdict(Settings())
    values = {
        key: raw.get(key, value)
        for key, value in defaults.items()
        if key not in {"stt_api_key", "llm_api_key"}
    }
    env_map = {
        "data_dir": "DATA_DIR",
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
    values["stt_api_key"] = (
        os.getenv("DASHSCOPE_API_KEY")
        if values["stt_provider"].startswith("dashscope_")
        else os.getenv("STT_API_KEY")
    )
    values["llm_api_key"] = os.getenv("LLM_API_KEY")
    values["oss_access_key_id"] = os.getenv("OSS_ACCESS_KEY_ID")
    values["oss_access_key_secret"] = os.getenv("OSS_ACCESS_KEY_SECRET")
    settings = Settings(**values)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    settings.knowledge_base_dir.mkdir(parents=True, exist_ok=True)
    return settings
