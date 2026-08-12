# JSON protocols

The host supplies a knowledge Profile with mode `open`, `guided`, or `strict`. Follow its scope and preferred topic paths while producing the same response structures below.

## Multi-topic routing response

Return one JSON object:

```json
{
  "topics": [
    {
      "title": "星座",
      "focus": "来源中关于星座分类与社交谈资的知识",
      "suggested_path": "文化/占星/星座.md",
      "aliases": ["十二星座"],
      "summary": "关于占星语境下星座体系的主题",
      "candidate_paths": ["文化/占星/星座.md"]
    }
  ]
}
```

`topics` must contain zero to eight non-overlapping knowledge topics. Return an empty array when
the source contains no durable in-scope knowledge. Each `candidate_paths` must contain zero to
three paths copied exactly from the supplied catalog. `focus` states which source knowledge belongs
to that topic so the final planner does not duplicate the whole source into every update.

## Batched update plan

Return one JSON object and no surrounding Markdown fence:

```json
{
  "updates": [
    {
      "action": "create",
      "target_path": "文化/占星/星座.md",
      "title": "星座",
      "aliases": ["十二星座"],
      "summary": "关于占星语境下星座体系的主题",
      "sections": {
        "overview": "本主题的简要定义。",
        "knowledge": [
          "先明确目标，再选择行动。\n  - 适用条件：目标尚不清晰时。\n  - 操作步骤：列出约束，再比较方案。\n  - 例外：紧急情况可先采取可逆行动。"
        ],
        "disagreements": []
      }
    }
  ]
}
```

`updates` may contain zero to eight plans and every `target_path` must be unique. Distribute each
source claim to its best-fitting update; never copy the same claim into several topics merely to
fill them. Source titles and timestamp links are optional and their absence is not a reason to skip
an otherwise useful update. Return an empty array only when there is no durable in-scope knowledge.

Actions:

- `create`: create a distinct topic at a new path.
- `merge`: replace one supplied candidate topic with a complete consolidated version.
- `link`: create a distinct topic and link it to related existing topics.
- `noop`: legacy single-plan no-change action; batched responses should use an empty `updates` array.

For `merge`, return the complete retained and new knowledge, disagreements, and sources—not a patch.
Use `disagreements` only for genuinely incompatible claims or materially different conclusions;
return an empty array when there is only one view or the claims can be reconciled.
Never output deletion or move operations.

`sections.knowledge` is a semantic hierarchy, not a flat union of claims. Each array item is one
top-level principle. When it has genuinely subordinate claims, encode nested Markdown bullets in
the same JSON string using `\n  - `. Infer parent-child relationships from meaning; do not force
fixed categories such as conditions, rationale, steps, examples, or exceptions, and omit low-value
detail. Prefer 3–8 distinct top-level principles and consolidate equivalent statements.
