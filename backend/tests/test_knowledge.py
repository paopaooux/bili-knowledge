import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.knowledge import (
    KnowledgeOrganizerError,
    organize_document,
    refactor_topic_document,
    validate_update_batch,
    validate_update_plan,
)


def _document(path: Path, title: str = "高效学习视频") -> Path:
    path.write_text(
        f"""---
title: {json.dumps(title, ensure_ascii=False)}
---

# {title}

## 内容摘要

讲解间隔复习与主动回忆。

## 核心观点与结论

- 间隔复习有助于巩固记忆，依据见 [00:10–00:30](https://example.test/video?t=10)。

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
                    "topics": [
                        {
                            "title": "间隔复习",
                            "focus": "间隔复习与主动回忆的学习方法",
                            "suggested_path": "个人成长/学习方法/间隔复习.md",
                            "aliases": ["分散学习"],
                            "summary": "通过合理安排复习间隔巩固记忆",
                            "candidate_paths": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "updates": [
                        {
                            "action": "create",
                            "target_path": "个人成长/学习方法/间隔复习.md",
                            "title": "间隔复习",
                            "aliases": ["分散学习"],
                            "summary": "通过合理安排复习间隔巩固记忆",
                            "sections": {
                                "overview": "间隔复习是在不同时间重新练习所学内容。",
                                "knowledge": [
                                    "间隔复习有助于巩固记忆。"
                                ],
                                "disagreements": [],
                            },
                            "related_paths": [],
                        }
                    ]
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

    topic = settings.knowledge_base_dir / "topics/个人成长/学习方法/间隔复习.md"
    index = settings.knowledge_base_dir / "topics/index.json"
    assert result["plans"][0]["action"] == "create"
    assert topic.is_file()
    content = topic.read_text(encoding="utf-8")
    assert content.startswith("# 间隔复习\n")
    assert "topic_id:" not in content
    assert "aliases:" not in content
    assert "created:" not in content
    assert "间隔复习有助于巩固记忆" in content
    assert "## 来源" not in content
    assert "不应发送给知识整理器" not in content
    assert json.loads(index.read_text(encoding="utf-8"))["topics"][0]["path"] == (
        "个人成长/学习方法/间隔复习.md"
    )


def test_organizer_merges_topic_without_legacy_sections_and_uses_mtime(settings, tmp_path: Path):
    first_source = _document(tmp_path / "first.md")
    first_responses = _create_responses()
    organize_document(
        first_source,
        settings,
        chat_func=lambda *args, **kwargs: next(first_responses),
    )
    topic = settings.knowledge_base_dir / "topics/个人成长/学习方法/间隔复习.md"
    topic.write_text(
        topic.read_text(encoding="utf-8") + "\n用户自己的观察。\n",
        encoding="utf-8",
    )
    second_source = _document(tmp_path / "second.md", "学习方法补充视频")
    responses = iter(
        [
            json.dumps(
                {
                    "topics": [
                        {
                            "title": "间隔复习",
                            "focus": "补充间隔复习知识",
                            "suggested_path": "个人成长/学习方法/间隔复习.md",
                            "aliases": [],
                            "summary": "补充学习方法知识",
                            "candidate_paths": ["个人成长/学习方法/间隔复习.md"],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "updates": [
                        {
                            "action": "merge",
                            "target_path": "个人成长/学习方法/间隔复习.md",
                            "title": "间隔复习",
                            "aliases": ["分散学习"],
                            "summary": "通过合理安排复习间隔巩固记忆",
                            "sections": {
                                "overview": "间隔复习是在不同时间重新练习所学内容。",
                                "knowledge": ["旧知识。", "新补充知识。"],
                                "disagreements": [],
                                "sources": [
                                    "[高效学习视频](https://example.test/video?t=10)",
                                    "[学习方法补充视频](https://example.test/video?t=20)",
                                ],
                            },
                            "related_paths": [],
                        }
                    ]
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
    assert "用户自己的观察" not in merged
    assert "## 我的笔记" not in merged
    assert "## 相关主题" not in merged
    expected_updated_at = datetime.fromtimestamp(topic.stat().st_mtime, tz=UTC).isoformat()
    assert result["updates"][0]["updated_at"] == expected_updated_at
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


def test_batch_ignores_legacy_related_paths():
    plans = validate_update_batch(
        {
            "updates": [
                {
                    "action": "create",
                    "target_path": "游戏/战斗系统.md",
                    "title": "战斗系统",
                    "aliases": [],
                    "summary": "战斗规则",
                    "sections": {
                        "overview": "战斗系统概述。",
                        "knowledge": ["战斗系统知识。"],
                        "disagreements": [],
                        "sources": [],
                    },
                    "related_paths": ["游戏/数值设计.md"],
                },
                {
                    "action": "create",
                    "target_path": "游戏/数值设计.md",
                    "title": "数值设计",
                    "aliases": [],
                    "summary": "数值规则",
                    "sections": {
                        "overview": "数值设计概述。",
                        "knowledge": ["数值设计知识。"],
                        "disagreements": [],
                        "sources": [],
                    },
                    "related_paths": ["游戏/战斗系统.md"],
                },
            ]
        },
        set(),
    )

    assert "related_paths" not in plans[0]
    assert "related_paths" not in plans[1]


def test_router_merges_duplicate_suggested_paths_instead_of_failing(settings, tmp_path: Path):
    source = _document(tmp_path / "document.md")
    responses = iter(
        [
            json.dumps(
                {
                    "topics": [
                        {
                            "title": "吸引力建立",
                            "focus": "建立长期吸引力",
                            "suggested_path": "关系/吸引力.md",
                            "aliases": ["长期吸引"],
                            "summary": "长期关系中的吸引力",
                            "candidate_paths": [],
                        },
                        {
                            "title": "持续吸引",
                            "focus": "维持持续吸引",
                            "suggested_path": "关系/吸引力.md",
                            "aliases": [],
                            "summary": "吸引力的维持",
                            "candidate_paths": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "updates": [
                        {
                            "action": "create",
                            "target_path": "关系/吸引力.md",
                            "title": "吸引力建立",
                            "aliases": ["持续吸引"],
                            "summary": "长期关系中的吸引力",
                            "sections": {
                                "overview": "吸引力概述。",
                                "knowledge": ["建立并维持吸引力。"],
                                "disagreements": [],
                                "sources": [],
                            },
                            "related_paths": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = organize_document(
        source,
        settings,
        chat_func=lambda *args, **kwargs: next(responses),
    )

    assert len(result["routes"]) == 1
    assert result["routes"][0]["suggested_path"] == "关系/吸引力.md"
    assert "建立长期吸引力" in result["routes"][0]["focus"]
    assert "维持持续吸引" in result["routes"][0]["focus"]


def test_topic_renders_hierarchical_knowledge_as_nested_markdown(settings, tmp_path: Path):
    source = _document(tmp_path / "document.md")
    responses = iter(
        [
            json.dumps(
                {
                    "topics": [
                        {
                            "title": "复习策略",
                            "focus": "如何安排复习",
                            "suggested_path": "学习/复习策略.md",
                            "candidate_paths": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "updates": [
                        {
                            "action": "create",
                            "target_path": "学习/复习策略.md",
                            "title": "复习策略",
                            "aliases": [],
                            "summary": "复习安排",
                            "sections": {
                                "overview": "复习应形成层级策略。",
                                "knowledge": [
                                    "按遗忘程度安排复习。\n  - 条件：材料已经初步理解。\n  - 步骤：逐渐拉长复习间隔。"
                                ],
                                "disagreements": [],
                                "sources": [],
                            },
                            "related_paths": [],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    organize_document(source, settings, chat_func=lambda *args, **kwargs: next(responses))

    content = (settings.knowledge_base_dir / "topics/学习/复习策略.md").read_text(
        encoding="utf-8"
    )
    assert "- 按遗忘程度安排复习。\n  - 条件：材料已经初步理解。" in content


def test_refactor_topic_builds_semantic_tree_and_removes_legacy_sections(settings, tmp_path: Path):
    topic = tmp_path / "经验判断.md"
    topic.write_text(
        "# 经验判断\n\n## 核心知识\n\n- 接触人数不等于经验质量。\n- 应区分事实与解释。"
        "\n\n## 我的笔记\n\n用户自己的反思。\n",
        encoding="utf-8",
    )
    response = """# 经验判断

## 核心知识

- 经验质量取决于信息深度与验证过程
  - 接触人数只代表样本数量，不等于理解质量
  - 有效判断需要区分观察事实与主观解释
    - 通过持续交流和反例修正最初判断
"""

    result = refactor_topic_document(
        topic,
        settings,
        chat_func=lambda *args, **kwargs: response,
    )

    assert "  - 接触人数只代表样本数量" in result
    assert "用户自己的反思。" not in result
    assert "## 我的笔记" not in result
    assert "## 相关主题" not in result
    assert topic.read_text(encoding="utf-8") == result


def test_topic_only_renders_disagreements_when_they_exist(settings, tmp_path: Path):
    base = {
        "action": "create",
        "target_path": "判断/分歧.md",
        "title": "判断分歧",
        "aliases": [],
        "summary": "判断中的分歧",
        "sections": {
            "overview": "不同观点可能依赖不同前提。",
            "knowledge": ["先识别双方前提。"],
            "disagreements": ["观点甲强调样本数量，观点乙强调信息深度。"],
            "sources": [],
        },
    }
    source = _document(tmp_path / "document.md")
    responses = iter([
        json.dumps({"topics": [{
            "title": "判断分歧", "focus": "不同判断标准",
            "suggested_path": "判断/分歧.md", "candidate_paths": [],
        }]}, ensure_ascii=False),
        json.dumps({"updates": [base]}, ensure_ascii=False),
    ])

    organize_document(source, settings, chat_func=lambda *args, **kwargs: next(responses))

    content = (settings.knowledge_base_dir / "topics/判断/分歧.md").read_text(encoding="utf-8")
    assert "## 不同观点与争议" in content
    assert "观点甲强调样本数量" in content


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
            '{"topics":[{"title":"新主题","focus":"新知识","suggested_path":"新主题.md","candidate_paths":[]}]}',
            json.dumps(
                {
                    "updates": [
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
                        }
                    ]
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


def test_one_source_is_split_into_distinct_topic_files(settings, tmp_path: Path):
    source = _document(tmp_path / "document.md", "个人成长综合知识")
    responses = iter(
        [
            json.dumps(
                {
                    "topics": [
                        {
                            "title": "时间管理",
                            "focus": "规划重点任务与专注时段的方法",
                            "suggested_path": "个人成长/时间管理.md",
                            "aliases": [],
                            "summary": "合理规划时间与任务的方法",
                            "candidate_paths": [],
                        },
                        {
                            "title": "运动习惯",
                            "focus": "循序渐进建立日常运动习惯的方法",
                            "suggested_path": "健康生活/运动习惯.md",
                            "aliases": ["日常锻炼"],
                            "summary": "建立可持续运动习惯的方法",
                            "candidate_paths": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            json.dumps(
                {
                    "updates": [
                        {
                            "action": "create",
                            "target_path": "个人成长/时间管理.md",
                            "title": "时间管理",
                            "aliases": [],
                            "summary": "合理规划时间与任务的方法",
                            "sections": {
                                "overview": "通过确定重点任务提升时间利用效率。",
                                "knowledge": ["每天先安排最重要的专注任务。"],
                                "disagreements": [],
                                "sources": ["[个人成长综合知识](https://example.test/video?t=10)"],
                            },
                            "related_paths": [],
                        },
                        {
                            "action": "create",
                            "target_path": "健康生活/运动习惯.md",
                            "title": "运动习惯",
                            "aliases": ["日常锻炼"],
                            "summary": "建立可持续运动习惯的方法",
                            "sections": {
                                "overview": "循序渐进更容易长期坚持运动。",
                                "knowledge": ["从短时低强度锻炼开始建立运动习惯。"],
                                "disagreements": [],
                                "sources": ["[个人成长综合知识](https://example.test/video?t=30)"],
                            },
                            "related_paths": [],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = organize_document(source, settings, chat_func=lambda *args, **kwargs: next(responses))

    planning_topic = settings.knowledge_base_dir / "topics/个人成长/时间管理.md"
    exercise_topic = settings.knowledge_base_dir / "topics/健康生活/运动习惯.md"
    assert len(result["updates"]) == 2
    assert planning_topic.is_file() and exercise_topic.is_file()
    assert "最重要的专注任务" in planning_topic.read_text(encoding="utf-8")
    assert "低强度锻炼" not in planning_topic.read_text(encoding="utf-8")
    assert "低强度锻炼" in exercise_topic.read_text(encoding="utf-8")
    assert "最重要的专注任务" not in exercise_topic.read_text(encoding="utf-8")
    catalog_paths = {
        item["path"]
        for item in json.loads(
            (settings.knowledge_base_dir / "topics/index.json").read_text(encoding="utf-8")
        )["topics"]
    }
    assert catalog_paths == {"个人成长/时间管理.md", "健康生活/运动习惯.md"}
