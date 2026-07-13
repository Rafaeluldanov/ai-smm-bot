"""Тесты UI live-readiness (v0.5.9). Клиентский язык; подтверждения; без публикаций/токенов."""

from fastapi.testclient import TestClient

_URL = "/ui/projects/1/live-readiness"


def test_page_renders(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Готовность к реальной автопубликации" in html


def test_page_has_confirmations(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "ENABLE_LIVE_AUTOPILOT" in html
    assert "ENABLE_PLATFORM_LIVE" in html


def test_page_warns_about_global_flags(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "администратором" in html


def test_autopilot_page_links_readiness(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot").text
    assert "live-readiness" in html
    assert "Реальная публикация" in html


def test_no_publish_due_or_jargon(client: TestClient) -> None:
    html = client.get(_URL).text.lower()
    for term in ("publish-due", "publish_due", "live gate", "live-gate", "webhook", "dry-run"):
        assert term not in html, term
    assert "условия публикации" in html


def test_no_raw_tokens(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "api_key_encrypted" not in html
    assert "BOT_TOKEN" not in html
