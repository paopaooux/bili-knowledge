from pathlib import Path

import httpx

from app import ai
from app.config import Settings


def test_chat_uses_streaming_response(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"流式"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"结果"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    result = ai.chat([{"role": "user", "content": "测试"}], settings, max_tokens=99)

    assert result == "流式结果"
    assert requests[0].read()
    assert b'"stream":true' in requests[0].content
    assert b'"max_tokens":99' in requests[0].content


def test_chat_retries_with_double_budget_when_output_truncated(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"choices":[{"delta":{"content":"半截"}}]}\n\n'
                    'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'
                    "data: [DONE]\n\n"
                ),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"完整结果"}}]}\n\n'
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    result = ai.chat([{"role": "user", "content": "测试"}], settings, max_tokens=100)

    assert result == "完整结果"
    assert len(requests) == 2
    assert b'"max_tokens":100' in requests[0].content
    assert b'"max_tokens":200' in requests[1].content


def test_chat_retries_twice_after_502_gateway_errors(monkeypatch):
    requests = []
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) <= 2:
            return httpx.Response(502, text="temporary gateway failure")
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"重试成功"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: sleeps.append(seconds))
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    assert ai.chat([{"role": "user", "content": "测试"}], settings) == "重试成功"
    assert len(requests) == 3
    assert sleeps == [1, 2]


def test_chat_retries_503_reported_inside_stream(monkeypatch):
    requests = []
    sleeps = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                text=(
                    'data: {"error":{"message":"Streaming response failed: [503] '
                    'Decode retraction is not resumable. Please retry the request."}}\n\n'
                ),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"choices":[{"delta":{"content":"重试成功"}}]}\n\n',
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: sleeps.append(seconds))
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    assert ai.chat([{"role": "user", "content": "测试"}], settings) == "重试成功"
    assert len(requests) == 2
    assert sleeps == [1]


def test_chat_can_disable_model_thinking(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"choices":[{"delta":{"content":"正文"}}]}\n\n',
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://llm.test/v1",
        llm_model="test-model",
        llm_enable_thinking=False,
    )

    assert ai.chat([{"role": "user", "content": "测试"}], settings) == "正文"
    assert b'"enable_thinking":false' in requests[0].read()


def test_chat_does_not_retry_non_transient_http_errors(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(401, text="invalid key")

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="bad-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    try:
        ai.chat([{"role": "user", "content": "测试"}], settings)
    except ai.AIServiceError as exc:
        assert "401 Unauthorized" in str(exc)
    else:
        raise AssertionError("expected AIServiceError")
    assert len(requests) == 1


def test_qwen_omni_chat_uses_audio_and_usage_options(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"audio":{"transcript":"你好"}}}]}\n\n'
                'data: {"usage":{"completion_tokens":2}}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key",
        llm_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        llm_model="qwen3.5-omni-plus",
    )

    assert ai.chat([{"role": "user", "content": "测试"}], settings) == "你好"
    payload = requests[0].read().decode()
    assert '"model":"qwen3.5-omni-plus"' in payload
    assert '"stream_options":{"include_usage":true}' in payload
    assert '"modalities":["text","audio"]' in payload
    assert '"audio":{"voice":"Ethan","format":"wav"}' in payload


def test_chat_ignores_stream_events_without_choices(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=(
                'data: {"choices":[{"delta":{"content":"正文"}}]}\n\n'
                'data: {"usage":{"completion_tokens":2}}\n\n'
                'data: {"type":"ping"}\n\n'
                "data: [DONE]\n\n"
            ),
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    assert ai.chat([{"role": "user", "content": "测试"}], settings) == "正文"


def test_chat_surfaces_stream_error_message(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text='data: {"error":{"code":"upstream_error","message":"上游暂时不可用"}}\n\n',
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        llm_api_key="test-key", llm_base_url="https://llm.test/v1", llm_model="test-model"
    )

    try:
        ai.chat([{"role": "user", "content": "测试"}], settings)
    except ai.AIServiceError as exc:
        assert str(exc) == "知识稿模型返回错误：上游暂时不可用"
    else:
        raise AssertionError("expected AIServiceError")


def test_qwen_callback_builds_timestamped_segments():
    callback = ai._QwenASRCallback()
    callback.on_event({"type": "session.created"})
    callback.on_event(
        {"type": "input_audio_buffer.speech_started", "item_id": "item-1", "audio_start_ms": 120}
    )
    callback.on_event(
        {"type": "input_audio_buffer.speech_stopped", "item_id": "item-1", "audio_end_ms": 2480}
    )
    callback.on_event(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "item_id": "item-1",
            "transcript": "这是测试",
            "language": "zh",
        }
    )

    assert callback.session_created.is_set()
    assert callback.language == "zh"
    assert callback.segments == [{"start": 0.12, "end": 2.48, "text": "这是测试"}]


