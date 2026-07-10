"""Тесты юридических страниц-черновиков и ссылок в UI."""

from fastapi.testclient import TestClient

_LEGAL = ("terms", "privacy", "offer", "payments")


def test_legal_pages_open_with_draft_warning(client: TestClient) -> None:
    for doc in _LEGAL:
        r = client.get(f"/ui/legal/{doc}")
        assert r.status_code == 200
        body = r.text
        assert "Черновик" in body
        assert "юридической консультацией" in body


def test_settings_has_legal_links(client: TestClient) -> None:
    body = client.get("/ui/settings").text
    for doc in _LEGAL:
        assert f"/ui/legal/{doc}" in body


def test_footer_has_legal_links(client: TestClient) -> None:
    body = client.get("/ui/projects").text
    assert "site-footer" in body
    for doc in _LEGAL:
        assert f"/ui/legal/{doc}" in body


def test_legal_pages_no_secrets(client: TestClient) -> None:
    for doc in _LEGAL:
        body = client.get(f"/ui/legal/{doc}").text
        assert "eyJ" not in body  # похоже на JWT
        assert "vk1." not in body and "EAAG" not in body
