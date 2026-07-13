"""Тесты UI календаря автопилота (v0.5.6). Простые варианты частоты, время, площадки, сохранение."""

from fastapi.testclient import TestClient


def test_calendar_frequency_options(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/calendar").text
    assert "Каждый день" in html
    assert "По будням" in html
    assert "3 раза в неделю" in html
    assert "Свои дни" in html


def test_calendar_save_button(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/calendar").text
    assert "Сохранить календарь" in html


def test_calendar_platforms_selector(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/calendar").text
    assert "cal-pf" in html
    assert "Telegram" in html and "VK" in html


def test_calendar_time_selector(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/calendar").text
    assert "cal-time" in html
    assert "по Москве" in html


def test_calendar_no_technical_jargon(client: TestClient) -> None:
    html = client.get("/ui/projects/1/autopilot/calendar").text.lower()
    for term in ("worker", "cron", "schedule run", "dry-run", "webhook"):
        assert term not in html
