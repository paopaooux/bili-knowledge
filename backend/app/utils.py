from __future__ import annotations

import re
import unicodedata
from datetime import timedelta
from pathlib import Path

INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_filename(value: str, max_length: int = 80) -> str:
    value = unicodedata.normalize("NFKC", value).strip()
    value = INVALID_FILENAME.sub("-", value)
    value = re.sub(r"\s+", " ", value).strip(" .-")
    return value[:max_length].rstrip(" .-") or "未命名"


def duration_text(seconds: float | None) -> str:
    return str(timedelta(seconds=int(seconds or 0)))


def within_directory(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False
