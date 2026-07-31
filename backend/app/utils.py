from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(value: str, max_length: int = 80) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = INVALID_FILENAME.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:max_length].rstrip(" .-") or "未命名"


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def duration_text(seconds: float | None) -> str:
    return str(timedelta(seconds=int(seconds or 0)))


def timestamp_url(url: str, seconds: float) -> str:
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({'t': int(max(0, seconds))})}"


def within_directory(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
