---
name: markdown-topic-refactor
description: Refactor an existing Markdown knowledge topic from a flat accumulation into a concise two-to-four-level semantic tree. Use when a topic has become repetitive, reads like an unstructured union of claims, or needs progressive disclosure while preserving its meaning.
---

# Markdown Topic Refactor

Rewrite one existing topic into a readable semantic hierarchy.

## Workflow

1. Treat the supplied topic as the complete evidence boundary; introduce no external facts.
2. Preserve the original level-one title and meaning.
3. Identify duplicate, near-equivalent, and genuinely distinct durable claims.
4. Merge repetition and promote shared abstractions into meaningful parent nodes.
5. Attach subordinate claims below their parent using two to four levels of Markdown bullets.
6. Keep distinct durable knowledge; omit redundant wording and low-value illustrative detail.
7. Output the complete rewritten Markdown without YAML, code fences, JSON, or explanation.
8. Do not output `## 相关主题` or `## 我的笔记`; these legacy sections are removed.

## Structure rules

- Make every parent node express a concept or conclusion that genuinely summarizes its children.
- Infer relationships from meaning rather than forcing buckets such as examples, conditions,
  exceptions, rationale, or steps.
- Prefer a small readable backbone over many flat top-level bullets.
- Preserve uncertainty, qualifications, and genuine disagreements when they affect meaning.
- Do not invent bridging claims merely to make the tree symmetrical.
