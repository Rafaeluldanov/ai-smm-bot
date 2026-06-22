"""Тесты клиентов публикации и реестра платформ (без реальной сети)."""

import httpx
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


def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("сеть не должна вызываться при выключенном live publishing")


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


def test_live_disabled_by_default_no_network() -> None:
    # Без флага live publishing — сразу PublishError, без обращения к сети.
    telegram = TelegramPublishingClient(
        token="T", default_target_id="@c", transport=httpx.MockTransport(_no_network)
    )
    with pytest.raises(PublishError) as tg_exc:
        telegram.publish_post(_request("telegram"))
    assert "Live publishing disabled by config" in str(tg_exc.value)

    vk = VKPublishingClient(
        token="V", default_target_id="-100", transport=httpx.MockTransport(_no_network)
    )
    with pytest.raises(PublishError) as vk_exc:
        vk.publish_post(_request("vk"))
    assert "Live publishing disabled by config" in str(vk_exc.value)


def test_real_clients_without_token_raise() -> None:
    # Транспорт, падающий при любом сетевом вызове, доказывает: проверка токена
    # происходит ДО сети.
    no_net = httpx.MockTransport(_no_network)
    with pytest.raises(PublishError):
        TelegramPublishingClient(token=None, live_enabled=True, transport=no_net).publish_post(
            _request("telegram")
        )
    with pytest.raises(PublishError):
        VKPublishingClient(token=None, live_enabled=True, transport=no_net).publish_post(
            _request("vk")
        )


def test_real_client_without_target_raises() -> None:
    request = PublishRequest(platform="telegram", target_id=None, text="x")
    with pytest.raises(PublishError):
        TelegramPublishingClient(
            token="secret", live_enabled=True, transport=httpx.MockTransport(_no_network)
        ).publish_post(request)


def test_vk_normalize_owner_handles_malformed_without_crash() -> None:
    assert VKPublishingClient._normalize_owner("100") == "-100"
    assert VKPublishingClient._normalize_owner("-100") == "-100"
    assert VKPublishingClient._normalize_owner("club5") == "club5"
    # Некорректный таргет с двойным минусом НЕ должен ронять ValueError.
    assert VKPublishingClient._normalize_owner("--100") == "--100"


def test_telegram_ok_without_message_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})  # ok, но без result/message_id

    client = TelegramPublishingClient(
        token="T",
        default_target_id="@c",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PublishError):
        client.publish_post(_request("telegram"))


def test_vk_without_post_id_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"response": {}})  # без post_id

    client = VKPublishingClient(
        token="V",
        default_target_id="-100",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PublishError):
        client.publish_post(_request("vk"))


def test_non_json_200_wrapped_in_publish_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>maintenance</html>")

    telegram = TelegramPublishingClient(
        token="T",
        default_target_id="@c",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PublishError):
        telegram.publish_post(_request("telegram"))

    vk = VKPublishingClient(
        token="V",
        default_target_id="-100",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PublishError):
        vk.publish_post(_request("vk"))


def test_telegram_live_enabled_calls_mocked_transport() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 42, "chat": {"username": "teeon"}}},
        )

    client = TelegramPublishingClient(
        token="T",
        default_target_id="@teeon",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    response = client.publish_post(_request("telegram"))
    assert response.external_post_id == "42"
    assert "/botT/sendMessage" in seen["url"]


def test_vk_live_enabled_calls_mocked_transport() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(200, json={"response": {"post_id": 99}})

    client = VKPublishingClient(
        token="V",
        default_target_id="-100",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    response = client.publish_post(_request("vk"))
    assert response.external_post_id == "99"
    assert "/method/wall.post" in seen["url"]


def test_telegram_live_api_error_raises_publish_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "chat not found"})

    client = TelegramPublishingClient(
        token="T",
        default_target_id="@teeon",
        live_enabled=True,
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PublishError):
        client.publish_post(_request("telegram"))
