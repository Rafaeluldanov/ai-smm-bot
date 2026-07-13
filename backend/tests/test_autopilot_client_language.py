"""Тесты клиентского языка (v0.5.6). Primary-страницы без технического жаргона; Advanced — можно."""

from fastapi.testclient import TestClient

# Технические термины, запрещённые на клиентских (primary) страницах.
_FORBIDDEN = (
    "worker",
    "schedule run",
    "media decision",
    "topic decision",
    "credentials",
    "dry-run",
    "fingerprint",
    "webhook",
)

_PRIMARY_PAGES = (
    "/ui/today",
    "/ui/projects/1/autopilot",
    "/ui/projects/1/autopilot/setup",
    "/ui/projects/1/autopilot/calendar",
    "/ui/projects/1/autopilot/media",
    "/ui/projects/1/autopilot/platforms",
    "/ui/projects/1/autopilot/rules",
)


def test_primary_pages_have_no_technical_jargon(client: TestClient) -> None:
    for page in _PRIMARY_PAGES:
        text = client.get(page).text.lower()
        for term in _FORBIDDEN:
            assert term not in text, f"{term!r} на клиентской странице {page}"


def test_advanced_may_contain_technical_terms(client: TestClient) -> None:
    # Advanced-страница — для продвинутых; технические ссылки/термины там допустимы.
    html = client.get("/ui/advanced").text
    assert "Advanced" in html
    # Advanced ссылается на технические разделы (webhook/доставка и т.п.).
    assert "/ui/notification-telegram" in html or "/ui/notification-delivery" in html
