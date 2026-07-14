"""Тесты UI страницы мониторинга live-автопилота (v0.6.1). Рендер без секретов; клиентский язык."""

from fastapi.testclient import TestClient


def test_monitoring_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/live-autopilot-monitoring")
    assert r.status_code == 200
    assert r.text.strip().startswith("<!doctype")
    # Клиентский заголовок и ключевые блоки присутствуют.
    assert "Мониторинг автопилота" in r.text
    assert "Стоп-кран автопилота" in r.text
    assert "Инциденты" in r.text


def test_monitoring_page_calls_api_not_flags(client: TestClient) -> None:
    r = client.get("/ui/projects/1/live-autopilot-monitoring")
    body = r.text
    # Страница обращается к API мониторинга и стоп-крана.
    assert "/live-autopilot-monitoring/projects/" in body
    assert "/pause" in body and "/resume" in body
    # Страница не встраивает секретов и не трогает глобальные флаги.
    assert "live_publishing_enabled" not in body
    assert "api_key" not in body


def test_subnav_has_monitoring_link(client: TestClient) -> None:
    # На соседней странице автопилота в подменю есть ссылка на мониторинг.
    r = client.get("/ui/projects/1/telegram-live-rollout")
    assert r.status_code == 200
    assert "live-autopilot-monitoring" in r.text
