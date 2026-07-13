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
    "/ui/projects/1/platforms/telegram",
    "/ui/projects/1/platforms/vk",
    "/ui/projects/1/platforms/instagram",
    "/ui/projects/1/platforms/yandex_disk",
    "/ui/projects/1/platforms/vk/schedule",
    "/ui/billing",
    "/ui/tariffs",
    "/ui/analytics",
    "/ui/settings",
    "/ui/guide",
    "/ui/guide/telegram",
    "/ui/guide/vk",
    "/ui/guide/instagram",
    "/ui/guide/yandex_disk",
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
    # Sidebar-разделы (autopilot-first, v0.5.6): Сегодня / Проекты / Аналитика / Оплата / Advanced.
    for path in ("/ui/projects", "/ui/tariffs", "/ui/analytics", "/ui/billing"):
        body = client.get(path).text
        for label in ("Сегодня", "Проекты", "Аналитика", "Оплата", "Настройки", "Advanced"):
            assert label in body, (path, label)


def test_botfleet_branding_and_logo(client: TestClient) -> None:
    # Бренд Botfleet и inline SVG-логотип присутствуют (без внешних CDN).
    for path in ("/ui/", "/ui/projects", "/ui/guide"):
        body = client.get(path).text
        assert "Botfleet" in body
        assert "brandlogo" in body  # класс inline SVG-логотипа
        assert "<svg" in body
        assert "cdn" not in body.lower()  # никаких внешних CDN


def test_theme_switcher_present(client: TestClient) -> None:
    # Переключатель темы: localStorage-ключ, data-theme, функции и метки light/dark.
    body = client.get("/ui/projects").text
    assert "botfleet_theme" in body
    assert "data-theme" in body
    assert "toggleTheme" in body and "applyTheme" in body
    assert "themebtn" in body
    assert "Светлая" in body
    assert "Тёмная" in body or "Темная" in body or "Ночь" in body


def test_dark_theme_css_variables_present(client: TestClient) -> None:
    body = client.get("/ui/projects").text
    assert 'data-theme="dark"' in body
    for var in ("--surface", "--surface-soft", "--text", "--accent-soft", "--input-bg", "--shadow"):
        assert var in body, var


def test_guide_page_content(client: TestClient) -> None:
    body = client.get("/ui/guide").text
    for marker in (
        "Botfleet",
        "Как подключиться к Botfleet",
        "Быстрый старт",
        "Telegram",
        "VK",
        "Яндекс Диск",
        "Расписание",
        "Безопасность",
    ):
        assert marker in body, marker


def test_guide_aliases_open(client: TestClient) -> None:
    for path in ("/ui/help", "/ui/onboarding-guide"):
        assert client.get(path).status_code == 200


def test_global_guide_is_overview_only(client: TestClient) -> None:
    # Общий /ui/guide — обзорный: содержит разделы и ссылки на платформенные гайды,
    # но НЕ содержит подробных инструкций (они переехали в разделы платформ).
    body = client.get("/ui/guide").text
    for marker in (
        "Botfleet",
        "Быстрый старт",
        "Telegram",
        "VK",
        "Яндекс Диск",
        "Расписание",
        "Безопасность",
        "units",
        "preview",
        "/ui/guide/telegram",
        "/ui/guide/vk",
        "/ui/guide/instagram",
    ):
        assert marker in body, marker
    # Подробные инструкции НЕ в общем гайде (они в разделах платформ).
    for deep in ("BotFather", "chat not found", "error 27", "Meta Developer"):
        assert deep not in body, deep


def test_platform_guide_pages_have_detailed_instructions(client: TestClient) -> None:
    tg = client.get("/ui/guide/telegram").text
    for m in ("BotFather", "chat not found", "getMe", "getChat", "getChatMember"):
        assert m in tg, m
    vk = client.get("/ui/guide/vk").text
    for m in ("error 27", "user-token", "публичный HTTPS-домен", "users.get", "groups.get"):
        assert m in vk, m
    ig = client.get("/ui/guide/instagram").text
    for m in (
        "Facebook Page",
        "Meta Developer",
        "Instagram API with Instagram Login",
        "публичный image_url",
        "accountquality",
    ):
        assert m in ig, m
    yd = client.get("/ui/guide/yandex_disk").text
    for m in ("HEIC", "root folder", "image_url"):
        assert m in yd, m


