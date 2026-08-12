#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath


class PlanValidationError(ValueError):
    pass


def _text(value: object, field: str, *, required: bool = True, limit: int = 4000) -> str:
    if not isinstance(value, str):
        raise PlanValidationError(f"{field} 必须是字符串")
    result = value.strip()
    if required and not result:
        raise PlanValidationError(f"{field} 不能为空")
    if len(result) > limit:
        raise PlanValidationError(f"{field} 过长")
    return result


def validate_topic_path(value: object, field: str = "path") -> str:
    result = _text(value, field, limit=240).replace("\\", "/")
    path = PurePosixPath(result)
    parts = path.parts
    if path.is_absolute() or not 1 <= len(parts) <= 4:
        raise PlanValidationError(f"{field} 必须是 1 到 4 层相对路径")
    forbidden = set('<>:"|?*')
    if any(
        part in {"", ".", ".."}
        or part.startswith(".")
        or any(character in forbidden for character in part)
        for part in parts
    ):
        raise PlanValidationError(f"{field} 包含不安全字符")
    if path.suffix.lower() != ".md":
        raise PlanValidationError(f"{field} 必须以 .md 结尾")
    return path.as_posix()


def _text_list(value: object, field: str, *, limit: int, item_limit: int) -> list[str]:
    if not isinstance(value, list) or len(value) > limit:
        raise PlanValidationError(f"{field} 必须是最多 {limit} 项的数组")
    result = []
    for item in value:
        text = _text(item, field, limit=item_limit)
        if text not in result:
            result.append(text)
    return result


def validate_plan(
    value: object,
    existing_paths: set[str] | None = None,
) -> dict:
    if not isinstance(value, dict):
        raise PlanValidationError("更新计划必须是 JSON 对象")
    action = _text(value.get("action"), "action", limit=10).lower()
    if action not in {"create", "merge", "link", "noop"}:
        raise PlanValidationError("action 只能是 create、merge、link 或 noop")

    target_path = ""
    if action != "noop":
        target_path = validate_topic_path(value.get("target_path"), "target_path")
    elif value.get("target_path"):
        target_path = validate_topic_path(value["target_path"], "target_path")

    known = existing_paths or set()
    if action == "merge" and target_path not in known:
        raise PlanValidationError("merge 的 target_path 必须是已有主题")
    if action in {"create", "link"} and target_path in known:
        raise PlanValidationError(f"{action} 的 target_path 必须是新主题")

    title = _text(value.get("title", ""), "title", required=action != "noop", limit=100)
    aliases = _text_list(value.get("aliases", []), "aliases", limit=10, item_limit=100)
    summary = _text(value.get("summary", ""), "summary", required=False, limit=500)
    raw_sections = value.get("sections") or {}
    if not isinstance(raw_sections, dict):
        raise PlanValidationError("sections 必须是对象")
    sections = {
        "overview": _text(
            raw_sections.get("overview", ""),
            "sections.overview",
            required=action != "noop",
            limit=4000,
        ),
        "knowledge": _text_list(
            raw_sections.get("knowledge", []),
            "sections.knowledge",
            limit=80,
            item_limit=4000,
        ),
        "disagreements": _text_list(
            raw_sections.get("disagreements", []),
            "sections.disagreements",
            limit=40,
            item_limit=4000,
        ),
        "sources": _text_list(
            raw_sections.get("sources", []),
            "sections.sources",
            limit=100,
            item_limit=1000,
        ),
    }
    if action != "noop" and not sections["knowledge"]:
        raise PlanValidationError("非 noop 计划至少需要一个核心知识点")
    return {
        "action": action,
        "target_path": target_path,
        "title": title,
        "aliases": aliases,
        "summary": summary,
        "sections": sections,
    }


def validate_batch(value: object, existing_paths: set[str] | None = None) -> list[dict]:
    if not isinstance(value, dict):
        raise PlanValidationError("批量更新计划必须是 JSON 对象")
    raw_updates = value.get("updates")
    if not isinstance(raw_updates, list) or len(raw_updates) > 8:
        raise PlanValidationError("updates 必须是最多 8 项的数组")
    plans = [validate_plan(item, existing_paths) for item in raw_updates]
    if any(plan["action"] == "noop" for plan in plans):
        raise PlanValidationError("批量计划请用空 updates 表示 noop")
    targets = [plan["target_path"] for plan in plans]
    if len(targets) != len(set(targets)):
        raise PlanValidationError("批量计划的 target_path 不能重复")
    seen_knowledge: set[str] = set()
    for plan in plans:
        for knowledge in plan["sections"]["knowledge"]:
            compact = "".join(knowledge.split()).casefold()
            if compact in seen_knowledge:
                raise PlanValidationError("同一知识点不能出现在多个主题更新中")
            seen_knowledge.add(compact)
    return plans


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate a Markdown topic update plan")
    parser.add_argument("plan", help="JSON plan file")
    parser.add_argument("--existing", help="JSON file containing existing topic paths")
    args = parser.parse_args()
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8"))
    existing = set()
    if args.existing:
        existing = set(json.loads(Path(args.existing).read_text(encoding="utf-8")))
    print(json.dumps(validate_plan(plan, existing), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
