import json

from app.database import Database
from app.pipeline import Pipeline


def test_rendered_document_has_metadata_citations_and_transcript(settings):
    pipeline = Pipeline(Database(settings.database_path), settings)
    metadata = {
        "title": "标题",
        "video_title": "视频",
        "bvid": "BV1234567890",
        "part": 1,
        "source_url": "https://www.bilibili.com/video/BV1234567890?p=1",
        "uploader": "UP",
        "published_at": "2025-01-01",
        "duration": 10,
        "language": "zh",
        "subtitle_source": "subtitle",
        "generated_at": "2026-01-01",
        "model": "mock-model",
    }
    result = pipeline._render_document(
        metadata,
        "## 内容摘要\n摘要",
        [{"start": 2, "end": 5, "text": "原始内容", "source": "subtitle"}],
    )
    assert result.startswith("---\n")
    assert 'subtitle_source: "subtitle"' in result
    assert "完整带时间戳转写" in result
    assert "?p=1&t=2" in result
    assert "原始内容" in result


def test_evidence_ranges_become_clickable(settings):
    pipeline = Pipeline(Database(settings.database_path), settings)
    result = pipeline._link_evidence_timestamps(
        "依据见 [01:05-01:20]，长视频见 [01:02:03–01:03:00]。",
        "https://example.test/video?p=2",
    )
    assert "p=2&t=65" in result
    assert "p=2&t=3723" in result


def test_offline_subtitle_pipeline_publishes_documents(monkeypatch, settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(
        {
            "bvid": "BV1AbCdEfGhJ",
            "url": "https://www.bilibili.com/video/BV1AbCdEfGhJ",
            "title": "离线测试 / 视频",
            "uploader": "UP",
            "parts": [
                {
                    "index": 1,
                    "title": "第一部分",
                    "url": "https://www.bilibili.com/video/BV1AbCdEfGhJ?p=1",
                    "subtitles": [],
                }
            ],
        }
    )
    job_id = db.create_job(video["id"], [video["parts"][0]["id"]])
    job = db.job_detail(job_id)
    pipeline = Pipeline(db, settings)
    paths = pipeline._paths(job, job["parts"][0])
    paths["transcript"].parent.mkdir(parents=True, exist_ok=True)
    paths["transcript"].write_text(
        json.dumps([{"start": 1, "end": 3, "text": "固定字幕", "source": "subtitle"}]),
        encoding="utf-8",
    )
    final_document = """## 内容摘要
摘要

## 核心观点与结论
结论

## 主题正文
正文

## 术语与概念
无

## 依据引用
- [00:01-00:03] 固定字幕"""
    responses = iter(["分段摘要；依据 [00:01-00:03]", final_document])
    monkeypatch.setattr("app.pipeline.chat", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(
        "app.pipeline.organize_document",
        lambda *args, **kwargs: {
            "route": {},
            "plan": {"action": "noop"},
            "topic_path": None,
        },
    )

    pipeline.run(job_id)

    finished = db.job_detail(job_id)
    assert finished["status"] == "completed"
    assert paths["document"].is_file()
    assert paths["index"].is_file()
    assert paths["knowledge_update"].is_file()
    assert "t=1" in paths["document"].read_text(encoding="utf-8")
    assert not (settings.temp_dir / job_id).exists()
