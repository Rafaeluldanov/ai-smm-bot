"""Тесты dev-мастера HTTPS-туннеля для VK OAuth (offline; без Docker/сети/subprocess).

Проверяют только чистые функции: парсинг URL, сборку redirect, обновление .env,
редакцию секретов и текст отчёта/причины. Реальный туннель/subprocess не запускаются.
"""

from app.scripts import dev_vk_oauth_tunnel_wizard as wiz

SECRET = "vk-app-secret-DO-NOT-LEAK-123"
ACCESS_TOKEN = "vk-access-token-KEEP-456"

CLOUDFLARED_LOG = """
2026-01-01T00:00:00Z INF Thank you for trying Cloudflare Tunnel.
2026-01-01T00:00:01Z INF +--------------------------------------------------------+
2026-01-01T00:00:01Z INF |  https://calm-frog-1234.trycloudflare.com              |
2026-01-01T00:00:01Z INF +--------------------------------------------------------+
"""


def test_parse_trycloudflare_url_from_logs() -> None:
    assert wiz.parse_tunnel_url(CLOUDFLARED_LOG) == "https://calm-frog-1234.trycloudflare.com"
    assert wiz.parse_tunnel_url("no tunnel url in this line") is None
    assert wiz.parse_tunnel_url("") is None


def test_build_vk_redirect_values() -> None:
    values = wiz.build_redirect_values("https://calm-frog-1234.trycloudflare.com/")
    assert values["tunnel_url"] == "https://calm-frog-1234.trycloudflare.com"
    assert values["domain"] == "calm-frog-1234.trycloudflare.com"
    assert (
        values["redirect_uri"]
        == "https://calm-frog-1234.trycloudflare.com/integrations/vk/oauth/callback"
    )


def test_env_update_does_not_print_secret() -> None:
    updates = wiz.build_env_updates(
        "https://calm-frog-1234.trycloudflare.com", SECRET, existing_group_id=None
    )
    assert updates is not None
    lines = wiz.update_env_lines([], updates)
    joined = "\n".join(lines)
    # Секрет ДОЛЖЕН попасть в файл .env…
    assert f"VK_APP_SECRET={SECRET}" in joined
    # …но при печати/логировании он маскируется.
    assert SECRET not in wiz.redact_sensitive(joined)
    # Live не включается.
    assert wiz.read_env_value(lines, "VK_LIVE_PUBLISHING_ENABLED") == "false"


def test_env_update_preserves_vk_access_token() -> None:
    original = [
        f"VK_ACCESS_TOKEN={ACCESS_TOKEN}",
        "TELEGRAM_BOT_TOKEN=keep-me",
        "VK_APP_ID=old",
    ]
    updates = wiz.build_env_updates(
        "https://x-y.trycloudflare.com", SECRET, existing_group_id="240102732"
    )
    assert updates is not None
    result = wiz.update_env_lines(original, updates)
    # VK_ACCESS_TOKEN и TELEGRAM_BOT_TOKEN не тронуты; VK_APP_ID обновлён.
    assert wiz.read_env_value(result, "VK_ACCESS_TOKEN") == ACCESS_TOKEN
    assert wiz.read_env_value(result, "TELEGRAM_BOT_TOKEN") == "keep-me"
    assert wiz.read_env_value(result, "VK_APP_ID") == wiz.VK_APP_ID_DEFAULT
    # Существующий group_id не перезаписан (updates его не содержит).
    assert "VK_DEFAULT_GROUP_ID" not in updates


def test_unreachable_tunnel_does_not_write_redirect() -> None:
    # Туннель не поднят/не проверен → обновлений нет, redirect не пишется.
    assert wiz.build_env_updates(None, SECRET, existing_group_id=None) is None
    assert wiz.build_env_updates("", SECRET, existing_group_id=None) is None


def test_report_masks_secret() -> None:
    values = wiz.build_redirect_values("https://calm-frog-1234.trycloudflare.com")
    report = wiz.build_report(values, secret_written=True)
    # Отчёт не содержит секрета (он в него и не передаётся).
    assert SECRET not in report
    assert "значение не показывается" in report
    assert "VK_LIVE_PUBLISHING_ENABLED=false" in report
    assert "publish-due не запускался" in report
    # redact_sensitive маскирует секреты/токены в произвольном тексте (логах).
    masked = wiz.redact_sensitive(f"VK_APP_SECRET={SECRET}\nVK_ACCESS_TOKEN={ACCESS_TOKEN}")
    assert SECRET not in masked and ACCESS_TOKEN not in masked


