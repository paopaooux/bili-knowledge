from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import yt_dlp

from .config import Settings

BVID_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}", re.IGNORECASE)
SHORT_LINK_HOSTS = {"b23.tv", "www.b23.tv"}


class VideoInspectionError(RuntimeError):
    pass


def _part_url(base_url: str, index: int) -> str:
    parsed = urlparse(base_url)
    query = parse_qs(parsed.query)
    query["p"] = [str(index)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def _subtitle_items(info: dict) -> list[dict]:
    result = []
    groups = [
        ("manual", info.get("subtitles") or {}),
        ("automatic", info.get("automatic_captions") or {}),
    ]
    for kind, languages in groups:
        for language, choices in languages.items():
            for choice in choices or []:
                if choice.get("url"):
                    result.append(
                        {
                            "language": language,
                            "kind": kind,
                            "url": choice["url"],
                            "extension": choice.get("ext", "vtt"),
                        }
                    )
    return result


def _cover_url(info: dict) -> str | None:
    candidates = [info.get("thumbnail")]
    candidates.extend(item.get("url") for item in reversed(info.get("thumbnails") or []) if item)
    for candidate in candidates:
        if not candidate:
            continue
        url = str(candidate)
        if url.startswith("//"):
            return "https:" + url
        if url.startswith("http://"):
            return "https://" + url.removeprefix("http://")
        return url
    return None


def _resolved_bvid(info: dict, entries: list[dict]) -> str | None:
    candidates = [
        info.get("id"),
        info.get("webpage_url"),
        info.get("original_url"),
        *(entry.get("id") for entry in entries if entry),
        *(entry.get("webpage_url") for entry in entries if entry),
    ]
    for candidate in candidates:
        match = BVID_PATTERN.search(str(candidate or ""))
        if match:
            return "BV" + match.group(0)[2:]
    return None


def inspect_video(url: str, settings: Settings) -> dict:
    match = BVID_PATTERN.search(url)
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    if not match and hostname not in SHORT_LINK_HOSTS:
        raise VideoInspectionError("仅支持含 BV 号的 Bilibili 视频链接或 b23.tv 官方短链")
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "ignoreconfig": True,
    }
    if settings.cookie_file:
        if not settings.cookie_file.is_file():
            raise VideoInspectionError(f"Cookie 文件不存在：{settings.cookie_file}")
        options["cookiefile"] = str(settings.cookie_file)
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except Exception as exc:
        message = str(exc).replace("ERROR: ", "")
        raise VideoInspectionError(f"视频解析失败：{message}") from exc
    if not info:
        raise VideoInspectionError("视频解析没有返回信息")

    entries = list(info.get("entries") or [])
    # BV 编码主体大小写敏感；只规范化固定前缀。短链必须在解析后的
    # Bilibili 页面信息中得到 BV 号，不能信任任意重定向目标。
    bvid = "BV" + match.group(0)[2:] if match else _resolved_bvid(info, entries)
    if not bvid:
        raise VideoInspectionError("b23.tv 短链没有解析到有效的 Bilibili BV 视频")
    canonical_url = f"https://www.bilibili.com/video/{bvid}"
    if len(entries) > 1:
        raise VideoInspectionError("当前版本暂不支持分 P 视频，请使用单 P 视频链接")
    if not entries:
        entries = [info]
    parts = []
    for position, entry in enumerate(entries, 1):
        if not entry:
            continue
        part_index = int(entry.get("playlist_index") or entry.get("page") or position)
        parts.append(
            {
                "index": part_index,
                "cid": str(entry.get("cid") or entry.get("id") or ""),
                "title": entry.get("title") or entry.get("part") or f"P{part_index}",
                "url": _part_url(canonical_url, part_index),
                "duration": entry.get("duration") or info.get("duration"),
                "subtitles": _subtitle_items(entry),
                "raw": {"webpage_url": entry.get("webpage_url"), "id": entry.get("id")},
            }
        )
    upload_date = info.get("upload_date")
    published_at = None
    if upload_date:
        published_at = (
            f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
            if len(upload_date) == 8 and upload_date.isdigit()
            else upload_date
        )
    return {
        "bvid": bvid,
        "url": canonical_url,
        "title": info.get("title") or bvid,
        "uploader": info.get("uploader") or info.get("channel"),
        "cover_url": _cover_url(info),
        "published_at": published_at,
        "duration": info.get("duration"),
        "parts": parts,
        "raw": {"extractor": info.get("extractor"), "id": info.get("id")},
    }
