import pytest

from app.video import VideoInspectionError, inspect_video


class FakeDownloader:
    def __init__(self, options, info):
        self.info = info

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def extract_info(self, url, download=False):
        return self.info


def test_inspect_video_accepts_b23_short_link_and_uses_canonical_part_url(
    monkeypatch, settings
):
    info = {
        "id": "BV1AbCdEfGhJ",
        "webpage_url": "https://www.bilibili.com/video/BV1AbCdEfGhJ",
        "title": "短链视频",
        "duration": 42,
    }
    monkeypatch.setattr(
        "app.video.yt_dlp.YoutubeDL", lambda options: FakeDownloader(options, info)
    )

    result = inspect_video("https://b23.tv/eeAfE0Z", settings)

    assert result["bvid"] == "BV1AbCdEfGhJ"
    assert result["url"] == "https://www.bilibili.com/video/BV1AbCdEfGhJ"
    assert result["parts"][0]["url"] == (
        "https://www.bilibili.com/video/BV1AbCdEfGhJ?p=1"
    )


def test_inspect_video_rejects_non_bilibili_shortener(monkeypatch, settings):
    monkeypatch.setattr(
        "app.video.yt_dlp.YoutubeDL",
        lambda options: pytest.fail("unsupported URL must be rejected before network access"),
    )

    with pytest.raises(VideoInspectionError, match="b23.tv"):
        inspect_video("https://example.com/eeAfE0Z", settings)


def test_inspect_video_rejects_b23_link_without_resolved_bvid(monkeypatch, settings):
    info = {"id": "not-a-video", "webpage_url": "https://www.bilibili.com/"}
    monkeypatch.setattr(
        "app.video.yt_dlp.YoutubeDL", lambda options: FakeDownloader(options, info)
    )

    with pytest.raises(VideoInspectionError, match="没有解析到有效"):
        inspect_video("https://b23.tv/invalid", settings)
