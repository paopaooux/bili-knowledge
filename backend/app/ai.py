from __future__ import annotations

import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path
from threading import Event

import dashscope
import httpx
import oss2
from dashscope.audio.qwen_omni import MultiModality, OmniRealtimeCallback, OmniRealtimeConversation
from dashscope.audio.qwen_omni.omni_realtime import TranscriptionParams

from .config import Settings

logger = logging.getLogger("uvicorn.error")

RETRYABLE_LLM_STATUS_CODES = {502, 503, 504}
LLM_GATEWAY_RETRY_DELAYS_SECONDS = (1, 2, 4, 8)


class AIServiceError(RuntimeError):
    pass


def _retryable_llm_status(error: BaseException) -> int | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            return status if status in RETRYABLE_LLM_STATUS_CODES else None
        current = current.__cause__
    # Some OpenAI-compatible gateways accept the HTTP stream with status 200 and then
    # report an upstream 5xx failure inside an SSE error event.
    match = re.search(r"\[(502|503|504)\]", str(error))
    if match:
        return int(match.group(1))
    return None


def _headers(key: str | None) -> dict[str, str]:
    if not key:
        raise AIServiceError("尚未配置 API 密钥")
    return {"Authorization": f"Bearer {key}"}


def _require_model_config(base_url: str, model: str, prefix: str) -> None:
    missing = []
    if not base_url:
        missing.append(f"{prefix}_BASE_URL")
    if not model:
        missing.append(f"{prefix}_MODEL")
    if missing:
        raise AIServiceError(f"尚未配置 {', '.join(missing)}")


class _QwenASRCallback(OmniRealtimeCallback):
    def __init__(self) -> None:
        self.segments: list[dict] = []
        self.starts: dict[str, float] = {}
        self.ends: dict[str, float] = {}
        self.errors: list[str] = []
        self.language: str | None = None
        self.session_created = Event()

    def on_open(self) -> None:
        pass

    def on_close(self, close_status_code, close_msg) -> None:
        pass

    def on_event(self, response: dict) -> None:
        event_type = response.get("type")
        if event_type == "session.created":
            self.session_created.set()
        elif event_type == "input_audio_buffer.speech_started":
            self.starts[response.get("item_id", "")] = (
                float(response.get("audio_start_ms", 0)) / 1000
            )
        elif event_type == "input_audio_buffer.speech_stopped":
            self.ends[response.get("item_id", "")] = float(response.get("audio_end_ms", 0)) / 1000
        elif event_type == "conversation.item.input_audio_transcription.completed":
            text = str(response.get("transcript", "")).strip()
            item_id = response.get("item_id", "")
            self.language = response.get("language") or self.language
            if text:
                start = self.starts.get(item_id, self.segments[-1]["end"] if self.segments else 0.0)
                end = max(start, self.ends.get(item_id, start))
                self.segments.append({"start": start, "end": end, "text": text})
        elif event_type == "error":
            error = response.get("error") or {}
            self.errors.append(str(error.get("message") or error.get("code") or "未知错误"))


def _pcm_from_audio(path: Path) -> Path:
    pcm_path = path.with_suffix(".pcm")
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "-acodec",
        "pcm_s16le",
        str(pcm_path),
    ]
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise AIServiceError("未找到 ffmpeg，无法为千问实时转写转换音频") from exc
    except subprocess.CalledProcessError as exc:
        raise AIServiceError(f"转换千问 PCM 音频失败：{exc.stderr[-500:]}") from exc
    return pcm_path


def _qwen_conversation(settings: Settings, callback: _QwenASRCallback) -> OmniRealtimeConversation:
    _headers(settings.stt_api_key)
    return OmniRealtimeConversation(
        model=settings.stt_model,
        url=settings.stt_base_url,
        callback=callback,
        api_key=settings.stt_api_key,
    )


def _configure_qwen_conversation(conversation: OmniRealtimeConversation) -> None:
    conversation.update_session(
        output_modalities=[MultiModality.TEXT],
        enable_turn_detection=True,
        turn_detection_type="server_vad",
        turn_detection_threshold=0.2,
        turn_detection_silence_duration_ms=800,
        enable_input_audio_transcription=True,
        transcription_params=TranscriptionParams(
            language="zh",
            sample_rate=16000,
            input_audio_format="pcm",
        ),
    )


