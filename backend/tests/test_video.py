import httpx
import pytest

from app.video import VideoInspectionError, _resolve_short_link, inspect_video


class FakeDownloader:
    def __init__(self, options, info):
        self.info = info

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def extract_info(self, url, download=False):
        return self.info


def test_resolve_short_link_uses_redirect_without_requesting_destination(monkeypatch):
    requested = []

    def handle(request):
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://www.bilibili.com/video/BV1CjV16KEHe?p=1"},
        )

    transport = httpx.MockTransport(handle)
    real_client = httpx.Client
    monkeypatch.setattr(
        "app.video.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    assert _resolve_short_link("https://b23.tv/vOQYg0H") == (
        "https://www.bilibili.com/video/BV1CjV16KEHe"
    )
    assert requested == ["https://b23.tv/vOQYg0H"]


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
    monkeypatch.setattr(
        "app.video._resolve_short_link",
        lambda url: "https://www.bilibili.com/video/BV1AbCdEfGhJ",
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
    monkeypatch.setattr(
        "app.video._resolve_short_link",
        lambda url: (_ for _ in ()).throw(VideoInspectionError("b23.tv 短链无效或已过期")),
    )

    with pytest.raises(VideoInspectionError, match="无效或已过期"):
        inspect_video("https://b23.tv/invalid", settings)


def test_short_link_is_resolved_before_yt_dlp(monkeypatch, settings):
    requested = []
    info = {
        "id": "BV1AbCdEfGhJ",
        "webpage_url": "https://www.bilibili.com/video/BV1AbCdEfGhJ",
        "title": "短链视频",
    }

    class RecordingDownloader(FakeDownloader):
        def extract_info(self, url, download=False):
            requested.append(url)
            return self.info

    monkeypatch.setattr(
        "app.video._resolve_short_link",
        lambda url: "https://www.bilibili.com/video/BV1AbCdEfGhJ",
    )
    monkeypatch.setattr(
        "app.video.yt_dlp.YoutubeDL", lambda options: RecordingDownloader(options, info)
    )

    inspect_video("https://b23.tv/valid", settings)

    assert requested == ["https://www.bilibili.com/video/BV1AbCdEfGhJ"]
