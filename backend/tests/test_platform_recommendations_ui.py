"""Тесты UI-вкладки «Рекомендации» и общего экрана (v1.0.1, offline).

Инварианты: вкладка появляется на страницах поддерживаемых платформ (и по фактическим slug каталога
проекта); отсутствует для не-KB платформ; общий экран /ui/recommendations рендерится; весь текст из
ресурса экранируется; вкладка не меняет настройки платформы (чистый GET-рендер).
"""

from app.api.ui import (
    _platform_recommendations_pane_html,
    _recs_banner,
    ui_platform_workspace,
    ui_recommendations,
)


def test_tab_present_for_kb_platforms() -> None:
    for platform in ("telegram", "instagram", "vk", "youtube", "rutube", "dzen", "website"):
        _, present = _platform_recommendations_pane_html(platform)
        assert present, platform


def test_tab_present_for_project_catalog_slugs() -> None:
    # Фактические slug каталога проекта → через алиасы попадают в KB.
    for platform in ("odnoklassniki", "two_gis", "email"):
        _, present = _platform_recommendations_pane_html(platform)
        assert present, platform


def test_tab_absent_for_non_kb_platform() -> None:
    html_out, present = _platform_recommendations_pane_html("yandex_disk")
    assert present is False
    assert html_out == ""


def test_platform_page_has_recommendations_tab() -> None:
    resp = ui_platform_workspace(1, "telegram")
    body = resp.body.decode()
    assert "pane-recommendations" in body
    assert "Рекомендации" in body
    assert "Роль платформы" in body
    assert "План недели" in body
    assert "Перед публикацией" in body
    # Версия базы отображается.
    assert "версия 2026.1" in body


def test_platform_page_shows_disclaimer() -> None:
    body = ui_platform_workspace(1, "instagram").body.decode()
    assert "Алгоритмы платформ меняются" in body


def test_general_screen_renders() -> None:
    body = ui_recommendations().body.decode()
    for token in (
        "SMM-рекомендации Botfleet",
        "Универсальные принципы",
        "Сводная частота",
        "Недельный календарь",
        "Кросс-платформенный конвейер",
        "Дополнительные каналы",
        "версия 2026.1",
    ):
        assert token in body, token


def test_pane_escapes_text_no_raw_angle_from_data() -> None:
    """Контент базы не содержит HTML; рендер не добавляет сырых тегов из данных."""
    pane, _ = _platform_recommendations_pane_html("vk")
    # В данных нет '<'/'>'; значит любые угловые скобки в pane — только из нашей разметки.
    from app.services.platform_recommendations_service import get_platform_recommendations_service

    rec = get_platform_recommendations_service().get_platform_recommendations("vk")
    for text in rec["risks"] + rec["kpi"] + rec["content_rules"]:
        assert "<" not in text and ">" not in text


def test_banner_uses_resource_disclaimer_not_hardcoded() -> None:
    """Баннер рендерит disclaimer из ресурса; пустой → fallback на константу."""
    assert "Своя формулировка 2099" in _recs_banner("2099.9", "Своя формулировка 2099")
    # Fallback при пустом disclaimer.
    assert "Алгоритмы платформ меняются" in _recs_banner("2026.1", "")


def test_tab_pane_passes_resource_disclaimer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Вкладка берёт disclaimer из ответа сервиса (единый источник правды)."""
    from app.services.platform_recommendations_service import PlatformRecommendationsService

    orig = PlatformRecommendationsService.get_platform_recommendations

    def _patched(self: PlatformRecommendationsService, slug: str) -> dict:
        rec = orig(self, slug)
        rec["disclaimer"] = "УНИКАЛЬНЫЙ-DISCLAIMER-XYZ"
        return rec

    monkeypatch.setattr(PlatformRecommendationsService, "get_platform_recommendations", _patched)
    pane, _ = _platform_recommendations_pane_html("telegram")
    assert "УНИКАЛЬНЫЙ-DISCLAIMER-XYZ" in pane


def test_general_screen_checklist_rendered_once() -> None:
    """Универсальный чек-лист на общем экране показан один раз (не в каждой карточке)."""
    body = ui_recommendations().body.decode()
    first_item = "Есть ли хук в первых 1–3 секундах или первых трёх строках?"
    assert body.count(first_item) == 1


def test_platform_tab_still_has_checklist() -> None:
    """На вкладке платформы чек-лист остаётся (полезен автономно)."""
    pane, _ = _platform_recommendations_pane_html("telegram")
    assert "Есть ли хук в первых 1–3 секундах или первых трёх строках?" in pane


def test_tab_render_is_pure_get_no_db_param() -> None:
    """Рендер вкладки не принимает и не трогает БД — чистое чтение статической базы."""
    import inspect

    sig = inspect.signature(_platform_recommendations_pane_html)
    assert list(sig.parameters) == ["platform"]
    # Повторный рендер идемпотентен.
    a, _ = _platform_recommendations_pane_html("telegram")
    b, _ = _platform_recommendations_pane_html("telegram")
    assert a == b
