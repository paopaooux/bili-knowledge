from pathlib import Path

from app.constants import STAGES
from app.database import Database


def inspection():
    return {
        "bvid": "BV1234567890",
        "url": "https://www.bilibili.com/video/BV1234567890",
        "title": "多 P / 测试",
        "uploader": "tester",
        "parts": [
            {"index": 1, "title": "相同标题", "url": "https://example.test?p=1", "subtitles": []},
            {"index": 2, "title": "相同标题", "url": "https://example.test?p=2", "subtitles": []},
        ],
    }


def test_job_persists_parts_stages_and_artifacts(settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(inspection())
    job_id = db.create_job(video["id"], [part["id"] for part in video["parts"]])
    detail = db.job_detail(job_id)
    assert detail["status"] == "queued"
    assert len(detail["parts"]) == 2
    assert [item["stage"] for item in detail["parts"][0]["stages"]] == STAGES

    db.set_stage(job_id, video["parts"][0]["id"], "parse", "running")
    recovered = db.recover_interrupted()
    assert job_id in recovered  # job itself was still queued
    stage = db.one("SELECT * FROM job_stages WHERE job_id=? AND status='failed'", (job_id,))
    assert "重启" in stage["error"]


def test_migration_is_idempotent(settings):
    db = Database(settings.database_path)
    db.migrate()
    db.migrate()
    assert db.one("SELECT COUNT(*) AS count FROM schema_migrations")["count"] == 6


def test_part_can_persist_multiple_topic_artifacts(settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(inspection())
    part_id = video["parts"][0]["id"]
    job_id = db.create_job(video["id"], [part_id])

    first_id = db.save_artifact(job_id, part_id, "topic", Path("topics/时间管理.md"))
    second_id = db.save_artifact(job_id, part_id, "topic", Path("topics/运动习惯.md"))
    repeated_id = db.save_artifact(job_id, part_id, "topic", Path("topics/时间管理.md"))

    artifacts = db.all(
        "SELECT * FROM artifacts WHERE job_id=? AND part_id=? AND kind='topic' ORDER BY path",
        (job_id, part_id),
    )
    assert len(artifacts) == 2
    assert first_id != second_id
    assert repeated_id == first_id


def test_topic_state_keeps_only_latest_update(settings):
    db = Database(settings.database_path)
    db.migrate()
    db.save_topic_state("个人成长/学习方法.md", "BV1", "create", "2026-01-01T00:00:00+00:00")
    db.save_topic_state("个人成长/学习方法.md", "BV2", "merge", "2026-01-02T00:00:00+00:00")

    rows = db.all("SELECT * FROM knowledge_topics")
    assert len(rows) == 1
    assert rows[0]["source_bvid"] == "BV2"
    assert rows[0]["last_action"] == "merge"


def test_profiles_persist_topics_and_active_selection(settings):
    db = Database(settings.database_path)
    db.migrate()
    first = db.seed_knowledge_profile(
        {
            "name": "开放知识库",
            "mode": "open",
            "scope": "",
            "preferred_topics": [],
            "rules": {"ignore_out_of_scope": False, "merge_similar": True},
        }
    )
    second = db.save_knowledge_profile(
        {
            "name": "个人成长与学习",
            "mode": "guided",
            "scope": "学习知识",
            "preferred_topics": [
                {
                    "name": "学习方法",
                    "path": "个人成长/学习方法.md",
                    "description": "阅读与复盘",
                }
            ],
            "rules": {"ignore_out_of_scope": True, "merge_similar": True},
        }
    )

    assert db.active_knowledge_profile()["id"] == first["id"]
    activated = db.activate_knowledge_profile(second["id"])
    assert activated["is_active"] is True
    assert activated["preferred_topics"][0]["path"] == "个人成长/学习方法.md"
    assert db.delete_knowledge_profile(first["id"]) is True
