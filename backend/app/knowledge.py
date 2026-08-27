from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import runpy
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from .ai import AIServiceError, chat
from .config import Settings
from .knowledge_profile import (
    KnowledgeProfileError,
    load_knowledge_profile,
    profile_instructions,
    validate_profile_plan,
)
from .prompting import render_prompt

logger = logging.getLogger("uvicorn.error")

SKILL_DIR = Path(__file__).resolve().parents[1] / "skills" / "markdown-knowledge-organizer"
SKILL_PATH = SKILL_DIR / "SKILL.md"
SCHEMA_PATH = SKILL_DIR / "references" / "schema.md"
TEMPLATE_PATH = SKILL_DIR / "assets" / "topic-template.md"
VALIDATOR_PATH = SKILL_DIR / "scripts" / "validate_update.py"
PROMPTS_DIR = SKILL_DIR / "prompts"
REFACTOR_SKILL_PATH = SKILL_DIR.parent / "markdown-topic-refactor" / "SKILL.md"

_validator = runpy.run_path(str(VALIDATOR_PATH))
validate_update_plan = _validator["validate_plan"]
validate_update_batch = _validator["validate_batch"]
validate_topic_path = _validator["validate_topic_path"]

ChatFunction = Callable[..., str]
TRANSCRIPT_HEADING = "## 完整带时间戳转写"


class KnowledgeOrganizerError(RuntimeError):
    pass


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _schema_protocol(heading: str, next_heading: str | None = None) -> str:
    """Return only the protocol needed by one LLM stage to avoid schema confusion."""
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    marker = f"## {heading}"
    start = schema.find(marker)
    if start < 0:
        raise RuntimeError(f"知识整理协议缺少章节：{heading}")
    if next_heading:
        end = schema.find(f"## {next_heading}", start + len(marker))
        if end >= 0:
            return schema[start:end].strip()
    return schema[start:].strip()


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
            temporary = Path(output.name)
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _json_response(value: str, label: str) -> dict:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise KnowledgeOrganizerError(f"{label}没有返回 JSON 对象，输出开头为：{text[:120]}")
    try:
        result = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise KnowledgeOrganizerError(
            f"{label}返回了无效 JSON：{exc}，输出开头为：{text[:120]}"
        ) from exc
    if not isinstance(result, dict):
        raise KnowledgeOrganizerError(f"{label}必须返回 JSON 对象，输出开头为：{text[:120]}")
    return result


def _chat_json(
    messages: list[dict],
    settings: Settings,
    label: str,
    max_tokens: int,
    chat_func: ChatFunction,
    required_array_field: str | None = None,
) -> dict:
    """调用模型并要求返回 JSON；语法或顶层数组结构错误时纠正重试一次。"""
    last_error: KnowledgeOrganizerError | None = None
    for attempt in range(2):
        response = chat_func(messages, settings, max_tokens=max_tokens)
        try:
            result = _json_response(response, label)
            if required_array_field and not isinstance(
                result.get(required_array_field), list
            ):
                raise KnowledgeOrganizerError(
                    f"{label} {required_array_field} 必须是数组"
                )
            return result
        except KnowledgeOrganizerError as exc:
            if not str(exc).startswith(label):
                raise
            last_error = exc
            logger.warning(
                "Knowledge %s returned invalid JSON or schema attempt=%d snippet=%r",
                label,
                attempt + 1,
                response[:120],
            )
            messages = [
                *messages,
                {"role": "assistant", "content": response[:4000]},
                {
                    "role": "user",
                    "content": (
                        "刚才的输出不是有效的 JSON，或者不符合指定的 JSON 结构。"
                        "请重新输出一个完整、合法的 JSON 对象，"
                        + (
                            f'只输出以 "{required_array_field}" 为唯一顶层字段的对象，'
                            f"且 {required_array_field} 必须是数组；"
                            "不要输出其他处理阶段的协议。"
                            if required_array_field
                            else ""
                        )
                        + "不要使用代码围栏、不要省略任何字段、不要输出任何解释文字。"
                    ),
                },
            ]
    assert last_error is not None
    raise last_error


