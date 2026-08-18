---
name: markdown-topic-refactor
description: Refactor an existing Markdown knowledge topic from a flat accumulation into a concise two-to-four-level semantic tree. Use when a topic has become repetitive, reads like an unstructured union of claims, or needs progressive disclosure while preserving its meaning.
---

# Markdown Topic Refactor

Rewrite one existing topic into a readable semantic hierarchy that reads like a practical
experience playbook rather than a pile of parallel claims.

## Workflow

1. Treat the supplied topic as the complete evidence boundary; introduce no external facts.
2. Preserve the original level-one title and meaning.
3. Write a short opening summary (one to three sentences, no heading) right after the title
   telling readers what this topic covers and when to use it.
4. Identify duplicate, near-equivalent, and genuinely distinct durable claims.
5. When several bullets say the same thing in different words, merge them into ONE detailed
   discussion that combines their examples, conditions, and phrasings — never leave parallel
   restatements side by side.
6. Promote shared abstractions into meaningful parent nodes.
7. Attach subordinate claims below their parent using two to four levels of Markdown bullets.
8. Keep distinct durable knowledge, including the concrete examples and cases already present in
   the topic as illustrations; omit only redundant wording and padded repetition.
9. If the topic contains genuinely conflicting viewpoints that affect meaning, keep them together
   in a short final section titled `## 不同观点与争议`; compatible claims belong in the main tree.
10. Output the complete rewritten Markdown without YAML, code fences, JSON, or explanation.
11. Do not output `## 相关主题` or `## 我的笔记`; these legacy sections are removed.

## Structure rules

- Make every parent node express a concept or conclusion that genuinely summarizes its children.
- Infer relationships from meaning rather than forcing buckets such as examples, conditions,
  exceptions, rationale, or steps; keep the topic's own examples as nested illustrations.
- Prefer a small readable backbone over many flat top-level bullets.
- Write like a practical experience playbook rather than an academic paper or compliance
  checklist: state the point, then elaborate with reasoning, context, boundary, and a concrete
  example when one exists; keep the source's original phrasings and vivid details.
- Merging similar claims should produce a fuller, more detailed discussion — combine the various
  examples and situations — not a compressed one-liner.
- Preserve uncertainty, qualifications, and genuine disagreements when they affect meaning.
- Do not invent bridging claims merely to make the tree symmetrical.
