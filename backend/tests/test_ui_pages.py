"""Smoke-тесты SaaS UI-страниц (offline, TestClient; без сети/секретов)."""

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

PAGES = [
    "/ui",
    "/ui/",
    "/ui/register",
    "/ui/login",
    "/ui/accounts",
    "/ui/projects",
    "/ui/projects/new",
    "/ui/projects/1/dashboard",
    "/ui/projects/1/settings",
    "/ui/billing",
]


@pytest.mark.parametrize("path", PAGES)
def test_ui_page_opens(client: TestClient, path: str) -> None:
    response = client.get(path)
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<html" in response.text.lower()


def test_auth_pages_have_forms(client: TestClient) -> None:
    assert "<form" in client.get("/ui/register").text
    assert "<form" in client.get("/ui/login").text


def test_new_project_form_has_all_sections(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    for marker in (
        "company_name",
        "project_slug",
        "project_name",
        "keywords",
        "media_sources",
        "platforms",
        "promotion_categories",
        "publishing_plans",
        "accept_terms",
    ):
        assert marker in body


def test_media_source_and_platform_options_present(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    for source in ("yandex_disk", "google_drive", "manual", "upload", "website", "other"):
        assert source in body
    for platform in ("vk", "telegram", "instagram", "youtube", "rutube"):
        assert platform in body


def test_api_key_is_password_input(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    # Секрет вводится как password и не автозаполняется.
    assert "name='api_key' type='password' autocomplete='off'" in body


def test_live_enabled_disabled_and_no_auto_publish(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    # auto_publish не предлагается в UI; режимы плана — без него.
    assert "auto_publish" not in body
    # live-чекбокс присутствует, но выключен (disabled).
    assert "live (выкл)" in body
    assert "disabled" in body


def test_dynamic_pages_escape_user_content(client: TestClient) -> None:
    # Пользовательские данные (имена/slug проектов и аккаунтов) экранируются перед
    # вставкой в innerHTML — защита от stored XSS.
    assert "function esc(" in client.get("/ui/projects").text
    for path in ("/ui/accounts", "/ui/projects", "/ui/projects/1/dashboard"):
        body = client.get(path).text
        assert "esc(" in body


def test_settings_page_seeds_form_rows(client: TestClient) -> None:
    # Страница настроек добавляет стартовые строки секций — форма пригодна к вводу.
    assert "forEach(addRow)" in client.get("/ui/projects/1/settings").text


def test_buildpayload_filters_untouched_select_rows(client: TestClient) -> None:
    # Незаполненные строки с select (media_sources/platforms/plans) не отправляются.
    body = client.get("/ui/projects/new").text
    assert "p.title||p.api_key||p.external_id" in body
    assert "m.title||m.url||m.root_folder" in body
    assert "p.category_title||p.platforms.length" in body


def test_ui_html_has_no_real_secrets(client: TestClient) -> None:
    settings = get_settings()
    secrets = [
        settings.telegram_bot_token,
        settings.vk_access_token,
        settings.instagram_access_token,
    ]
    for path in PAGES:
        text = client.get(path).text
        for secret in secrets:
            if secret:  # непустой реальный токен из окружения
                leaked = secret in text
                assert not leaked  # не печатаем секрет в сообщении об ошибке