def test_platform_page_telegram_has_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    for m in ("BotFather", "chat not found", "Гайд подключения", "Расписание", "Обзор"):
        assert m in body, m


def test_platform_page_vk_has_oauth_and_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/vk").text
    # OAuth-подключение (перенесено с дашборда).
    assert "Подключить VK" in body
    assert "Проверить доступ" in body
    assert "/integrations/vk/oauth/start" in body
    assert "vkCheck(" in body
    assert "/integrations/vk/oauth/check" in body
    assert "Что вставить в VK ID" in body
    assert "Базовый домен" in body
    assert "OAuth App ID" in body
    assert "app.teeon.ru" in body
    # Гайд VK (error 27 / user-token / публичный HTTPS-домен).
    for m in ("error 27", "user-token", "публичный HTTPS-домен"):
        assert m in body, m


def test_platform_page_instagram_has_card_and_guide(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/instagram").text
    for marker in (
        "Instagram App ID",
        "Instagram App Secret",
        "Redirect URI",
        "Access Token",
        "Instagram User ID",
        "image_url",
        "live выключен",
        "Проверить настройки",
        "Скопировать Redirect URI",
        "Meta Developer",
        "Instagram API with Instagram Login",
        "Facebook Page",
    ):
        assert marker in body, marker
    assert "igCheck(" in body and "igCopyRedirect(" in body
    assert "INSTAGRAM_LIVE_PUBLISHING_ENABLED=true" not in body


def test_dashboard_is_clean_platform_grid(client: TestClient) -> None:
    # Дашборд — чистая сетка платформ без длинных инструкций.
    body = client.get("/ui/projects/1/dashboard").text
    assert "Платформы" in body
    assert "extra.platforms" in body
    assert "ptile" in body  # кликабельные карточки платформ
    assert "Создать платформу" in body
    assert "Создать расписание" in body
    # Кликабельная карточка ведёт на страницу платформы.
    assert "/ui/projects/${PID}/platforms/${encodeURIComponent(pt)}" in body
    # Длинные OAuth-инструкции убраны из дашборда (переехали на страницу VK).
    assert "Что вставить в VK ID" not in body
    assert "BotFather" not in body


def test_no_instagram_live_flag_enabled_in_ui(client: TestClient) -> None:
    # Ни на одной странице нет включённого флага живой публикации Instagram.
    for path in PAGES:
        assert "INSTAGRAM_LIVE_PUBLISHING_ENABLED=true" not in client.get(path).text


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


def test_vk_oauth_connect_ui_moved_off_dashboard(client: TestClient) -> None:
    # VK OAuth-подключение переехало с дашборда на страницу платформы VK (Part 1/2).
    dashboard = client.get("/ui/projects/1/dashboard").text
    assert "Что вставить в VK ID" not in dashboard
    # На странице платформы VK — полный OAuth-блок (проверяется отдельным тестом).
    vk_page = client.get("/ui/projects/1/platforms/vk").text
    assert "Подключить VK" in vk_page
    assert "/integrations/vk/oauth/start" in vk_page


def test_dashboard_has_no_secret_or_live_toggle(client: TestClient) -> None:
    from app.config import get_settings

    body = client.get("/ui/projects/1/dashboard").text
    # На дашборде нет глобального включателя VK live и нет publish-due.
    assert "VK_LIVE_PUBLISHING_ENABLED=true" not in body
    assert "publish-due" not in body and "publish_due" not in body
    # Значение секрета приложения VK не встраивается в страницу (имя-инструкция допустимо).
    secret = get_settings().vk_app_secret
    if secret:
        assert secret not in body


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
        settings.vk_app_secret,
        settings.instagram_access_token,
        settings.instagram_app_secret,
    ]
    for path in PAGES:
        text = client.get(path).text
        for secret in secrets:
            if secret:  # непустой реальный токен/секрет из окружения
                assert secret not in text  # секрет не попадает в HTML
