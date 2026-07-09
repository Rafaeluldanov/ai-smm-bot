"""Smoke-тесты SaaS личного кабинета v0.2.3 (offline, TestClient; без сети/секретов)."""

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
    "/ui/projects/1/platforms/vk/schedule",
    "/ui/billing",
    "/ui/tariffs",
    "/ui/analytics",
    "/ui/settings",
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


def test_sidebar_labels_present(client: TestClient) -> None:
    # Sidebar-разделы присутствуют на страницах кабинета.
    for path in ("/ui/projects", "/ui/tariffs", "/ui/analytics", "/ui/billing"):
        body = client.get(path).text
        for label in ("Проекты", "Тарифы", "Аналитика", "Настройки"):
            assert label in body, (path, label)


def test_account_dropdown_labels_present(client: TestClient) -> None:
    # Метки dropdown аккаунта рендерятся статически (JS лишь переключает видимость).
    for path in ("/ui/projects", "/ui/billing", "/ui/"):
        body = client.get(path).text
        assert "Пополнить счёт" in body
        assert "Выйти" in body
    # Гостю доступны кнопки входа/регистрации.
    login_page = client.get("/ui/login").text
    assert "Войти" in login_page
    assert "Регистрация" in login_page


def test_new_project_form_has_all_sections(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    for marker in (
        "company_name",
        "project_slug",
        "project_name",
        "kwtable",
        "media_sources",
        "platforms",
        "promotion_categories",
        "publishing_plans",
        "accept_terms",
    ):
        assert marker in body, marker


def test_new_project_bulk_keyword_import(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    assert "Вставьте ключевые запросы списком" in body
    assert "Разобрать ключи" in body
    # Импорт файла читается в браузере (FileReader), без загрузки на сервер.
    assert "FileReader" in body
    assert "accept='.txt,.csv'" in body
    # Эвристики продукта/технологии присутствуют.
    assert "kwHeuristics" in body
    assert "DTF-печать" in body


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


def test_no_enabled_live_toggle_and_no_auto_publish(client: TestClient) -> None:
    body = client.get("/ui/projects/new").text
    # auto_publish не предлагается в UI.
    assert "auto_publish" not in body
    # Нет включаемого чекбокса live: на форму всегда уходит live_enabled:false.
    assert "live_enabled:false" in body
    assert "live: выкл" in body
    assert "Живая публикация включается отдельно после проверки" in body
    # Нет активного (не-disabled) чекбокса live_enabled.
    assert "name='live_enabled' type='checkbox'" not in body


def test_schedule_planner_maps_to_publishing_plan(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram/schedule").text
    # Планировщик собирает publishing_plans с нужными полями.
    assert "publishing_plans" in body
    assert "posts_per_day" in body
    assert "Europe/Moscow" in body
    assert "semi_auto" in body
    assert "Без плана расписания бот ничего не публикует" in body
    # Платформа безопасно прокинута как JSON-строка.
    assert 'const PLATFORM="telegram"' in body


def test_dashboard_renders_platform_cards_section(client: TestClient) -> None:
    body = client.get("/ui/projects/1/dashboard").text
    assert "Платформы" in body
    assert "extra.platforms" in body  # карточки платформ из dashboard.extra
    assert "Next actions" in body


def test_dynamic_pages_escape_user_content(client: TestClient) -> None:
    # Пользовательские данные (имена/slug проектов и аккаунтов) экранируются перед
    # вставкой в innerHTML — защита от stored XSS.
    assert "function esc(" in client.get("/ui/projects").text
    for path in ("/ui/accounts", "/ui/projects", "/ui/projects/1/dashboard", "/ui/settings"):
        body = client.get(path).text
        assert "esc(" in body


def test_no_publish_due_in_ui(client: TestClient) -> None:
    # В UI нет действия/маршрута публикации по расписанию (publish-due).
    for path in PAGES:
        body = client.get(path).text
        assert "publish-due" not in body
        assert "publish_due" not in body


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
                assert secret not in text  # секрет не попадает в HTML