def _transcribe_dashscope_realtime(path: Path, settings: Settings) -> dict:
    pcm_path = _pcm_from_audio(path)
    callback = _QwenASRCallback()
    conversation = _qwen_conversation(settings, callback)
    try:
        conversation.connect()
        if not callback.session_created.wait(timeout=10):
            raise AIServiceError("千问实时转写连接成功，但未收到 session.created")
        _configure_qwen_conversation(conversation)
        with pcm_path.open("rb") as audio:
            while chunk := audio.read(3200):
                conversation.append_audio(base64.b64encode(chunk).decode("ascii"))
                # 3200 bytes = 100 ms 的 16 kHz/16-bit/单声道 PCM。实时接口需按音频速率发送。
                time.sleep(len(chunk) / 32_000)
        conversation.end_session(timeout=max(20, settings.request_timeout_seconds))
    except AIServiceError:
        raise
    except Exception as exc:
        raise AIServiceError(f"千问实时转写失败：{exc}") from exc
    finally:
        with suppress(Exception):
            conversation.close()
        pcm_path.unlink(missing_ok=True)
    if callback.errors:
        raise AIServiceError(f"千问实时转写返回错误：{'; '.join(callback.errors)}")
    if not callback.segments:
        raise AIServiceError("千问实时转写未返回有效文本")
    return {
        "text": " ".join(segment["text"] for segment in callback.segments),
        "segments": callback.segments,
        "language": callback.language or "zh",
    }


def transcribe_audio(path: Path, settings: Settings) -> dict:
    _require_model_config(settings.stt_base_url, settings.stt_model, "STT")
    if settings.stt_provider == "dashscope_realtime":
        return _transcribe_dashscope_realtime(path, settings)
    if settings.stt_provider == "dashscope_flash":
        if settings.stt_model == "qwen-audio-3.0-asr-flash":
            return _transcribe_qwen_audio_3(path, settings)
        return _transcribe_dashscope_flash(path, settings)
    if settings.stt_provider == "dashscope_filetrans":
        return _transcribe_dashscope_filetrans(path, settings)
    raise AIServiceError(f"不支持的语音转写方式：{settings.stt_provider}")


def _value(value, key: str, default=None):
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _transcribe_dashscope_flash(path: Path, settings: Settings) -> dict:
    _headers(settings.stt_api_key)
    dashscope.base_http_api_url = settings.stt_base_url.rstrip("/")
    call_options = {
        "api_key": settings.stt_api_key,
        "model": settings.stt_model,
        "messages": [
            {
                "role": "system",
                "content": [
                    {
                        "text": "请忠实转写音频中的所有语音，只输出转写文本，不要总结或回答内容。"
                    }
                ],
            },
            {"role": "user", "content": [{"audio": path.resolve().as_uri()}]},
        ],
        "result_format": "message",
    }
    if settings.stt_model.startswith("qwen3-asr-"):
        call_options["asr_options"] = {"enable_lid": True, "enable_itn": False}
    try:
        response = dashscope.MultiModalConversation.call(**call_options)
    except Exception as exc:
        raise AIServiceError(f"千问 {settings.stt_model} 转写失败：{exc}") from exc

    status_code = _value(response, "status_code", 200)
    if status_code != 200:
        message = _value(response, "message") or _value(response, "code") or status_code
        raise AIServiceError(f"千问 {settings.stt_model} 转写失败：{message}")
    try:
        output = _value(response, "output")
        choices = _value(output, "choices", [])
        message = _value(choices[0], "message")
        content = _value(message, "content", [])
        text = "".join(str(_value(item, "text", "")) for item in content).strip()
    except (IndexError, TypeError) as exc:
        raise AIServiceError(f"千问 {settings.stt_model} 返回结构异常") from exc
    if not text:
        raise AIServiceError(f"千问 {settings.stt_model} 未返回有效文本")
    return {"text": text, "segments": [], "language": "unknown"}


