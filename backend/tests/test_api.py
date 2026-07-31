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
        assert client.post(f"/api/jobs/{job['id']}/cancel").status_code == 200


def test_settings_never_returns_keys(settings):
    settings.stt_api_key = "secret-stt"
    settings.llm_api_key = "secret-llm"
    app = create_app(settings, start_worker=False)
    with TestClient(app) as client:
        payload = client.get("/api/settings").json()
    assert "secret" not in str(payload)
    assert payload["stt_key_configured"] is True


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
