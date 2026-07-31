import pytest

from app.subtitles import normalize_segments, parse_bilibili_json, parse_vtt_srt
from app.utils import safe_filename, timestamp_url
from app.video import VideoInspectionError, _cover_url, inspect_video


def test_safe_filename_removes_illegal_characters():
    assert safe_filename('  教程: A/B? * "入门"  ') == "教程- A-B- - -入门"
    assert safe_filename("...") == "未命名"


def test_normalize_merges_duplicate_overlapping_segments():
    value = normalize_segments(
        [
            {"start": 0, "end": 1, "text": " 你好 "},
            {"start": 1.1, "end": 2, "text": "你好"},
            {"start": 2, "end": 3, "text": "世界"},
        ],
        "subtitle",
    )
    assert value == [
        {"start": 0.0, "end": 2.0, "text": "你好", "source": "subtitle"},
        {"start": 2.0, "end": 3.0, "text": "世界", "source": "subtitle"},
    ]


def test_parse_common_subtitle_formats():
    vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n<b>Hello</b> world\n"
    assert parse_vtt_srt(vtt)[0]["text"] == "Hello world"
    bili = '{"body":[{"from":1.2,"to":2.3,"content":"测试"}]}'
    assert parse_bilibili_json(bili)[0]["start"] == 1.2
    json3 = (
        '{"events":[{"tStartMs":2000,"dDurationMs":1500,"segs":[{"utf8":"自动"},{"utf8":"字幕"}]}]}'
    )
    assert parse_bilibili_json(json3)[0]["text"] == "自动字幕"


def test_cover_url_prefers_thumbnail_and_normalizes_https():
    assert _cover_url({"thumbnail": "http://i0.hdslb.com/test.jpg"}) == (
        "https://i0.hdslb.com/test.jpg"
    )


def test_inspect_rejects_multipart_video(monkeypatch, settings):
    class FakeDownloader:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, url, download):
            return {
                "id": "BV1234567890",
                "entries": [
                    {"id": "part-1", "title": "P1"},
                    {"id": "part-2", "title": "P2"},
                ],
            }

    monkeypatch.setattr("app.video.yt_dlp.YoutubeDL", FakeDownloader)

    with pytest.raises(VideoInspectionError, match="暂不支持分 P"):
        inspect_video("https://www.bilibili.com/video/BV1234567890", settings)
    assert _cover_url({"thumbnails": [{"url": "//i1.hdslb.com/fallback.jpg"}]}) == (
        "https://i1.hdslb.com/fallback.jpg"
    )


def test_timestamp_url_preserves_query():
    assert timestamp_url("https://example.test/video?p=2", 65).endswith("p=2&t=65")
