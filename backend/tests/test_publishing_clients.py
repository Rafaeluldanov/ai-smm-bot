"""Тесты клиентов публикации и реестра платформ (без сети)."""

import pytest

from app.integrations.publishing import FakePublishingClient, PublishError, PublishRequest
from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.services.publication_platform_registry import (
    PublicationPlatformRegistry,
    UnknownPlatformError,
)


def _request(platform: str) -> PublishRequest:
    return PublishRequest(platform=platform, target_id="target", text="Привет", hashtags=["#teeon"])


def test_registry_returns_clients() -> None:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram"), "vk": FakePublishingClient("vk")}
    )
    assert registry.get_client("telegram").platform == "telegram"
    assert registry.get_client("vk").platform == "vk"
    assert set(registry.get_available_platforms()) == {"telegram", "vk"}


def test_registry_unknown_platform() -> None:
    registry = PublicationPlatformRegistry({})
    with pytest.raises(UnknownPlatformError):
        registry.get_client("instagram")


def test_fake_client_success() -> None:
    client = FakePublishingClient("telegram", external_post_id="abc")
    response = client.publish_post(_request("telegram"))
    assert response.external_post_id == "abc"
    assert response.external_url is not None
    assert len(client.calls) == 1


def test_fake_client_failure() -> None:
    client = FakePublishingClient("vk", fail=True)
    with pytest.raises(PublishError):
        client.publish_post(_request("vk"))


def test_real_clients_without_token_raise() -> None:
    with pytest.raises(PublishError):
        TelegramPublishingClient(token=None).publish_post(_request("telegram"))
    with pytest.raises(PublishError):
        VKPublishingClient(token=None).publish_post(_request("vk"))


def test_real_client_without_target_raises() -> None:
    request = PublishRequest(platform="telegram", target_id=None, text="x")
    with pytest.raises(PublishError):
        TelegramPublishingClient(token="secret").publish_post(request)
