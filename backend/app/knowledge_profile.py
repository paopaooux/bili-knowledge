from __future__ import annotations

import json
from pathlib import Path, PurePosixPath


class KnowledgeProfileError(ValueError):
    pass


def validate_topic_path(value: object, label: str = "path") -> str:
    path = str(value or "").strip().replace("\\", "/")
    parsed = PurePosixPath(path)
    if (
        not path
        or path.startswith("/")
        or parsed.suffix.lower() != ".md"
        or any(part in {"", ".", ".."} for part in parsed.parts)
        or len(parsed.parts) > 4
    ):
        raise KnowledgeProfileError(f"{label} 必须是最多四层的安全 Markdown 相对路径")
    return path


def open_profile() -> dict:
    return {
        "name": "开放知识库",
        "mode": "open",
        "scope": "",
        "preferred_topics": [],
        "rules": {"ignore_out_of_scope": False, "merge_similar": True},
    }


def load_knowledge_profile(path: Path | None) -> dict:
    if path is None or not path.exists():
        return open_profile()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeProfileError(f"读取知识库 Profile 失败：{exc}") from exc
    if not isinstance(raw, dict):
        raise KnowledgeProfileError("知识库 Profile 必须是 JSON 对象")
    return normalize_knowledge_profile(raw)


def normalize_knowledge_profile(raw: dict) -> dict:

    mode = str(raw.get("mode") or "open").strip().lower()
    if mode not in {"open", "guided", "strict"}:
        raise KnowledgeProfileError("知识库 Profile mode 只能是 open、guided 或 strict")
    raw_topics = raw.get("preferred_topics") or []
    if not isinstance(raw_topics, list) or len(raw_topics) > 50:
        raise KnowledgeProfileError("preferred_topics 必须是最多 50 项的数组")
    topics = []
    for index, item in enumerate(raw_topics):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise KnowledgeProfileError(f"preferred_topics[{index}] 缺少 name")
        topic = {
            "name": str(item["name"]).strip()[:100],
            "description": str(item.get("description") or "").strip()[:500],
        }
        if item.get("path"):
            topic["path"] = validate_topic_path(item["path"], f"preferred_topics[{index}].path")
        else:
            raise KnowledgeProfileError("每个推荐主题都必须配置 path")
        topics.append(topic)

    paths = [item["path"] for item in topics]
    if len(paths) != len(set(paths)):
        raise KnowledgeProfileError("推荐主题路径不能重复")

    return {
        "name": str(raw.get("name") or "未命名知识库").strip()[:100],
        "mode": mode,
        "scope": str(raw.get("scope") or "").strip()[:2000],
        "preferred_topics": topics,
        "rules": {
            "ignore_out_of_scope": mode == "strict",
            "merge_similar": True,
        },
    }


def profile_instructions(profile: dict) -> str:
    mode = profile["mode"]
    if mode == "open":
        return "当前为 open 模式：不限定知识领域，根据内容自由归类。"
    behavior = (
        "scope 和推荐主题只是归类优先级，不是内容过滤器；优先按它们归类，"
        "匹配不上时仍应保留其他有价值的知识并自由创建新主题。"
        "即使 scope 中包含“忽略”或“排除”类描述，也不得据此返回 noop；"
        "只有来源确实没有可持久的知识时才返回 noop。"
        if mode == "guided"
        else "只允许使用推荐主题中配置的路径，范围外内容必须 noop。"
    )
    if mode == "strict":
        behavior += " 与 scope 无关的内容必须 noop。"
    if profile["rules"]["merge_similar"]:
        behavior += " 语义相同的知识应精简合并。"
    prompt_profile = {
        key: profile[key] for key in ("name", "mode", "scope", "preferred_topics")
    }
    prompt_profile["rules"] = {
        "ignore_out_of_scope": mode == "strict",
        "merge_similar": True,
    }
    return (
        f"知识库 Profile（{mode}）：\n"
        + json.dumps(prompt_profile, ensure_ascii=False)
        + "\n执行要求："
        + behavior
    )


def validate_profile_plan(profile: dict, plan: dict) -> None:
    if profile["mode"] != "strict" or plan["action"] == "noop":
        return
    allowed = {item["path"] for item in profile["preferred_topics"]}
    if plan["target_path"] not in allowed:
        raise KnowledgeProfileError("strict 模式禁止写入推荐主题之外的路径")


def default_topic_path(profile: dict, name: str, used_paths: set[str] | None = None) -> str:
    safe_name = "".join(
        "-" if character in '/\\:*?"<>|' or ord(character) < 32 else character
        for character in name.strip()
    )
    safe_name = " ".join(safe_name.split()).strip(" .-")[:80] or "新主题"
    topics = profile.get("preferred_topics") or []
    roots = {
        PurePosixPath(item["path"]).parts[0]
        for item in topics
        if item.get("path") and len(PurePosixPath(item["path"]).parts) > 1
    }
    parent = next(iter(roots)) if len(roots) == 1 else ""
    candidate = f"{parent}/{safe_name}.md" if parent else f"{safe_name}.md"
    used = used_paths or {item.get("path") for item in topics}
    suffix = 2
    while candidate in used:
        candidate = f"{parent}/{safe_name}-{suffix}.md" if parent else f"{safe_name}-{suffix}.md"
        suffix += 1
    return validate_topic_path(candidate)
