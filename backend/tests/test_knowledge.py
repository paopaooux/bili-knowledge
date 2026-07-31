import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.knowledge import KnowledgeOrganizerError, organize_document, validate_update_plan


def _document(path: Path, title: str = "星座视频") -> Path:
    path.write_text(
        f"""---
title: {json.dumps(title, ensure_ascii=False)}
---

# {title}

## 内容摘要

讲解星座与四元素分类。

## 核心观点与结论

- 星座可按四元素分类，依据见 [00:10–00:30](https://example.test/video?t=10)。

## 完整带时间戳转写

- 不应发送给知识整理器的完整转写。
""",
        encoding="utf-8",
    )
    return path


def _create_responses():
    return iter(
        [
            json.dumps(
                {
                    "title": "星座",
                    "suggested_path": "文化/占星/星座.md",
                    "aliases": ["十二星座"],
                    "summary": "占星语境下的星座知识",
                    "candidate_paths": [],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "action": "create",
                    "target_path": "文化/占星/星座.md",
                    "title": "星座",
                    "aliases": ["十二星座"],
                    "summary": "占星语境下的星座知识",
                    "sections": {
                        "overview": "星座是占星学中的分类体系。",
                        "knowledge": [
                            "星座可按四元素分类，[00:10–00:30](https://example.test/video?t=10)。"
                        ],
                        "disagreements": [],
                        "sources": ["[星座视频 00:10–00:30](https://example.test/video?t=10)"],
                    },
                    "related_paths": [],
                },
                ensure_ascii=False,
            ),
        ]
    )


def test_organizer_creates_topic_and_index(settings, tmp_path: Path):
    source = _document(tmp_path / "document.md")
    responses = _create_responses()

    result = organize_document(
        source,
        settings,
        chat_func=lambda *args, **kwargs: next(responses),
    )

    topic = settings.knowledge_base_dir / "topics/文化/占星/星座.md"
    index = settings.knowledge_base_dir / "topics/index.json"
    assert result["plan"]["action"] == "create"
    assert topic.is_file()
    assert "星座可按四元素分类" in topic.read_text(encoding="utf-8")
    assert "不应发送给知识整理器" not in topic.read_text(encoding="utf-8")
    assert json.loads(index.read_text(encoding="utf-8"))["topics"][0]["path"] == (
        "文化/占星/星座.md"
    )


def test_organizer_merges_topic_preserves_manual_notes_and_uses_mtime(settings, tmp_path: Path):
    first_source = _document(tmp_path / "first.md")
    first_responses = _create_responses()
    organize_document(
        first_source,
        settings,
        chat_func=lambda *args, **kwargs: next(first_responses),
    )
    topic = settings.knowledge_base_dir / "topics/文化/占星/星座.md"
    topic.write_text(
        topic.read_text(encoding="utf-8") + "\n用户自己的观察。\n",
        encoding="utf-8",
    )
    second_source = _document(tmp_path / "second.md", "星座补充视频")
    responses = iter(
        [
            json.dumps(
                {
                    "title": "星座",
                    "suggested_path": "文化/占星/星座.md",
                    "aliases": [],
                    "summary": "补充星座知识",
                    "candidate_paths": ["文化/占星/星座.md"],
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "action": "merge",
                    "target_path": "文化/占星/星座.md",
                    "title": "星座",
                    "aliases": ["十二星座"],
                    "summary": "占星语境下的星座知识",
                    "sections": {
                        "overview": "星座是占星学中的分类体系。",
                        "knowledge": ["旧知识。", "新补充知识。"],
                        "disagreements": [],
                        "sources": [
                            "[星座视频](https://example.test/video?t=10)",
                            "[星座补充视频](https://example.test/video?t=20)",
                        ],
                    },
                    "related_paths": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = organize_document(
        second_source,
        settings,
        chat_func=lambda *args, **kwargs: next(responses),
    )

    merged = topic.read_text(encoding="utf-8")
    assert "新补充知识" in merged
    assert "用户自己的观察" in merged
    expected_updated_at = datetime.fromtimestamp(topic.stat().st_mtime, tz=UTC).isoformat()
    assert result["updated_at"] == expected_updated_at
    index = json.loads(
        (settings.knowledge_base_dir / "topics/index.json").read_text(encoding="utf-8")
    )
    assert index["updated_at"] == expected_updated_at
    assert index["topics"][0]["updated_at"] == expected_updated_at
    assert "updated:" not in merged
    assert not (settings.knowledge_base_dir / "history").exists()


def test_validator_rejects_path_traversal():
    with pytest.raises(ValueError, match="相对路径|不安全"):
        validate_update_plan(
            {
                "action": "create",
                "target_path": "../../outside.md",
                "title": "越界",
                "aliases": [],
                "summary": "",
                "sections": {
                    "overview": "越界",
                    "knowledge": ["内容"],
                    "disagreements": [],
                    "sources": ["来源"],
                },
                "related_paths": [],
            },
            set(),
        )


def test_merge_cannot_target_unread_topic(settings, tmp_path: Path):
    source = _document(tmp_path / "document.md")
    topics = settings.knowledge_base_dir / "topics"
    topics.mkdir(parents=True)
    (topics / "已有主题.md").write_text("# 已有主题", encoding="utf-8")
    (topics / "index.json").write_text(
        json.dumps(
            {
                "version": 1,
                "updated_at": None,
                "topics": [{"path": "已有主题.md", "title": "已有主题"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    responses = iter(
        [
            '{"title":"新主题","suggested_path":"新主题.md","candidate_paths":[]}',
            json.dumps(
                {
                    "action": "merge",
                    "target_path": "已有主题.md",
                    "title": "已有主题",
                    "aliases": [],
                    "summary": "",
                    "sections": {
                        "overview": "概述",
                        "knowledge": ["内容"],
                        "disagreements": [],
                        "sources": ["来源"],
                    },
                    "related_paths": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    with pytest.raises(KnowledgeOrganizerError, match="未读取"):
        organize_document(
            source,
            settings,
            chat_func=lambda *args, **kwargs: next(responses),
        )
