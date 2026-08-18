import json

import pytest

from app.knowledge_profile import (
    KnowledgeProfileError,
    load_knowledge_profile,
    profile_instructions,
    validate_profile_plan,
)


def test_missing_profile_uses_open_mode(tmp_path):
    profile = load_knowledge_profile(tmp_path / "missing.json")
    assert profile["mode"] == "open"
    assert profile["preferred_topics"] == []


def test_loads_guided_profile(tmp_path):
    path = tmp_path / "profile.json"
    path.write_text(
        json.dumps(
            {
                "name": "个人成长与学习",
                "mode": "guided",
                "scope": "学习与成长知识",
                "preferred_topics": [
                    {
                        "name": "学习方法",
                        "path": "个人成长/学习方法.md",
                        "description": "阅读与复盘方法",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    profile = load_knowledge_profile(path)
    assert profile["name"] == "个人成长与学习"
    assert profile["preferred_topics"][0]["path"] == "个人成长/学习方法.md"
    assert profile["rules"] == {"ignore_out_of_scope": False, "merge_similar": True}
    instructions = profile_instructions(profile)
    assert "scope 和推荐主题只是归类优先级，不是内容过滤器" in instructions
    assert "即使 scope 中包含“忽略”或“排除”" in instructions


def test_strict_profile_rejects_unconfigured_target():
    profile = {
        "mode": "strict",
        "preferred_topics": [{"path": "个人成长/学习方法.md"}],
    }
    with pytest.raises(KnowledgeProfileError, match="推荐主题之外"):
        validate_profile_plan(
            profile,
            {"action": "create", "target_path": "个人成长/其他.md"},
        )
