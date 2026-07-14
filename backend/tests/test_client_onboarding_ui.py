"""Тесты UI мастера онбординга (v0.6.4). Рендер 5 шагов; без секретов."""

from fastapi.testclient import TestClient


def test_onboarding_page_renders(client: TestClient) -> None:
    r = client.get("/ui/onboarding")
    assert r.status_code == 200
    assert r.text.strip().startswith("<!doctype")
    assert "Запустите AI-автопилот за 5 минут" in r.text
    assert "Ваш бизнес" in r.text and "Где публиковать" in r.text


def test_onboarding_page_calls_api_not_flags(client: TestClient) -> None:
    body = client.get("/ui/onboarding").text
    assert "/onboarding/start" in body and "/onboarding/" in body
    # Никаких секретов/глобальных флагов в разметке.
    assert "live_publishing_enabled" not in body
    assert "api_key" not in body


def test_onboarding_page_has_five_steps(client: TestClient) -> None:
    body = client.get("/ui/onboarding").text
    assert all(f"ob-s{i}" in body for i in range(1, 6))
