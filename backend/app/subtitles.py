from __future__ import annotations

import html
import json
import re
from typing import Any

TIME_PATTERN = re.compile(
    r"(?P<h>\d{1,2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
    r"\s*-->\s*"
    r"(?P<eh>\d{1,2}):(?P<em>\d{2}):(?P<es>\d{2})[,.](?P<ems>\d{3})"
)
TAG_PATTERN = re.compile(r"<[^>]+>")


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def normalize_segments(items: list[dict], source: str) -> list[dict]:
    result = []
    for item in items:
        text = re.sub(r"\s+", " ", html.unescape(str(item.get("text", "")))).strip()
        if not text:
            continue
        start = max(0.0, float(item.get("start", 0)))
        end = max(start, float(item.get("end", start)))
        if result and result[-1]["text"] == text and start <= result[-1]["end"] + 0.2:
            result[-1]["end"] = max(result[-1]["end"], end)
        else:
            result.append(
                {"start": round(start, 3), "end": round(end, 3), "text": text, "source": source}
            )
    return result


def parse_vtt_srt(content: str, source: str = "subtitle") -> list[dict]:
    lines = content.replace("\ufeff", "").replace("\r", "").split("\n")
    segments: list[dict] = []
    index = 0
    while index < len(lines):
        match = TIME_PATTERN.search(lines[index])
        if not match:
            index += 1
            continue
        values = match.groupdict()
        start = _seconds(values["h"], values["m"], values["s"], values["ms"])
        end = _seconds(values["eh"], values["em"], values["es"], values["ems"])
        index += 1
        text_lines = []
        while index < len(lines) and lines[index].strip():
            text_lines.append(TAG_PATTERN.sub("", lines[index]))
            index += 1
        segments.append({"start": start, "end": end, "text": " ".join(text_lines)})
    return normalize_segments(segments, source)


def parse_bilibili_json(content: str, source: str = "subtitle") -> list[dict]:
    payload = json.loads(content)
    body: list[dict[str, Any]] = payload if isinstance(payload, list) else payload.get("body", [])
    if isinstance(payload, dict) and payload.get("events"):
        items = []
        for event in payload["events"]:
            text = "".join(segment.get("utf8", "") for segment in event.get("segs", []))
            start = float(event.get("tStartMs", 0)) / 1000
            end = start + float(event.get("dDurationMs", 0)) / 1000
            items.append({"start": start, "end": end, "text": text})
        return normalize_segments(items, source)
    return normalize_segments(
        [
            {
                "start": item.get("from", 0),
                "end": item.get("to", 0),
                "text": item.get("content", ""),
            }
            for item in body
        ],
        source,
    )


def parse_subtitle(content: str, extension: str, source: str = "subtitle") -> list[dict]:
    if extension.lower() in {"json", "json3"}:
        return parse_bilibili_json(content, source)
    return parse_vtt_srt(content, source)
