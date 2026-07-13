"""Тесты UI Telegram live rollout (v0.6.0). Клиентский язык; подтверждение; без токенов/жаргона."""

from fastapi.testclient import TestClient

_URL = "/ui/projects/1/telegram-live-rollout"


def test_page_renders(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Telegram: первый live-канал автопилота" in html


def test_page_has_confirmation(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "ENABLE_TELEGRAM_LIVE" in html


def test_page_shows_statuses(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Условия публикации" in html
    assert "Live для проекта" in html
    assert "Live для Telegram" in html
    assert "Full-auto live" in html


def test_live_readiness_links_rollout(client: TestClient) -> None:
    html = client.get("/ui/projects/1/live-readiness").text
    assert "telegram-live-rollout" in html


def test_autopilot_links_rollout(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot").text
    assert "telegram-live-rollout" in html
    assert "Telegram live" in html


def test_no_raw_token(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "api_key_encrypted" not in html
    assert "BOT_TOKEN" not in html


def test_no_publish_due_or_jargon(client: TestClient) -> None:
    html = client.get(_URL).text.lower()
    for term in ("publish-due", "publish_due", "webhook", "dry-run"):
        assert term not in html, term
