from fastapi.testclient import TestClient

from app.main import create_app

FAKE_INSPECTION = {
    "bvid": "BV1234567890",
    "url": "https://www.bilibili.com/video/BV1234567890",
    "title": "API 测试",
    "uploader": "tester",
    "parts": [
        {"index": 1, "title": "P1", "url": "https://example.test?p=1", "subtitles": []},
    ],
}


def test_inspect_create_list_and_cancel(monkeypatch, settings):
    monkeypatch.setattr("app.main.inspect_video", lambda url, config: FAKE_INSPECTION)
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        inspected = client.post(
            "/api/videos/inspect", json={"url": "https://www.bilibili.com/video/BV1234567890"}
        )
        assert inspected.status_code == 200
        video = inspected.json()
        created = client.post(
            "/api/jobs", json={"video_id": video["id"], "part_ids": [video["parts"][0]["id"]]}
        )
        assert created.status_code == 201
        job = created.json()
        assert len(job["parts"][0]["stages"]) == 6
        assert client.get("/api/jobs").json()[0]["id"] == job["id"]
        transcript_path = settings.knowledge_base_dir / "test" / "transcript.json"
        transcript_path.parent.mkdir(parents=True)
        transcript_path.write_text(
            '[{"start":0,"end":1,"text":"中间结果","source":"subtitle"}]',
            encoding="utf-8",
        )
        artifact_id = app.state.db.save_artifact(
            job["id"], job["parts"][0]["id"], "transcript", transcript_path
        )
        transcript = client.get(f"/api/transcripts/{artifact_id}")
        assert transcript.status_code == 200
        assert transcript.json()[0]["text"] == "中间结果"
        topic_path = settings.knowledge_base_dir / "topics/test.md"
        topic_path.parent.mkdir(parents=True)
        topic_path.write_text("# 主题知识", encoding="utf-8")
        topic_id = app.state.db.save_artifact(job["id"], job["parts"][0]["id"], "topic", topic_path)
        assert client.get(f"/api/documents/{topic_id}").text == "# 主题知识"
        update_path = settings.knowledge_base_dir / "test" / "knowledge-update.json"
        update_path.parent.mkdir(parents=True, exist_ok=True)
        update_path.write_text('{"plans":[]}', encoding="utf-8")
        update_id = app.state.db.save_artifact(
            job["id"], job["parts"][0]["id"], "knowledge_update", update_path
        )
        assert client.get(f"/api/documents/{update_id}").text == '{"plans":[]}'
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200


def test_settings_never_returns_keys(settings):
    settings.stt_api_key = "secret-stt"
    settings.llm_api_key = "secret-llm"
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        payload = client.get("/api/settings").json()
    assert "secret" not in str(payload)
    assert payload["stt_key_configured"] is True


def test_browse_and_preview_knowledge_files_without_exposing_absolute_paths(settings):
    topic = settings.knowledge_base_dir / "topics" / "学习方法.md"
    topic.parent.mkdir(parents=True)
    topic.write_text("# 学习方法\n\n间隔复习。", encoding="utf-8")
    (settings.knowledge_base_dir / "audio.mp3").write_bytes(b"audio")
    empty_job = settings.knowledge_base_dir / "失败任务" / "parts" / "P01"
    empty_job.mkdir(parents=True)
    outside = settings.knowledge_base_dir.parent / "secret.md"
    outside.write_text("secret", encoding="utf-8")

    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        response = client.get("/api/knowledge/files")
        preview = client.get("/api/knowledge/file", params={"path": "topics/学习方法.md"})
        hidden_artifact = client.get("/api/knowledge/file", params={"path": "audio.mp3"})
        traversal = client.get("/api/knowledge/file", params={"path": "../secret.md"})

    assert response.status_code == 200
    payload = response.json()
    assert str(settings.knowledge_base_dir) not in str(payload)
    assert payload[0]["name"] == "开放知识库"
    assert payload[0]["path"] == "@knowledge-base"
    assert payload[0]["children"][0]["previewable"] is True
    assert "audio.mp3" not in str(payload)
    assert "失败任务" not in str(payload)
    assert not empty_job.exists()
    assert preview.text == "# 学习方法\n\n间隔复习。"
    assert hidden_artifact.status_code == 404
    assert traversal.status_code == 404


