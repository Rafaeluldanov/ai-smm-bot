"""Тесты v0.2.9: публичный HTTPS VK OAuth callback (PUBLIC_APP_URL) — offline.

Проверяют вывод VK_OAUTH_REDIRECT_URI из PUBLIC_APP_URL, базовый домен, CLI
setup-info (без секретов; проверка live-флага) и probe=none при VK error 27.
"""

import httpx
import pytest

from app.config import Settings
from app.integrations.vk.client import VKPublishingClient
from app.scripts import show_vk_oauth_setup as setup


def test_redirect_derived_from_public_app_url() -> None:
    settings = Settings(
        _env_file=None, public_app_url="https://app.teeon.ru", vk_oauth_redirect_uri=""
    )
    assert settings.vk_oauth_redirect_uri == "https://app.teeon.ru/integrations/vk/oauth/callback"
    assert settings.vk_oauth_base_domain == "app.teeon.ru"


def test_public_app_url_trailing_slash_normalised() -> None:
    settings = Settings(
        _env_file=None, public_app_url="https://app.teeon.ru/", vk_oauth_redirect_uri=""
    )
    assert settings.vk_oauth_redirect_uri == "https://app.teeon.ru/integrations/vk/oauth/callback"


def test_explicit_redirect_wins_over_public_app_url() -> None:
    settings = Settings(
        _env_file=None,
        public_app_url="https://app.teeon.ru",
        vk_oauth_redirect_uri="https://x.example/integrations/vk/oauth/callback",
    )
    assert settings.vk_oauth_redirect_uri == "https://x.example/integrations/vk/oauth/callback"
    assert settings.vk_oauth_base_domain == "x.example"


def test_setup_info_prints_no_secret_and_live_off(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(
        _env_file=None,
        public_app_url="https://app.teeon.ru",
        vk_oauth_redirect_uri="",
        vk_app_id="54671660",
        vk_app_secret="TOPSECRET_do_not_leak",
        vk_live_publishing_enabled=False,
    )
    info = setup.build_info(settings)
    assert info["public_app_url"] == "https://app.teeon.ru"
    assert info["vk_app_id"] == "54671660"
    assert info["vk_id_base_domain"] == "app.teeon.ru"
    assert info["vk_id_redirect_url"] == "https://app.teeon.ru/integrations/vk/oauth/callback"
    assert info["vk_oauth_configured"] is True

    setup.print_info(info)
    out = capsys.readouterr().out
    assert "app.teeon.ru" in out
    assert "https://app.teeon.ru/integrations/vk/oauth/callback" in out
    assert "TOPSECRET_do_not_leak" not in out  # секрет не печатается
    assert "VK_LIVE_PUBLISHING_ENABLED=false" in out


def test_setup_info_warns_when_live_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    settings = Settings(_env_file=None, vk_live_publishing_enabled=True)
    setup.print_info(setup.build_info(settings))
    out = capsys.readouterr().out
    assert "VK_LIVE_PUBLISHING_ENABLED=true" in out
    assert "⚠️" in out


def test_probe_recommends_none_on_error_27() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "groups.getById" in path:
            return httpx.Response(200, json={"response": [{"id": 100, "name": "TEEON"}]})
        if "photos.getWallUploadServer" in path:
            return httpx.Response(200, json={"error": {"error_code": 27, "error_msg": "group"}})
        if "photos.getAlbums" in path:
            return httpx.Response(200, json={"error": {"error_code": 27, "error_msg": "group"}})
        return httpx.Response(200, json={"error": {"error_code": 1, "error_msg": "x"}})

    client = VKPublishingClient(
        token="TK",
        default_target_id="-240102732",
        transport=httpx.MockTransport(handler),
        photo_upload_strategy="auto",
    )
    result = client.probe_photo_strategies(allow_upload=False)
    assert result["wall"]["ok"] is False and result["wall"]["error_code"] == 27
    assert result["album"]["ok"] is False and result["album"]["error_code"] == 27
    assert result["recommended_strategy"] == "none"