def _load_catalog(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "updated_at": None, "topics": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KnowledgeOrganizerError(f"主题索引损坏：{exc}") from exc
    if not isinstance(value, dict) or not isinstance(value.get("topics"), list):
        raise KnowledgeOrganizerError("主题索引结构无效")
    return value


def _source_note(document: Path) -> str:
    try:
        content = document.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeOrganizerError(f"读取来源知识稿失败：{exc}") from exc
    note = content.split(TRANSCRIPT_HEADING, 1)[0].strip()
    if not note:
        raise KnowledgeOrganizerError("来源知识稿没有可归类内容")
    return note[:24_000]


def _route(
    source: str,
    catalog: dict,
    profile: dict,
    settings: Settings,
    chat_func: ChatFunction,
) -> list[dict]:
    compact_catalog = [
        {
            "path": item.get("path"),
            "title": item.get("title"),
            "aliases": item.get("aliases", []),
            "summary": item.get("summary", ""),
        }
        for item in catalog["topics"]
        if isinstance(item, dict) and item.get("path") and item.get("title")
    ]
    value = _chat_json(
        [
            {
                "role": "system",
                "content": render_prompt(
                    PROMPTS_DIR / "route-system.md",
                    skill=SKILL_PATH.read_text(encoding="utf-8"),
                    profile_instructions=profile_instructions(profile),
                    schema=_schema_protocol(
                        "Multi-topic routing response", "Batched update plan"
                    ),
                ),
            },
            {
                "role": "user",
                "content": render_prompt(
                    PROMPTS_DIR / "route-user.md",
                    catalog_json=json.dumps(compact_catalog, ensure_ascii=False),
                    source=source,
                ),
            },
        ],
        settings,
        "知识路由",
        max_tokens=12000,
        chat_func=chat_func,
        required_array_field="topics",
    )
    raw_topics = value.get("topics")
    if not isinstance(raw_topics, list):
        raise KnowledgeOrganizerError("知识路由 topics 必须是数组")
    logger.info(
        "Knowledge routing response topic_count=%d topics=%s",
        len(raw_topics),
        json.dumps(
            [
                {
                    "title": item.get("title"),
                    "suggested_path": item.get("suggested_path"),
                    "candidate_paths": item.get("candidate_paths"),
                    "focus": str(item.get("focus") or "")[:300],
                }
                for item in raw_topics
                if isinstance(item, dict)
            ],
            ensure_ascii=False,
        ),
    )
    known_paths = {str(item["path"]) for item in compact_catalog}
    routes = []
    for index, topic in enumerate(raw_topics):
        if not isinstance(topic, dict):
            raise KnowledgeOrganizerError(f"知识路由 topics[{index}] 必须是对象")
        try:
            suggested_path = validate_topic_path(
                topic.get("suggested_path"), f"topics[{index}].suggested_path"
            )
        except ValueError as exc:
            raise KnowledgeOrganizerError(f"知识路由路径无效：{exc}") from exc
        candidates = topic.get("candidate_paths") or []
        if not isinstance(candidates, list):
            raise KnowledgeOrganizerError("知识路由 candidate_paths 必须是数组")
        raw_aliases = topic.get("aliases") or []
        if not isinstance(raw_aliases, list):
            raise KnowledgeOrganizerError("知识路由 aliases 必须是数组")
        focus = str(topic.get("focus") or "").strip()
        if not focus:
            raise KnowledgeOrganizerError("知识路由 focus 不能为空")
        known_candidates = [str(item) for item in candidates if item in known_paths]
        if suggested_path in known_paths:
            known_candidates.insert(0, suggested_path)
        routes.append(
            {
                "title": str(topic.get("title") or PurePosixPath(suggested_path).stem).strip()[:100],
                "focus": focus[:1000],
                "suggested_path": suggested_path,
                "aliases": [str(item).strip()[:100] for item in raw_aliases[:10]],
                "summary": str(topic.get("summary") or "").strip()[:500],
                "candidate_paths": list(dict.fromkeys(known_candidates))[:3],
            }
        )
    merged_routes: dict[str, dict] = {}
    for route in routes:
        path = route["suggested_path"]
        if path not in merged_routes:
            merged_routes[path] = route
            continue
        current = merged_routes[path]
        logger.warning(
            "Knowledge routing duplicate path merged path=%s kept_title=%r merged_title=%r",
            path,
            current["title"],
            route["title"],
        )
        current["focus"] = "；".join(
            dict.fromkeys([current["focus"], route["focus"]])
        )[:2000]
        current["aliases"] = list(
            dict.fromkeys([*current["aliases"], route["title"], *route["aliases"]])
        )[:10]
        current["candidate_paths"] = list(
            dict.fromkeys([*current["candidate_paths"], *route["candidate_paths"]])
        )[:3]
        if route["summary"] and route["summary"] not in current["summary"]:
            current["summary"] = "；".join(
                item for item in [current["summary"], route["summary"]] if item
            )[:500]
    return list(merged_routes.values())


def _candidate_documents(topics_root: Path, paths: list[str]) -> tuple[list[dict], dict[str, str]]:
    documents = []
    hashes = {}
    for relative in paths:
        document = topics_root / relative
        if not document.is_file():
            continue
        content = document.read_text(encoding="utf-8")
        documents.append({"path": relative, "content": content[:16_000]})
        hashes[relative] = _sha256(content)
    return documents, hashes


def _deduplicate_batch_knowledge(raw: dict) -> dict:
    """Keep an exact knowledge point in only its first planned topic update."""
    updates = raw.get("updates")
    if not isinstance(updates, list):
        return raw
    seen: set[str] = set()
    normalized = []
    for item in updates:
        if not isinstance(item, dict):
            normalized.append(item)
            continue
        sections = item.get("sections")
        knowledge = sections.get("knowledge") if isinstance(sections, dict) else None
        if not isinstance(knowledge, list):
            normalized.append(item)
            continue
        unique = []
        removed = 0
        for point in knowledge:
            compact = "".join(str(point).split()).casefold()
            if compact and compact in seen:
                removed += 1
                continue
            if compact:
                seen.add(compact)
            unique.append(point)
        if removed:
            logger.warning(
                "Knowledge plan removed duplicate points target=%s removed=%d",
                item.get("target_path"),
                removed,
            )
        if knowledge and not unique:
            logger.warning(
                "Knowledge plan skipped duplicate-only update target=%s",
                item.get("target_path"),
            )
            continue
        normalized.append({**item, "sections": {**sections, "knowledge": unique}})
    return {**raw, "updates": normalized}


def _plan(
    source: str,
    routes: list[dict],
    candidates: list[dict],
    existing_paths: set[str],
    profile: dict,
    settings: Settings,
    chat_func: ChatFunction,
) -> list[dict]:
    raw = _chat_json(
        [
            {
                "role": "system",
                "content": render_prompt(
                    PROMPTS_DIR / "plan-system.md",
                    skill=SKILL_PATH.read_text(encoding="utf-8"),
                    profile_instructions=profile_instructions(profile),
                    schema=_schema_protocol("Batched update plan"),
                ),
            },
            {
                "role": "user",
                "content": render_prompt(
                    PROMPTS_DIR / "plan-user.md",
                    routes_json=json.dumps(routes, ensure_ascii=False),
                    candidates_json=json.dumps(candidates, ensure_ascii=False),
                    source=source,
                ),
            },
        ],
        settings,
        "知识整理",
        max_tokens=12000,
        chat_func=chat_func,
        required_array_field="updates",
    )
    candidate_paths = {
        path for route in routes for path in route["candidate_paths"]
    }
    raw_updates = raw.get("updates") if isinstance(raw, dict) else None
    if isinstance(raw_updates, list):
        normalized_updates = []
        for item in raw_updates:
            if (
                isinstance(item, dict)
                and item.get("action") == "create"
                and item.get("target_path") in existing_paths
                and item.get("target_path") in candidate_paths
            ):
                logger.warning(
                    "Knowledge plan corrected create to merge for existing candidate path=%s",
                    item["target_path"],
                )
                item = {**item, "action": "merge"}
            normalized_updates.append(item)
        raw = {**raw, "updates": normalized_updates}
    raw = _deduplicate_batch_knowledge(raw)
    try:
        plans = validate_update_batch(raw, existing_paths)
    except ValueError as exc:
        raise KnowledgeOrganizerError(f"知识更新计划未通过校验：{exc}") from exc
    suggested_paths = {route["suggested_path"] for route in routes}
    for plan in plans:
        if plan["action"] == "merge" and plan["target_path"] not in candidate_paths:
            raise KnowledgeOrganizerError("模型试图合并未读取的主题")
        if plan["action"] == "create" and plan["target_path"] not in suggested_paths:
            raise KnowledgeOrganizerError("模型试图创建未经路由的主题")
        try:
            validate_profile_plan(profile, plan)
        except KnowledgeProfileError as exc:
            raise KnowledgeOrganizerError(f"知识更新计划不符合 Profile：{exc}") from exc
    return plans


def _bullets(values: list[str], empty: str = "暂无。") -> str:
    return "\n".join(f"- {item}" for item in values) if values else f"- {empty}"


def _without_legacy_sections(content: str) -> str:
    positions = [
        content.find(heading)
        for heading in ("## 相关主题", "## 我的笔记")
        if heading in content
    ]
    return content[: min(positions)].rstrip() if positions else content.rstrip()


TOPIC_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\([^)]*\.md(?:#[^)]*)?\)", re.IGNORECASE)


def _without_topic_links(content: str) -> str:
    return TOPIC_LINK_PATTERN.sub(r"\1", content)


def _render_topic(plan: dict, existing: str | None) -> str:
    disagreements = plan["sections"]["disagreements"]
    replacements = {
        "{{title}}": plan["title"],
        "{{overview}}": plan["sections"]["overview"],
        "{{knowledge}}": _bullets(plan["sections"]["knowledge"]),
        "{{disagreements_section}}": (
            "## 不同观点与争议\n\n" + _bullets(disagreements)
            if disagreements
            else ""
        ),
    }
    result = TEMPLATE_PATH.read_text(encoding="utf-8")
    for marker, value in replacements.items():
        result = result.replace(marker, value)
    return _without_topic_links(result).rstrip() + "\n"


def _append_unique_bullets(content: str, heading: str, values: list[str]) -> str:
    additions = [value for value in values if value and value not in content]
    if not additions:
        return content
    block = _bullets(additions)
    heading_match = re.search(rf"(?m)^{re.escape(heading)}\s*$", content)
    if not heading_match:
        return content.rstrip() + f"\n\n{heading}\n\n{block}\n"
    next_heading = re.search(r"(?m)^##\s+", content[heading_match.end() :])
    insert_at = (
        heading_match.end() + next_heading.start()
        if next_heading
        else len(content.rstrip())
    )
    before = content[:insert_at].rstrip()
    after = content[insert_at:].lstrip("\n")
    result = before + "\n\n" + block + "\n"
    if after:
        result += "\n" + after
    return result


def _merge_topic_increment(existing: str, plan: dict) -> str:
    result = _without_legacy_sections(existing)
    result = _append_unique_bullets(result, "## 核心知识", plan["sections"]["knowledge"])
    result = _append_unique_bullets(
        result,
        "## 不同观点与争议",
        plan["sections"]["disagreements"],
    )
    return _without_topic_links(result).rstrip() + "\n"


def _apply_plan(
    plan: dict,
    catalog: dict,
    topics_root: Path,
    expected_hashes: dict[str, str],
) -> tuple[Path | None, str | None]:
    if plan["action"] == "noop":
        return None, None
    relative = plan["target_path"]
    target = topics_root / relative
    current = target.read_text(encoding="utf-8") if target.exists() else None
    if plan["action"] == "merge":
        if current is None or _sha256(current) != expected_hashes.get(relative):
            raise KnowledgeOrganizerError("主题文档在整理期间发生变化，已停止覆盖")
    elif current is not None:
        raise KnowledgeOrganizerError("新主题路径已被占用，已停止写入")

    rendered = (
        _merge_topic_increment(current, plan)
        if plan["action"] == "merge" and current is not None
        else _render_topic(plan, current)
    )
    try:
        _atomic_write(target, rendered)
        updated_at = datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat()
        topics = [
            item
            for item in catalog["topics"]
            if isinstance(item, dict) and item.get("path") != relative
        ]
        topics.append(
            {
                "path": relative,
                "title": plan["title"],
                "aliases": plan["aliases"],
                "summary": plan["summary"],
                "updated_at": updated_at,
                "content_sha256": _sha256(rendered),
            }
        )
        catalog["topics"] = sorted(topics, key=lambda item: str(item["path"]))
        catalog["updated_at"] = updated_at
    except Exception:
        if current is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, current)
        raise
    return target, current


def _restore_topics(applied: list[tuple[Path, str | None]]) -> None:
    for target, previous in reversed(applied):
        if previous is None:
            target.unlink(missing_ok=True)
        else:
            _atomic_write(target, previous)


def refactor_topic_document(
    path: Path,
    settings: Settings,
    *,
    chat_func: ChatFunction = chat,
) -> str:
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise KnowledgeOrganizerError(f"读取主题文档失败：{exc}") from exc
    if not original.strip():
        raise KnowledgeOrganizerError("主题文档为空，无法重构")
    if len(original) > 60_000:
        raise KnowledgeOrganizerError("主题文档超过 60000 字符，请先手动拆分主题")
    original_hash = _sha256(original)
    knowledge_content = _without_legacy_sections(original)
    response = chat_func(
        [
            {
                "role": "system",
                "content": render_prompt(
                    PROMPTS_DIR / "refactor-system.md",
                    skill=REFACTOR_SKILL_PATH.read_text(encoding="utf-8"),
                ),
            },
            {"role": "user", "content": knowledge_content},
        ],
        settings,
        max_tokens=12000,
    )
    refactored = re.sub(
        r"^```(?:markdown|md)?\s*|\s*```$", "", response.strip(), flags=re.IGNORECASE
    )
    original_title = re.search(r"(?m)^#\s+(.+)$", original)
    result_title = re.search(r"(?m)^#\s+(.+)$", refactored)
    if not original_title or not result_title or result_title.group(1).strip() != original_title.group(1).strip():
        raise KnowledgeOrganizerError("重构结果没有保留原主题标题")
    if not re.search(r"(?m)^\s{2,}-\s+", refactored):
        raise KnowledgeOrganizerError("重构结果没有形成可展开的知识层级")
    result = _without_legacy_sections(refactored) + "\n"
    if not path.is_file() or _sha256(path.read_text(encoding="utf-8")) != original_hash:
        raise KnowledgeOrganizerError("主题文档在重构期间发生变化，已停止覆盖")
    _atomic_write(path, result)
    logger.info(
        "Knowledge topic refactored path=%s before_chars=%d after_chars=%d",
        path,
        len(original),
        len(result),
    )
    return result


def organize_document(
    document: Path,
    settings: Settings,
    *,
    profile: dict | None = None,
    topics_root: Path | None = None,
    chat_func: ChatFunction = chat,
) -> dict:
    topics_root = topics_root or settings.knowledge_base_dir / "topics"
    catalog_path = topics_root / "index.json"
    topics_root.mkdir(parents=True, exist_ok=True)
    source = _source_note(document)
    catalog = _load_catalog(catalog_path)
    if profile is None:
        try:
            profile = load_knowledge_profile(settings.knowledge_profile_path)
        except KnowledgeProfileError as exc:
            raise KnowledgeOrganizerError(str(exc)) from exc
    existing_paths = {
        str(item["path"])
        for item in catalog["topics"]
        if isinstance(item, dict) and item.get("path")
    }
    logger.info(
        "Knowledge organization started source=%s source_chars=%d profile=%s mode=%s existing_topics=%d",
        document,
        len(source),
        profile["name"],
        profile["mode"],
        len(existing_paths),
    )
    try:
        routes = _route(source, catalog, profile, settings, chat_func)
        logger.info(
            "Knowledge routes selected count=%d suggested_paths=%s",
            len(routes),
            [route["suggested_path"] for route in routes],
        )
        candidate_paths = list(
            dict.fromkeys(path for route in routes for path in route["candidate_paths"])
        )
        candidates, expected_hashes = _candidate_documents(topics_root, candidate_paths)
        plans = (
            _plan(source, routes, candidates, existing_paths, profile, settings, chat_func)
            if routes
            else []
        )
        logger.info(
            "Knowledge updates planned count=%d targets=%s",
            len(plans),
            [plan["target_path"] for plan in plans],
        )
        applied: list[tuple[Path, str | None]] = []
        try:
            for plan in plans:
                target, previous = _apply_plan(plan, catalog, topics_root, expected_hashes)
                if target:
                    applied.append((target, previous))
            if applied and settings.auto_refactor_topics:
                for plan, (target, _) in zip(plans, applied, strict=True):
                    if plan["action"] != "merge":
                        continue
                    try:
                        refactor_topic_document(target, settings, chat_func=chat_func)
                    except (KnowledgeOrganizerError, AIServiceError) as exc:
                        logger.warning(
                            "Auto topic refactor skipped path=%s error=%s", target, exc
                        )
                        continue
                    refreshed = target.read_text(encoding="utf-8")
                    for item in catalog["topics"]:
                        if item.get("path") == plan["target_path"]:
                            item["updated_at"] = datetime.fromtimestamp(
                                target.stat().st_mtime, tz=UTC
                            ).isoformat()
                            item["content_sha256"] = _sha256(refreshed)
                            break
            if applied:
                _atomic_write(
                    catalog_path,
                    json.dumps(catalog, ensure_ascii=False, indent=2) + "\n",
                )
        except Exception:
            _restore_topics(applied)
            raise
    except AIServiceError:
        raise
    except KnowledgeOrganizerError:
        raise
    except (OSError, TypeError, KeyError) as exc:
        raise KnowledgeOrganizerError(f"整理 Markdown 知识库失败：{exc}") from exc
    updates = [
        {
            "plan": plan,
            "topic_path": str(target),
            "updated_at": datetime.fromtimestamp(target.stat().st_mtime, tz=UTC).isoformat(),
        }
        for plan, (target, _) in zip(plans, applied, strict=True)
    ]
    return {
        "profile": {"name": profile["name"], "mode": profile["mode"]},
        "routes": routes,
        "plans": plans,
        "updates": updates,
    }
