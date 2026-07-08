"""Тесты adapter-скелета Instagram (offline, без сети)."""

import pytest

from app.integrations.instagram.client import InstagramPublishingClient
from app.integrations.publishing import PublishError, PublishRequest

TOKEN = "SECRET_IG_TOKEN_do_not_leak"


def _request() -> PublishRequest:
    return PublishRequest(platform="instagram", target_id="ig-account", text="Пост")


def test_live_off_no_network() -> None:
    client = InstagramPublishingClient(token=TOKEN, live_enabled=False)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "disabled" in str(exc_info.value).lower()
    assert TOKEN not in str(exc_info.value)


def test_missing_token_clear_error() -> None:
    client = InstagramPublishingClient(token=None, live_enabled=True)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "INSTAGRAM_ACCESS_TOKEN" in str(exc_info.value)


def test_live_not_implemented_clear_error() -> None:
    client = InstagramPublishingClient(token=TOKEN, live_enabled=True)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "Live publishing for instagram is not implemented yet" in str(exc_info.value)
    assert TOKEN not in str(exc_info.value)


def test_token_not_leaked_on_any_path() -> None:
    for live_enabled in (False, True):
        client = InstagramPublishingClient(token=TOKEN, live_enabled=live_enabled)
        with pytest.raises(PublishError) as exc_info:
            client.publish_post(_request())
        assert TOKEN not in str(exc_info.value)


def test_platform_and_live_implemented_flag() -> None:
    client = InstagramPublishingClient(token=TOKEN, live_enabled=False)
    assert client.platform == "instagram"
    assert client.live_implemented is False
