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


def test_jobs_are_ordered_by_last_update(settings):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(inspection())
    older = db.create_job(video["id"], [video["parts"][0]["id"]])
    newer = db.create_job(video["id"], [video["parts"][1]["id"]])
    db.execute("UPDATE jobs SET updated_at=? WHERE id=?", ("2026-01-03T00:00:00+00:00", older))
    db.execute("UPDATE jobs SET updated_at=? WHERE id=?", ("2026-01-02T00:00:00+00:00", newer))

    assert [job["id"] for job in db.list_jobs()] == [older, newer]


def test_list_jobs_uses_fixed_number_of_bulk_queries(settings, monkeypatch):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(inspection())
    for part in video["parts"]:
        db.create_job(video["id"], [part["id"]])
    original_all = db.all
    queries = []

    def tracked_all(sql, params=()):
        queries.append(sql)
        return original_all(sql, params)

    monkeypatch.setattr(db, "all", tracked_all)

    jobs = db.list_jobs()

    assert len(jobs) == 2
    assert len(queries) == 4
    assert all(job["parts"][0]["stages"] for job in jobs)


def test_compact_job_list_omits_artifacts_and_uses_three_queries(settings, monkeypatch):
    db = Database(settings.database_path)
    db.migrate()
    video = db.save_inspection(inspection())
    db.create_job(video["id"], [video["parts"][0]["id"]])
    original_all = db.all
    queries = []

    def tracked_all(sql, params=()):
        queries.append(sql)
        return original_all(sql, params)

    monkeypatch.setattr(db, "all", tracked_all)
    jobs = db.list_jobs_compact()

    assert len(queries) == 3
    assert "artifacts" not in jobs[0]
    assert "artifacts" not in jobs[0]["parts"][0]
    assert "summary" not in jobs[0]["parts"][0]


def test_migration_is_idempotent(settings):
    db = Database(settings.database_path)
    db.migrate()
    db.migrate()
    assert db.one("SELECT COUNT(*) AS count FROM schema_migrations")["count"] == 7


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
    profile = db.seed_knowledge_profile(
        {
            "name": "测试库",
            "mode": "open",
            "scope": "",
            "preferred_topics": [],
            "rules": {"ignore_out_of_scope": False, "merge_similar": True},
        }
    )
    db.save_topic_state(
        profile["id"], "个人成长/学习方法.md", "BV1", "create", "2026-01-01T00:00:00+00:00"
    )
    db.save_topic_state(
        profile["id"], "个人成长/学习方法.md", "BV2", "merge", "2026-01-02T00:00:00+00:00"
    )

    rows = db.all("SELECT * FROM knowledge_topics")
    assert len(rows) == 1
    assert rows[0]["source_bvid"] == "BV2"
    assert rows[0]["last_action"] == "merge"


def test_same_source_is_deduplicated_per_profile(settings):
    db = Database(settings.database_path)
    db.migrate()
    first = db.seed_knowledge_profile(
        {"name": "A", "mode": "open", "scope": "", "preferred_topics": [], "rules": {}}
    )
    second = db.save_knowledge_profile(
        {"name": "B", "mode": "open", "scope": "", "preferred_topics": [], "rules": {}}
    )
    video = db.save_inspection(inspection())
    part_ids = [video["parts"][0]["id"]]

    _, first_created = db.create_job_if_absent(video["id"], part_ids, first)
    duplicate_id, duplicate_created = db.create_job_if_absent(video["id"], part_ids, first)
    second_id, second_created = db.create_job_if_absent(video["id"], part_ids, second)

    assert first_created is True
    assert duplicate_created is False
    assert second_created is True
    assert duplicate_id != second_id


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
    assert activated["rules"]["ignore_out_of_scope"] is False
    assert activated["preferred_topics"][0]["path"] == "个人成长/学习方法.md"
    assert db.delete_knowledge_profile(first["id"]) is True