def test_cloudflared_failure_message_mentions_network_block() -> None:
    assert "Network blocks Cloudflare tunnel ports" in wiz.NETWORK_BLOCK_MESSAGE
    assert "VPN" in wiz.NETWORK_BLOCK_MESSAGE
    assert "mobile hotspot" in wiz.NETWORK_BLOCK_MESSAGE
    report = wiz.build_failure_report("cloudflared exited")
    assert wiz.NETWORK_BLOCK_MESSAGE in report
    assert "VK_OAUTH_REDIRECT_URI не записан" in report
    # Fallback-варианты присутствуют (ngrok / другой интернет / VPS).
    assert "ngrok" in report and "мобильную точку" in report


# --------------------------------------------------------------------------- #
# ngrok fallback                                                              #
# --------------------------------------------------------------------------- #

NGROK_LOG = (
    't=2026-01-01T00:00:00+0000 lvl=info msg="started tunnel" '
    "name=command_line addr=http://host.docker.internal:8000 "
    "url=https://1a2b-3c4d.ngrok-free.app"
)


def test_parse_ngrok_url() -> None:
    assert wiz.parse_ngrok_url(NGROK_LOG) == "https://1a2b-3c4d.ngrok-free.app"
    assert wiz.parse_ngrok_url("https://abcd.ngrok.io/health") == "https://abcd.ngrok.io"
    assert wiz.parse_ngrok_url("no ngrok url here") is None
    assert wiz.parse_ngrok_url("") is None


def test_ngrok_no_authtoken_message() -> None:
    # Понятное сообщение с командой export (без секретов).
    assert "NGROK_AUTHTOKEN не задан" in wiz.NGROK_TOKEN_MISSING_MESSAGE
    assert "export NGROK_AUTHTOKEN=" in wiz.NGROK_TOKEN_MISSING_MESSAGE
    # try_ngrok без токена не запускает Docker и возвращает это сообщение.
    monkey_env = {k: v for k, v in wiz.os.environ.items() if k != "NGROK_AUTHTOKEN"}
    saved = wiz.os.environ.get("NGROK_AUTHTOKEN")
    try:
        wiz.os.environ.pop("NGROK_AUTHTOKEN", None)
        url, reason = wiz.try_ngrok(1.0)
        assert url is None
        assert reason == wiz.NGROK_TOKEN_MISSING_MESSAGE
    finally:
        if saved is not None:
            wiz.os.environ["NGROK_AUTHTOKEN"] = saved
    assert "NGROK_AUTHTOKEN" not in monkey_env


def test_unreachable_ngrok_does_not_write_redirect() -> None:
    # ngrok не поднялся/не проверен (url=None) → обновлений .env нет.
    assert wiz.build_env_updates(None, SECRET, existing_group_id=None) is None


def test_successful_ngrok_redirect_values() -> None:
    ngrok_url = "https://1a2b-3c4d.ngrok-free.app"
    values = wiz.build_redirect_values(ngrok_url)
    assert values["domain"] == "1a2b-3c4d.ngrok-free.app"
    assert values["redirect_uri"] == f"{ngrok_url}/integrations/vk/oauth/callback"
    updates = wiz.build_env_updates(ngrok_url, secret=None, existing_group_id="240102732")
    assert updates is not None
    assert updates["VK_OAUTH_REDIRECT_URI"] == f"{ngrok_url}/integrations/vk/oauth/callback"
    assert updates["VK_LIVE_PUBLISHING_ENABLED"] == "false"
    assert "VK_APP_SECRET" not in updates  # секрет не передан → не пишется


def test_ngrok_authtoken_redacted_in_logs() -> None:
    log = f"NGROK_AUTHTOKEN={SECRET}\nstarting agent authtoken={SECRET} region=eu"
    masked = wiz.redact_sensitive(log)
    assert SECRET not in masked
    assert "authtoken=***" in masked or "NGROK_AUTHTOKEN=***" in masked
