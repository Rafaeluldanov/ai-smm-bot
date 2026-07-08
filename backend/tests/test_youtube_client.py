"""Тесты adapter-скелета YouTube (offline, без сети)."""

import pytest

from app.integrations.publishing import PublishError, PublishRequest
from app.integrations.youtube.client import YouTubePublishingClient

TOKEN = "SECRET_YT_TOKEN_do_not_leak"


def _request() -> PublishRequest:
    return PublishRequest(platform="youtube", target_id="yt-channel", text="Видео")


def test_live_off_no_network() -> None:
    client = YouTubePublishingClient(token=TOKEN, live_enabled=False)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "disabled" in str(exc_info.value).lower()
    assert TOKEN not in str(exc_info.value)


def test_missing_token_clear_error() -> None:
    client = YouTubePublishingClient(token=None, live_enabled=True)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "YOUTUBE_ACCESS_TOKEN" in str(exc_info.value)


def test_live_not_implemented_clear_error() -> None:
    client = YouTubePublishingClient(token=TOKEN, live_enabled=True)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "Live publishing for youtube is not implemented yet" in str(exc_info.value)
    assert TOKEN not in str(exc_info.value)


def test_token_not_leaked_on_any_path() -> None:
    for live_enabled in (False, True):
        client = YouTubePublishingClient(token=TOKEN, live_enabled=live_enabled)
        with pytest.raises(PublishError) as exc_info:
            client.publish_post(_request())
        assert TOKEN not in str(exc_info.value)


def test_platform_and_live_implemented_flag() -> None:
    client = YouTubePublishingClient(token=TOKEN, live_enabled=False)
    assert client.platform == "youtube"
    assert client.live_implemented is False
