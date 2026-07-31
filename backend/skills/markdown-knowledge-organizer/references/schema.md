# JSON protocols

The host supplies a knowledge Profile with mode `open`, `guided`, or `strict`. Follow its scope and preferred topic paths while producing the same response structures below.

## Routing response

Return one JSON object:

```json
{
  "title": "星座",
  "suggested_path": "文化/占星/星座.md",
  "aliases": ["十二星座"],
  "summary": "关于占星语境下星座体系的主题",
  "candidate_paths": ["文化/占星/星座.md"]
}
```

`candidate_paths` must contain zero to three paths copied exactly from the supplied catalog.

## Final update plan

Return one JSON object and no surrounding Markdown fence:

```json
{
  "action": "create",
  "target_path": "文化/占星/星座.md",
  "title": "星座",
  "aliases": ["十二星座"],
  "summary": "关于占星语境下星座体系的主题",
  "sections": {
    "overview": "本主题的简要定义。",
    "knowledge": ["带有来源时间戳链接的完整知识点。"],
    "disagreements": [],
    "sources": ["[视频标题 02:05–03:00](https://www.bilibili.com/video/BV...?t=125)"]
  },
  "related_paths": []
}
```

Actions:

- `create`: create a distinct topic at a new path.
- `merge`: replace one supplied candidate topic with a complete consolidated version.
- `link`: create a distinct topic and link it to related existing topics.
- `noop`: make no topic change; explain briefly in `summary`.

For `merge`, return the complete retained and new knowledge, disagreements, and sources—not a patch. For `noop`, `sections` may be empty. Never output deletion or move operations.
