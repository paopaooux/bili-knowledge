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

`topics` must contain non-overlapping knowledge topics. Use only as many as the source genuinely
needs; never split knowledge unnecessarily. Return an empty array when
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
          "先明确目标，再选择行动：目标不清晰时列出约束、比较方案，而不是凭感觉推进。\n  - 紧急情况可以先用可逆的小行动试探，避免停在原地。\n  - 比如想换工作的人，先约几次行业交流确认方向，再决定辞职，而不是先辞职再慢慢想。"
        ],
        "disagreements": []
      }
    }
  ]
}
```

`updates` may contain any number of plans and every `target_path` must be unique. Distribute each
source claim to its best-fitting update; never copy the same claim into several topics merely to
fill them. Source titles and timestamp links are optional and their absence is not a reason to skip
an otherwise useful update. Return an empty array only when there is no durable in-scope knowledge.

Actions:

- `create`: create a distinct topic at a new path.
- `merge`: add only the new durable knowledge from this source to one supplied candidate topic.
- `noop`: legacy single-plan no-change action; batched responses should use an empty `updates` array.

For `merge`, return only knowledge and disagreements newly contributed by this source. Do not copy
existing candidate content into the response. The host preserves the existing topic and inserts this increment.
Use `disagreements` only for genuinely incompatible claims or materially different conclusions;
return an empty array when there is only one view or the claims can be reconciled.
Never output deletion or move operations.

Never output Markdown links or “see also” references to other topic files. Topic documents must be
self-contained because cross-topic links are not guaranteed to be navigable in the viewer.

`sections.knowledge` is a semantic hierarchy, not a flat union of claims. Each array item is one
top-level principle, written as a detailed discussion rather than a bare rule: state the point,
then elaborate with reasoning, context, concrete examples, and boundary conditions. When it has
genuinely subordinate claims, encode nested Markdown bullets in the same JSON string using
`\n  - `. Infer parent-child relationships from meaning; do not force fixed categories such as
conditions, rationale, steps, examples, or exceptions, but do keep the source's own concrete
examples and cases as nested illustrations. Prefer 3–8 distinct top-level principles per update,
each with real substance; consolidate equivalent statements and omit only padded repetition.
Tone: practical field-experience notes — direct, vivid, specific, keeping original phrasings;
avoid academic hedging and boilerplate.