def _transcribe_qwen_audio_3(path: Path, settings: Settings) -> dict:
    """Call qwen-audio-3.0-asr-flash using its native HTTP input_audio schema."""
    _headers(settings.stt_api_key)
    fd, wav_name = tempfile.mkstemp(prefix="qwen-asr-", suffix=".wav")
    os.close(fd)
    wav_path = Path(wav_name)
    try:
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(path),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise AIServiceError("未找到 ffmpeg，无法转换 qwen-audio-3.0-asr-flash 音频") from exc
        except subprocess.CalledProcessError as exc:
            raise AIServiceError(f"转换 qwen-audio-3.0-asr-flash 音频失败：{exc.stderr[-500:]}") from exc

        encoded = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        url = settings.stt_base_url.rstrip("/") + "/services/aigc/multimodal-generation/generation"
        payload = {
            "model": settings.stt_model,
            "input": {
                "messages": [{
                    "role": "user",
                    "content": [{
                        "type": "input_audio",
                        "input_audio": {"data": f"data:audio/wav;base64,{encoded}"},
                    }],
                }],
            },
            "parameters": {"format": "wav", "sample_rate": "16000"},
        }
        headers = {**_headers(settings.stt_api_key), "Content-Type": "application/json", "X-DashScope-SSE": "disable"}
        try:
            with httpx.Client(timeout=settings.request_timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AIServiceError(f"千问 {settings.stt_model} 转写失败：{exc}") from exc

        output = result.get("output") or {}
        choices = output.get("choices") or []
        message = choices[0].get("message") if choices else {}
        content = message.get("content") if isinstance(message, dict) else []
        if isinstance(content, str):
            text = content.strip()
        else:
            text = "".join(str(item.get("text", "")) for item in (content or []) if isinstance(item, dict)).strip()
        if not text:
            error = result.get("message") or result.get("code") or "未返回有效文本"
            raise AIServiceError(f"千问 {settings.stt_model} 转写失败：{error}")
        return {"text": text, "segments": [], "language": "unknown"}
    finally:
        wav_path.unlink(missing_ok=True)


def _oss_bucket(settings: Settings) -> oss2.Bucket:
    missing = [
        name
        for name, value in {
            "OSS_ENDPOINT": settings.oss_endpoint,
            "OSS_BUCKET": settings.oss_bucket,
            "OSS_ACCESS_KEY_ID": settings.oss_access_key_id,
            "OSS_ACCESS_KEY_SECRET": settings.oss_access_key_secret,
        }.items()
        if not value
    ]
    if missing:
        raise AIServiceError(f"千问文件转写需要 OSS 配置：{', '.join(missing)}")
    auth = oss2.Auth(settings.oss_access_key_id, settings.oss_access_key_secret)
    return oss2.Bucket(auth, settings.oss_endpoint, settings.oss_bucket)


def _upload_for_filetrans(path: Path, settings: Settings) -> tuple[oss2.Bucket, str, str]:
    bucket = _oss_bucket(settings)
    prefix = settings.oss_prefix.strip("/") or "bili-knowledge-stt"
    object_key = f"{prefix}/{uuid.uuid4().hex}{path.suffix.lower()}"
    try:
        bucket.put_object_from_file(object_key, str(path))
        signed_url = bucket.sign_url("GET", object_key, 7200, slash_safe=True)
    except oss2.exceptions.OssError as exc:
        raise AIServiceError(f"上传临时音频到 OSS 失败：{exc}") from exc
    return bucket, object_key, signed_url


def _dashscope_error(response: httpx.Response) -> str:
    try:
        payload = response.json()
        output = payload.get("output") or {}
        return str(output.get("message") or payload.get("message") or response.text[:500])
    except ValueError:
        return response.text[:500] or f"HTTP {response.status_code}"


def _parse_filetrans_result(payload: dict) -> dict:
    segments = []
    texts = []
    language = None
    for transcript in payload.get("transcripts") or []:
        if transcript.get("text"):
            texts.append(str(transcript["text"]).strip())
        for sentence in transcript.get("sentences") or []:
            text = str(sentence.get("text", "")).strip()
            if not text:
                continue
            language = language or sentence.get("language")
            segments.append(
                {
                    "start": float(sentence.get("begin_time", 0)) / 1000,
                    "end": float(sentence.get("end_time", 0)) / 1000,
                    "text": text,
                }
            )
    text = " ".join(texts) or " ".join(segment["text"] for segment in segments)
    if not text:
        raise AIServiceError("千问文件转写结果中没有文本")
    return {"text": text, "segments": segments, "language": language or "unknown"}


def _transcribe_dashscope_filetrans(path: Path, settings: Settings) -> dict:
    _headers(settings.stt_api_key)
    bucket, object_key, signed_url = _upload_for_filetrans(path, settings)
    headers = {
        "Authorization": f"Bearer {settings.stt_api_key}",
        "Content-Type": "application/json",
    }
    base_url = settings.stt_base_url.rstrip("/")
    try:
        with httpx.Client(timeout=settings.request_timeout_seconds) as client:
            response = client.post(
                base_url + "/services/audio/asr/transcription",
                headers={**headers, "X-DashScope-Async": "enable"},
                json={
                    "model": settings.stt_model,
                    "input": {"file_url": signed_url},
                    "parameters": {
                        "channel_id": [0],
                        "enable_itn": True,
                        "enable_words": True,
                    },
                },
            )
            if response.status_code != 200:
                raise AIServiceError(f"提交千问文件转写失败：{_dashscope_error(response)}")
            try:
                task_id = response.json()["output"]["task_id"]
            except (ValueError, KeyError, TypeError) as exc:
                raise AIServiceError("千问文件转写提交响应缺少 task_id") from exc

            deadline = time.monotonic() + settings.stt_poll_timeout_seconds
            while True:
                if time.monotonic() >= deadline:
                    raise AIServiceError("等待千问文件转写结果超时")
                query = client.get(base_url + f"/tasks/{task_id}", headers=headers)
                if query.status_code != 200:
                    raise AIServiceError(f"查询千问文件转写失败：{_dashscope_error(query)}")
                output = query.json().get("output") or {}
                status = str(output.get("task_status", "")).upper()
                if status == "SUCCEEDED":
                    result_url = (output.get("result") or {}).get("transcription_url")
                    if not result_url:
                        raise AIServiceError("千问任务成功但没有 transcription_url")
                    result_response = client.get(result_url)
                    result_response.raise_for_status()
                    return _parse_filetrans_result(result_response.json())
                if status in {"FAILED", "UNKNOWN"}:
                    message = output.get("message") or output.get("code") or status
                    raise AIServiceError(f"千问文件转写任务失败：{message}")
                time.sleep(2)
    except AIServiceError:
        raise
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise AIServiceError(f"千问文件转写请求失败：{exc}") from exc
    finally:
        with suppress(oss2.exceptions.OssError):
            bucket.delete_object(object_key)


def chat(messages: list[dict], settings: Settings, max_tokens: int = 3000) -> str:
    _require_model_config(settings.llm_base_url, settings.llm_model, "LLM")
    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    input_chars = sum(len(str(message.get("content", ""))) for message in messages)
    started = time.monotonic()
    budget = max_tokens
    attempts = 0
    gateway_retries = 0
    while True:
        try:
            content, reasoning_chars, truncated = _stream_chat(messages, settings, url, budget)
        except AIServiceError as exc:
            status = _retryable_llm_status(exc)
            if status is None or gateway_retries >= len(LLM_GATEWAY_RETRY_DELAYS_SECONDS):
                raise
            delay = LLM_GATEWAY_RETRY_DELAYS_SECONDS[gateway_retries]
            gateway_retries += 1
            attempts += 1
            logger.warning(
                "LLM gateway request failed; retrying model=%s status=%d retry=%d delay=%ds",
                settings.llm_model,
                status,
                gateway_retries,
                delay,
            )
            time.sleep(delay)
            continue
        # 输出被 max_tokens 截断时，用双倍额度重试一次，避免把半截 JSON 交给上层。
        if truncated and budget < 32768:
            attempts += 1
            budget = min(budget * 2, 32768)
            logger.warning(
                "LLM output truncated by max_tokens input_chars=%d old_max_tokens=%d retry_max_tokens=%d",
                input_chars,
                budget // 2,
                budget,
            )
            continue
        if content:
            logger.info(
                "LLM request completed model=%s output_chars=%d elapsed=%.2fs attempts=%d",
                settings.llm_model,
                len(content),
                time.monotonic() - started,
                attempts + 1,
            )
            return content
        if not reasoning_chars:
            raise AIServiceError("知识稿模型返回了空内容")
        if budget >= 32768:
            raise AIServiceError(
                "知识稿模型把输出额度全部用在了思考上，没有产出正文。"
                "系统已自动把 max_tokens 扩到 32768；请设置 "
                "LLM_ENABLE_THINKING=false 后重启服务，或改用非思考模型。"
            )
        attempts += 1
        budget = min(budget * 2, 32768)
        logger.warning(
            "LLM reasoning consumed the budget input_chars=%d old_max_tokens=%d retry_max_tokens=%d",
            input_chars,
            budget // 2,
            budget,
        )


def _stream_chat(
    messages: list[dict],
    settings: Settings,
    url: str,
    max_tokens: int,
) -> tuple[str, int, bool]:
    request_payload = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if settings.llm_enable_thinking is not None:
        request_payload["enable_thinking"] = settings.llm_enable_thinking
    if settings.llm_model == "qwen3.5-omni-plus":
        request_payload.update(
            {
                "stream_options": {"include_usage": True},
                "modalities": ["text", "audio"],
                "audio": {"voice": "Ethan", "format": "wav"},
            }
        )
    started = time.monotonic()
    logger.info(
        "LLM request started model=%s messages=%d input_chars=%d max_tokens=%d",
        settings.llm_model,
        len(messages),
        sum(len(str(message.get("content", ""))) for message in messages),
        max_tokens,
    )
    try:
        with (
            httpx.Client(timeout=settings.request_timeout_seconds) as client,
            client.stream(
                "POST",
                url,
                headers={**_headers(settings.llm_api_key), "Content-Type": "application/json"},
                json=request_payload,
            ) as response,
        ):
            response.raise_for_status()
            parts = []
            audio_transcript_parts = []
            reasoning_chars = 0
            truncated = False
            for line in response.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                payload = json.loads(data)
                if not isinstance(payload, dict):
                    continue
                error = payload.get("error")
                if error:
                    if isinstance(error, dict):
                        message = error.get("message") or error.get("code") or str(error)
                    else:
                        message = str(error)
                    raise AIServiceError(f"知识稿模型返回错误：{message}")
                choices = payload.get("choices")
                if not isinstance(choices, list) or not choices:
                    logger.debug("Ignored LLM stream event without choices keys=%s", payload.keys())
                    continue
                choice = choices[0]
                if not isinstance(choice, dict):
                    continue
                if choice.get("finish_reason") == "length":
                    truncated = True
                delta = choice.get("delta") or {}
                if not isinstance(delta, dict):
                    continue
                piece = delta.get("content")
                if piece:
                    parts.append(str(piece))
                reasoning = delta.get("reasoning_content")
                if reasoning:
                    reasoning_chars += len(str(reasoning))
                audio = delta.get("audio")
                if isinstance(audio, dict) and audio.get("transcript"):
                    audio_transcript_parts.append(str(audio["transcript"]))
        content = "".join(parts).strip() or "".join(audio_transcript_parts).strip()
        return content, reasoning_chars, truncated
    except AIServiceError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        logger.warning(
            "LLM request failed model=%s elapsed=%.2fs error_type=%s",
            settings.llm_model,
            time.monotonic() - started,
            type(exc).__name__,
        )
        raise AIServiceError(f"知识稿模型请求失败：{exc}") from exc


def test_service(service: str, settings: Settings) -> dict:
    if service == "llm":
        _require_model_config(settings.llm_base_url, settings.llm_model, "LLM")
        result = chat([{"role": "user", "content": "只回复 OK"}], settings, max_tokens=2000)
        return {"service": service, "ok": True, "message": result[:100]}
    _require_model_config(settings.stt_base_url, settings.stt_model, "STT")
    if settings.stt_provider == "dashscope_realtime":
        callback = _QwenASRCallback()
        conversation = _qwen_conversation(settings, callback)
        try:
            conversation.connect()
            if not callback.session_created.wait(timeout=10):
                raise AIServiceError("连接成功，但未收到千问会话确认")
            return {"service": service, "ok": True, "message": "千问 WebSocket 鉴权成功"}
        except AIServiceError:
            raise
        except Exception as exc:
            raise AIServiceError(f"千问 STT 连接测试失败：{exc}") from exc
        finally:
            with suppress(Exception):
                conversation.close()
    if settings.stt_provider == "dashscope_filetrans":
        _headers(settings.stt_api_key)
        _oss_bucket(settings)
        return {
            "service": service,
            "ok": True,
            "message": "千问文件转写与 OSS 配置完整（未发起付费转写）",
        }
    if settings.stt_provider == "dashscope_flash":
        _headers(settings.stt_api_key)
        return {
            "service": service,
            "ok": True,
            "message": f"千问 {settings.stt_model} 配置完整（未发起付费转写）",
        }
    url = settings.stt_base_url.rstrip("/") + "/models"
    try:
        with httpx.Client(timeout=20) as client:
            response = client.get(url, headers=_headers(settings.stt_api_key))
            response.raise_for_status()
            response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise AIServiceError(f"STT 服务连接测试失败：{exc}") from exc
    return {"service": service, "ok": True, "message": "连接成功"}
