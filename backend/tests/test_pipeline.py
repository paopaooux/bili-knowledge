import json
from pathlib import Path

import pytest

from app.database import Database
from app.pipeline import Pipeline


def test_rendered_document_only_contains_knowledge_content(settings):
    pipeline = Pipeline(Database(settings.database_path), settings)
    result = pipeline._render_document(
        "建立持续学习的复盘方法",
        "## 检查学习效果\n\n正文内容。",
    )
    assert result == "# 建立持续学习的复盘方法\n\n## 检查学习效果\n\n正文内容。\n"
    assert "title:" not in result
    assert "BV1234567890" not in result


def test_parsed_knowledge_draft_rejects_video_title(settings):
    pipeline = Pipeline(Database(settings.database_path), settings)
    with pytest.raises(RuntimeError, match="照抄了视频标题"):
        pipeline._parse_knowledge_draft(
            '{"title":"原视频标题","body":"正文"}',
            {"title": "原视频标题", "video_title": "原视频标题"},
        )


def test_evidence_ranges_become_clickable(settings):
    pipeline = Pipeline(Database(settings.database_path), settings)
    result = pipeline._link_evidence_timestamps(
        "依据见 [01:05-01:20]，长视频见 [01:02:03–01:03:00]。",
        "https://example.test/video?p=2",
    )
    assert "p=2&t=65" in result
    assert "p=2&t=3723" in result


def test_dashscope_flash_audio_chunks_overlap_below_five_minutes(monkeypatch, settings, tmp_path):
    settings.stt_provider = "dashscope_flash"
    settings.audio_chunk_seconds = 900
    pipeline = Pipeline(Database(settings.database_path), settings)
    audio = tmp_path / "audio.mp3"
    audio.write_bytes(b"audio")
    commands = []

    def fake_run(command, **kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"chunk")

    monkeypatch.setattr("app.pipeline.subprocess.run", fake_run)
    monkeypatch.setattr(
        pipeline,
        "_probe_duration",
        lambda path: 408.0 if path == audio else (240.0 if path.name == "chunk-0000.mp3" else 173.0),
    )

    chunks = pipeline._split_audio(audio, tmp_path / "chunks")

    assert [(start, duration) for _, start, duration in chunks] == [(0.0, 240.0), (235.0, 173.0)]
    assert [command[command.index("-t") + 1] for command in commands] == ["240.000", "173.000"]


def test_transcript_overlap_only_removes_exact_repeated_boundary():
    assert Pipeline._trim_transcript_overlap(
        "前文内容，这句话跨越切片边界",
        "这句话跨越切片边界，后续内容继续。",
    ) == "后续内容继续。"
    assert Pipeline._trim_transcript_overlap("上一段不同表达", "下一段不能误删") == "下一段不能误删"


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
    assert paths["root"].is_relative_to(settings.source_output_dir)
    assert not paths["root"].is_relative_to(settings.knowledge_base_dir)
    paths["transcript"].parent.mkdir(parents=True, exist_ok=True)
    paths["transcript"].write_text(
        json.dumps([{"start": 1, "end": 3, "text": "固定字幕", "source": "subtitle"}]),
        encoding="utf-8",
    )
    final_document = json.dumps(
        {
            "title": "固定字幕中的知识",
            "body": "## 关键内容\n\n正文依据 [00:01-00:03]。",
        },
        ensure_ascii=False,
    )
    responses = iter(["分段摘要；依据 [00:01-00:03]", final_document])
    monkeypatch.setattr("app.pipeline.chat", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(
        "app.pipeline.organize_document",
        lambda *args, **kwargs: {
            "routes": [],
            "plans": [],
            "updates": [],
        },
    )

    pipeline.run(job_id)

    finished = db.job_detail(job_id)
    assert finished["status"] == "completed"
    assert paths["document"].is_file()
    assert paths["knowledge_update"].is_file()
    rendered = paths["document"].read_text(encoding="utf-8")
    assert rendered.startswith("# 固定字幕中的知识\n")
    assert "t=1" in rendered
    assert "完整带时间戳转写" not in rendered
    assert "subtitle_source:" not in rendered
    assert not (settings.temp_dir / job_id).exists()


def test_existing_job_keeps_using_legacy_artifacts_after_storage_split(settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(
        {
            "bvid": "BV1LegacyPath",
            "url": "https://example.test/video",
            "title": "旧任务",
            "parts": [
                {"index": 1, "title": "正片", "url": "https://example.test/video", "subtitles": []}
            ],
        }
    )
    job_id = db.create_job(video["id"], [video["parts"][0]["id"]])
    job = db.job_detail(job_id)
    pipeline = Pipeline(db, settings)
    legacy_document = (
        settings.knowledge_base_dir / "旧任务-BV1LegacyPath" / "parts" / "P01-正片" / "document.md"
    )
    legacy_document.parent.mkdir(parents=True)
    legacy_document.write_text("# 旧知识稿", encoding="utf-8")

    paths = pipeline._paths(job, job["parts"][0])

    assert paths["document"] == legacy_document


def test_organize_persists_every_topic_artifact(monkeypatch, settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(
        {
            "bvid": "BV1MultiTopic",
            "url": "https://example.test/video",
            "title": "多主题视频",
            "parts": [
                {"index": 1, "title": "正片", "url": "https://example.test/video", "subtitles": []}
            ],
        }
    )
    part_id = video["parts"][0]["id"]
    job_id = db.create_job(video["id"], [part_id])
    job = db.job_detail(job_id)
    part = job["parts"][0]
    pipeline = Pipeline(db, settings)
    paths = pipeline._paths(job, part)
    paths["document"].parent.mkdir(parents=True, exist_ok=True)
    paths["document"].write_text("# 综合知识\n", encoding="utf-8")
    first = settings.knowledge_base_dir / "topics/个人成长/时间管理.md"
    second = settings.knowledge_base_dir / "topics/健康生活/运动习惯.md"
    for path in (first, second):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# {path.stem}\n", encoding="utf-8")
    monkeypatch.setattr(
        "app.pipeline.organize_document",
        lambda *args, **kwargs: {
            "routes": [],
            "plans": [],
            "updates": [
                {
                    "plan": {"action": "create", "target_path": "个人成长/时间管理.md"},
                    "topic_path": str(first),
                    "updated_at": "2026-08-04T00:00:00+00:00",
                },
                {
                    "plan": {"action": "create", "target_path": "健康生活/运动习惯.md"},
                    "topic_path": str(second),
                    "updated_at": "2026-08-04T00:00:01+00:00",
                },
            ],
        },
    )

    pipeline._organize(job, part, paths)

    artifacts = db.all(
        "SELECT path FROM artifacts WHERE job_id=? AND part_id=? AND kind='topic' ORDER BY path",
        (job_id, part_id),
    )
    assert [item["path"] for item in artifacts] == sorted([str(first), str(second)])