def test_qwen_realtime_adapter_streams_pcm_and_returns_payload(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "chunk.mp3"
    audio_path.write_bytes(b"input")
    pcm_path = tmp_path / "chunk.pcm"
    pcm_path.write_bytes(b"\0" * 6400)
    sent_frames = []

    class FakeConversation:
        def __init__(self, callback):
            self.callback = callback

        def connect(self):
            self.callback.on_event({"type": "session.created"})

        def update_session(self, **kwargs):
            assert kwargs["transcription_params"].sample_rate == 16000

        def append_audio(self, value):
            sent_frames.append(value)

        def end_session(self, timeout):
            self.callback.on_event(
                {
                    "type": "input_audio_buffer.speech_started",
                    "item_id": "item-1",
                    "audio_start_ms": 0,
                }
            )
            self.callback.on_event(
                {
                    "type": "input_audio_buffer.speech_stopped",
                    "item_id": "item-1",
                    "audio_end_ms": 200,
                }
            )
            self.callback.on_event(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "item_id": "item-1",
                    "transcript": "流式结果",
                    "language": "zh",
                }
            )

        def close(self):
            pass

    monkeypatch.setattr(ai, "_pcm_from_audio", lambda path: pcm_path)
    monkeypatch.setattr(
        ai, "_qwen_conversation", lambda settings, callback: FakeConversation(callback)
    )
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: None)
    settings = Settings(
        data_dir=tmp_path / "data",
        knowledge_base_dir=tmp_path / "knowledge",
        stt_provider="dashscope_realtime",
        stt_base_url="wss://example.test/realtime",
        stt_model="qwen3-asr-flash-realtime",
        stt_api_key="test-key",
    )

    payload = ai.transcribe_audio(audio_path, settings)

    assert payload["text"] == "流式结果"
    assert payload["segments"][0]["end"] == 0.2
    assert len(sent_frames) == 2
    assert not pcm_path.exists()


