"""Тесты UI страницы Telegram runbook (v0.6.3). Рендер без секретов; клиентский язык."""

from fastapi.testclient import TestClient


def test_runbook_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/telegram-runbook")
    assert r.status_code == 200
    assert r.text.strip().startswith("<!doctype")
    assert "Запуск Telegram автопилота" in r.text
    assert "Готовность (checklist)" in r.text
    assert "тестовый production-пост" in r.text


def test_runbook_page_calls_api_not_flags(client: TestClient) -> None:
    body = client.get("/ui/projects/1/telegram-runbook").text
    assert "/telegram-runbook/check" in body
    assert "/telegram-runbook/publish-test" in body
    # Никаких секретов/глобальных флагов в разметке.
    assert "live_publishing_enabled" not in body
    assert "api_key" not in body


def test_subnav_has_runbook_link(client: TestClient) -> None:
    r = client.get("/ui/projects/1/telegram-live-rollout")
    assert r.status_code == 200
    assert "telegram-runbook" in r.text