def test_delete_failed_job_without_knowledge_output(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    job_id = app.state.db.create_job(video["id"], [video["parts"][0]["id"]])
    app.state.db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
    transcript = settings.knowledge_base_dir / "failed" / "transcript.json"
    transcript.parent.mkdir(parents=True)
    transcript.write_text("[]", encoding="utf-8")
    app.state.db.save_artifact(job_id, video["parts"][0]["id"], "transcript", transcript)
    temp_dir = settings.temp_dir / job_id
    temp_dir.mkdir(parents=True)
    (temp_dir / "audio.mp3").write_bytes(b"audio")

    with TestClient(app) as client:
        response = client.delete(f"/api/jobs/{job_id}")
        assert response.status_code == 204
        assert client.get(f"/api/jobs/{job_id}").status_code == 404

    assert not transcript.exists()
    assert not temp_dir.exists()


def test_delete_cancelled_job_without_knowledge_output(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    job_id = app.state.db.create_job(video["id"], [video["parts"][0]["id"]])
    app.state.db.execute("UPDATE jobs SET status='cancelled' WHERE id=?", (job_id,))

    with TestClient(app) as client:
        response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 204
    assert app.state.db.job_detail(job_id) is None


def test_delete_failed_job_only_removes_selected_job(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    job_ids = [
        app.state.db.create_job(video["id"], [video["parts"][0]["id"]])
        for _ in range(3)
    ]
    for job_id in job_ids:
        app.state.db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))

    with TestClient(app) as client:
        response = client.delete(f"/api/jobs/{job_ids[1]}")
        remaining = {job["id"] for job in client.get("/api/jobs").json()}

    assert response.status_code == 204
    assert remaining == {job_ids[0], job_ids[2]}


def test_delete_failed_job_rejects_existing_document(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    job_id = app.state.db.create_job(video["id"], [video["parts"][0]["id"]])
    app.state.db.execute("UPDATE jobs SET status='failed' WHERE id=?", (job_id,))
    document = settings.knowledge_base_dir / "failed" / "document.md"
    document.parent.mkdir(parents=True)
    document.write_text("# 已生成", encoding="utf-8")
    app.state.db.save_artifact(job_id, video["parts"][0]["id"], "document", document)

    with TestClient(app) as client:
        response = client.delete(f"/api/jobs/{job_id}")

    assert response.status_code == 409
    assert "已经生成知识文档" in response.json()["detail"]
    assert app.state.db.job_detail(job_id) is not None


def test_completed_job_can_retry_only_organize_and_clears_old_topic_artifacts(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    part_id = video["parts"][0]["id"]
    job_id = app.state.db.create_job(video["id"], [part_id])
    app.state.db.execute(
        "UPDATE job_stages SET status='completed' WHERE job_id=?",
        (job_id,),
    )
    app.state.db.execute(
        "UPDATE job_parts SET status='completed' WHERE job_id=?",
        (job_id,),
    )
    app.state.db.execute(
        "UPDATE jobs SET status='completed' WHERE id=?",
        (job_id,),
    )
    document = settings.knowledge_base_dir / "completed" / "document.md"
    topic = settings.knowledge_base_dir / "topics" / "学习方法.md"
    document.parent.mkdir(parents=True)
    topic.parent.mkdir(parents=True)
    document.write_text("# 学习方法", encoding="utf-8")
    topic.write_text("# 学习方法", encoding="utf-8")
    app.state.db.save_artifact(job_id, part_id, "document", document)
    app.state.db.save_artifact(job_id, part_id, "topic", topic)

    with TestClient(app) as client:
        rejected = client.post(
            f"/api/jobs/{job_id}/retry",
            json={"part_id": part_id, "stage": "generate"},
        )
        response = client.post(
            f"/api/jobs/{job_id}/retry",
            json={"part_id": part_id, "stage": "organize"},
        )

    assert rejected.status_code == 409
    assert response.status_code == 200
    detail = app.state.db.job_detail(job_id)
    assert detail["status"] == "queued"
    stages = {item["stage"]: item["status"] for item in detail["parts"][0]["stages"]}
    assert stages["generate"] == "completed"
    assert stages["organize"] == "pending"
    assert stages["publish"] == "pending"
    assert not [item for item in detail["parts"][0]["artifacts"] if item["kind"] == "topic"]
    assert topic.is_file()


def test_regenerate_knowledge_clears_outputs_and_queues_from_generate(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    part_id = video["parts"][0]["id"]
    job_id = app.state.db.create_job(video["id"], [part_id])
    app.state.db.execute("UPDATE job_stages SET status='completed' WHERE job_id=?", (job_id,))
    app.state.db.execute("UPDATE job_parts SET status='completed' WHERE job_id=?", (job_id,))
    app.state.db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job_id,))

    job = app.state.db.job_detail(job_id)
    paths = app.state.worker.pipeline._paths(job, job["parts"][0])
    paths["part"].mkdir(parents=True)
    paths["transcript"].write_text(
        '[{"start":0,"end":1,"text":"保留的转写","source":"subtitle"}]', encoding="utf-8"
    )
    paths["metadata"].write_text('{"title":"P1","video_title":"API 测试"}', encoding="utf-8")
    paths["document"].write_text("# 旧知识正文", encoding="utf-8")
    paths["knowledge_update"].write_text("{}", encoding="utf-8")
    topic = settings.knowledge_base_dir / "topics" / "旧主题.md"
    topic.parent.mkdir(parents=True)
    topic.write_text("# 旧主题", encoding="utf-8")
    for kind, path in (
        ("transcript", paths["transcript"]), ("metadata", paths["metadata"]),
        ("document", paths["document"]), ("knowledge_update", paths["knowledge_update"]),
        ("topic", topic),
    ):
        app.state.db.save_artifact(job_id, part_id, kind, path)
    app.state.db.save_topic_state("旧主题.md", video["bvid"], "create", "2026-01-01")

    with TestClient(app) as client:
        response = client.post("/api/knowledge/regenerate")

    assert response.status_code == 200
    assert response.json() == {"queued_jobs": 1, "queued_parts": 1}
    assert paths["transcript"].is_file()
    assert paths["metadata"].is_file()
    assert not paths["document"].exists()
    assert not paths["knowledge_update"].exists()
    assert not topic.exists()
    assert app.state.db.all("SELECT * FROM knowledge_topics") == []
    detail = app.state.db.job_detail(job_id)
    assert detail["status"] == "queued"
    stages = {stage["stage"]: stage["status"] for stage in detail["parts"][0]["stages"]}
    assert stages == {
        "parse": "completed", "acquire": "completed", "transcribe": "completed",
        "generate": "pending", "organize": "pending", "publish": "pending",
    }
    assert {artifact["kind"] for artifact in detail["parts"][0]["artifacts"]} == {
        "transcript", "metadata"
    }


def test_regenerate_knowledge_rejects_while_queue_is_active(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(FAKE_INSPECTION)
    app.state.db.create_job(video["id"], [video["parts"][0]["id"]])

    with TestClient(app) as client:
        response = client.post("/api/knowledge/regenerate")

    assert response.status_code == 409
    assert "仍有任务" in response.json()["detail"]


def test_create_job_rejects_existing_multipart_video(settings):
    app = create_app(settings, start_worker=False)
    video = app.state.db.save_inspection(
        {
            "bvid": "BV1234567890",
            "url": "https://www.bilibili.com/video/BV1234567890",
            "title": "多 P 视频",
            "parts": [
                {"index": 1, "title": "P1", "url": "https://example.test?p=1"},
                {"index": 2, "title": "P2", "url": "https://example.test?p=2"},
            ],
        }
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/jobs",
            json={"video_id": video["id"], "part_ids": [video["parts"][0]["id"]]},
        )

    assert response.status_code == 422
    assert "仅支持单 P" in response.json()["detail"]


def test_create_job_deduplicates_same_bvid_and_part_across_inspections(settings):
    app = create_app(settings, start_worker=False)
    first_video = app.state.db.save_inspection(FAKE_INSPECTION)
    second_video = app.state.db.save_inspection(FAKE_INSPECTION)

    with TestClient(app) as client:
        created = client.post(
            "/api/jobs",
            json={
                "video_id": first_video["id"],
                "part_ids": [first_video["parts"][0]["id"]],
            },
        )
        duplicate = client.post(
            "/api/jobs",
            json={
                "video_id": second_video["id"],
                "part_ids": [second_video["parts"][0]["id"]],
            },
        )

    assert created.status_code == 201
    assert duplicate.status_code == 409
    assert "相同视频任务已存在" in duplicate.json()["detail"]
    assert app.state.db.one("SELECT COUNT(*) AS count FROM jobs")["count"] == 1


def test_profile_crud_generates_paths_and_activates(settings):
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        initial = client.get("/api/knowledge/profiles").json()
        assert len(initial) == 1
        created = client.post(
            "/api/knowledge/profiles",
            json={
                "name": "学习知识库",
                "mode": "guided",
                "scope": "学习与成长",
                "preferred_topics": [{"name": "学习方法", "description": "阅读与复盘"}],
            },
        )
        assert created.status_code == 201
        profile = created.json()
        assert profile["preferred_topics"][0]["path"] == "学习方法.md"

        activated = client.post(f"/api/knowledge/profiles/{profile['id']}/activate")
        assert activated.status_code == 200
        assert activated.json()["is_active"] is True

        updated = client.put(
            f"/api/knowledge/profiles/{profile['id']}",
            json={
                "name": "学习知识库",
                "mode": "strict",
                "scope": "只保留学习方法",
                "preferred_topics": profile["preferred_topics"],
            },
        )
        assert updated.status_code == 200
        assert updated.json()["mode"] == "strict"


def test_ai_topic_suggestion_reuses_existing_path(monkeypatch, settings):
    app = create_app(settings, start_worker=False)
    profile = app.state.db.active_knowledge_profile()
    app.state.db.save_knowledge_profile(
        {
            "name": profile["name"],
            "mode": "guided",
            "scope": "学习",
            "preferred_topics": [
                {
                    "name": "学习方法",
                    "path": "个人成长/学习方法.md",
                    "description": "阅读与复盘",
                }
            ],
            "rules": {"ignore_out_of_scope": True, "merge_similar": True},
        },
        profile["id"],
    )
    monkeypatch.setattr(
        "app.main.chat",
        lambda *args, **kwargs: (
            '{"action":"use_existing","path":"个人成长/学习方法.md","reason":"语义相同"}'
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/knowledge/topic-suggestion",
            json={"profile_id": profile["id"], "name": "高效学习", "description": "复盘方法"},
        )

    assert response.status_code == 200
    assert response.json()["action"] == "use_existing"
    assert response.json()["path"] == "个人成长/学习方法.md"
