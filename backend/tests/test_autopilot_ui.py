"""Тесты UI автопилота (v0.5.6). Страницы рендерятся; клиентский язык; sidebar упрощён; Advanced."""

from fastapi.testclient import TestClient


def test_today_renders(client: TestClient) -> None:
    r = client.get("/ui/today")
    assert r.status_code == 200
    assert "Сегодня" in r.text


def test_autopilot_page_renders(client: TestClient) -> None:
    r = client.get("/ui/projects/1/autopilot")
    assert r.status_code == 200
    assert "Автопостинг работает сам" in r.text
    assert "Запустить автопилот" in r.text
    assert "Яндекс Диск" in r.text
    assert "Календарь" in r.text
    assert "сам пишет" in r.text or "Пишет текст" in r.text


def test_sub_pages_render(client: TestClient) -> None:
    for suffix in ("setup", "calendar", "media", "platforms", "rules"):
        r = client.get(f"/ui/projects/1/autopilot/{suffix}")
        assert r.status_code == 200, suffix


def test_sidebar_simplified_and_advanced(client: TestClient) -> None:
    html = client.get("/ui/today").text
    assert "/ui/today" in html
    assert "/ui/advanced" in html
    # Advanced page exists.
    assert client.get("/ui/advanced").status_code == 200


def test_advanced_page_lists_complex_sections(client: TestClient) -> None:
    html = client.get("/ui/advanced").text
    assert "Эксперименты" in html
    assert "/ui/experiments" in html


def test_bottom_nav_present(client: TestClient) -> None:
    html = client.get("/ui/today").text
    assert "bnav" in html


def test_no_raw_tokens_no_publish_due(client: TestClient) -> None:
    for p in (
        "/ui/today",
        "/ui/projects/1/autopilot",
        "/ui/projects/1/autopilot/media",
        "/ui/projects/1/autopilot/calendar",
    ):
        html = client.get(p).text
        assert "publish-due" not in html
        assert "publish_due" not in html
        assert "api_key_encrypted" not in html
        assert "NOTIFICATION_TELEGRAM_BOT_TOKEN" not in html


def test_project_dashboard_leads_to_autopilot(client: TestClient) -> None:
    html = client.get("/ui/projects/1/dashboard").text
    assert "/ui/projects/1/autopilot" in html
    assert "Открыть автопилот" in html
