"""Тесты UI Calendar Assistant (v0.5.8). Клиентский язык; кнопки; без техжаргона."""

from fastapi.testclient import TestClient

_URL = "/ui/projects/1/autopilot/calendar-assistant"


def test_page_renders(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Календарь автопостинга" in html
    assert "Botfleet сам будет писать текст" in html


def test_client_buttons(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Предварительный просмотр" in html
    assert "Создать календарь" in html
    assert "Применить к автопилоту" in html
    assert "Вернуться к автопилоту" in html


def test_goal_and_platforms(client: TestClient) -> None:
    html = client.get(_URL).text
    assert "Цель" in html
    assert "Telegram" in html and "VK" in html and "Instagram" in html


def test_no_technical_jargon(client: TestClient) -> None:
    html = client.get(_URL).text.lower()
    for term in (
        "worker",
        "schedule run",
        "dry-run",
        "dry_run",
        "credentials",
        "media decision",
        "topic decision",
        "webhook",
        "fingerprint",
    ):
        assert term not in html, term


def test_autopilot_page_links_assistant(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot").text
    assert "calendar-assistant" in html
    assert "Календарь автопостинга" in html