def test_qwen_flash_adapter_uses_local_file(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "chunk.mp3"
    audio_path.write_bytes(b"input")
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return {
            "status_code": 200,
            "output": {"choices": [{"message": {"content": [{"text": "本地文件转写成功"}]}}]},
        }

    monkeypatch.setattr(ai.dashscope.MultiModalConversation, "call", fake_call)
    settings = Settings(
        stt_provider="dashscope_flash",
        stt_base_url="https://dashscope.aliyuncs.com/api/v1",
        stt_model="qwen3-asr-flash",
        stt_api_key="test-key",
    )

    result = ai.transcribe_audio(audio_path, settings)

    assert result["text"] == "本地文件转写成功"
    assert result["segments"] == []
    assert captured["model"] == "qwen3-asr-flash"
    assert captured["messages"][1]["content"][0]["audio"] == audio_path.resolve().as_uri()
    assert captured["asr_options"] == {"enable_lid": True, "enable_itn": False}


def test_qwen_omni_transcription_uses_instruction_without_asr_options(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "chunk.mp3"
    audio_path.write_bytes(b"input")
    captured = {}

    def fake_call(**kwargs):
        captured.update(kwargs)
        return {
            "status_code": 200,
            "output": {"choices": [{"message": {"content": [{"text": "Omni 转写"}]}}]},
        }

    monkeypatch.setattr(ai.dashscope.MultiModalConversation, "call", fake_call)
    settings = Settings(
        stt_api_key="test-key",
        stt_base_url="https://dashscope.aliyuncs.com/api/v1",
        stt_model="qwen3.5-omni-plus",
    )

    result = ai.transcribe_audio(audio_path, settings)

    assert result["text"] == "Omni 转写"
    assert captured["model"] == "qwen3.5-omni-plus"
    assert "asr_options" not in captured
    assert "只输出转写文本" in captured["messages"][0]["content"][0]["text"]


def test_stt_configuration_message_uses_current_model():
    settings = Settings(
        stt_api_key="test-key",
        stt_base_url="https://dashscope.aliyuncs.com/api/v1",
        stt_model="qwen3.5-omni-plus",
    )

    result = ai.test_service("stt", settings)

    assert result["message"] == "千问 qwen3.5-omni-plus 配置完整（未发起付费转写）"


def test_model_operation_rejects_missing_env_configuration(tmp_path: Path):
    settings = Settings(stt_api_key="test-key", llm_api_key="test-key")

    try:
        ai.transcribe_audio(tmp_path / "audio.mp3", settings)
    except ai.AIServiceError as exc:
        assert str(exc) == "尚未配置 STT_BASE_URL, STT_MODEL"
    else:
        raise AssertionError("expected AIServiceError")

    try:
        ai.chat([{"role": "user", "content": "测试"}], settings)
    except ai.AIServiceError as exc:
        assert str(exc) == "尚未配置 LLM_BASE_URL, LLM_MODEL"
    else:
        raise AssertionError("expected AIServiceError")


def test_parse_filetrans_result_builds_timestamped_segments():
    payload = {
        "transcripts": [
            {
                "text": "第一句。第二句。",
                "sentences": [
                    {
                        "begin_time": 120,
                        "end_time": 2480,
                        "text": "第一句。",
                        "language": "zh",
                    },
                    {
                        "begin_time": 2600,
                        "end_time": 4100,
                        "text": "第二句。",
                        "language": "zh",
                    },
                ],
            }
        ]
    }

    result = ai._parse_filetrans_result(payload)

    assert result["text"] == "第一句。第二句。"
    assert result["language"] == "zh"
    assert result["segments"] == [
        {"start": 0.12, "end": 2.48, "text": "第一句。"},
        {"start": 2.6, "end": 4.1, "text": "第二句。"},
    ]


def test_filetrans_submits_polls_downloads_and_deletes(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "chunk.mp3"
    audio_path.write_bytes(b"input")

    class FakeBucket:
        def __init__(self):
            self.deleted = []

        def delete_object(self, object_key):
            self.deleted.append(object_key)

    bucket = FakeBucket()
    monkeypatch.setattr(
        ai,
        "_upload_for_filetrans",
        lambda path, settings: (bucket, "prefix/audio.mp3", "https://oss.test/audio.mp3"),
    )
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        if str(request.url).endswith("/tasks/task-1"):
            return httpx.Response(
                200,
                json={
                    "output": {
                        "task_status": "SUCCEEDED",
                        "result": {"transcription_url": "https://result.test/output.json"},
                    }
                },
            )
        return httpx.Response(
            200,
            json={
                "transcripts": [
                    {
                        "text": "测试完成",
                        "sentences": [{"begin_time": 0, "end_time": 900, "text": "测试完成"}],
                    }
                ]
            },
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        stt_provider="dashscope_filetrans",
        stt_base_url="https://dashscope.test/api/v1",
        stt_model="qwen3-asr-flash-filetrans",
        stt_api_key="test-key",
    )

    result = ai.transcribe_audio(audio_path, settings)

    assert result["text"] == "测试完成"
    assert result["segments"] == [{"start": 0.0, "end": 0.9, "text": "测试完成"}]
    assert bucket.deleted == ["prefix/audio.mp3"]
    assert [request.method for request in requests] == ["POST", "GET", "GET"]


def test_filetrans_deletes_oss_object_when_task_fails(monkeypatch, tmp_path: Path):
    audio_path = tmp_path / "chunk.mp3"
    audio_path.write_bytes(b"input")

    class FakeBucket:
        def __init__(self):
            self.deleted = []

        def delete_object(self, object_key):
            self.deleted.append(object_key)

    bucket = FakeBucket()
    monkeypatch.setattr(
        ai,
        "_upload_for_filetrans",
        lambda path, settings: (bucket, "prefix/audio.mp3", "https://oss.test/audio.mp3"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        return httpx.Response(
            200,
            json={"output": {"task_status": "FAILED", "message": "bad audio"}},
        )

    class FakeClient(httpx.Client):
        def __init__(self, **kwargs):
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(ai.httpx, "Client", FakeClient)
    settings = Settings(
        stt_provider="dashscope_filetrans",
        stt_base_url="https://dashscope.test/api/v1",
        stt_model="qwen3-asr-flash-filetrans",
        stt_api_key="test-key",
    )

    try:
        ai.transcribe_audio(audio_path, settings)
    except ai.AIServiceError as exc:
        assert "bad audio" in str(exc)
    else:
        raise AssertionError("expected AIServiceError")

    assert bucket.deleted == ["prefix/audio.mp3"]
