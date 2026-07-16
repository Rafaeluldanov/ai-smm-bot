"""Тесты содержимого базы SMM-рекомендаций Botfleet (v1.0.1, offline).

Смысловые инварианты: у всех платформ есть role/frequency/KPI; частоты соответствуют спецификации;
точные проценты поданы как «практический ориентир», а не официальная гарантия платформы.
"""

from app.services.platform_recommendations_service import get_platform_recommendations_service

_SVC = get_platform_recommendations_service()

# Ожидаемые ключевые формулировки частоты по платформам (canonical slug → подстрока).
_FREQUENCY_NEEDLE = {
    "instagram": "3–5",
    "telegram": "1–2 поста в день",
    "vk": "3–5 постов в неделю",
    "youtube": "1 в неделю",
    "rutube": "1–2 видео в неделю",
    "dzen": "2–3 статьи в неделю",
    "ok": "4–5",
    "email": "1 письмо в неделю",
}


def test_all_platforms_have_role() -> None:
    for p in _SVC.list_platforms():
        assert p["role"].strip(), p["slug"]


def test_all_platforms_have_frequency_or_event_marker() -> None:
    for p in _SVC.list_platforms():
        rec = _SVC.get_platform_recommendations(p["slug"])
        freq = " | ".join(rec["frequency"]) + " | " + rec["frequency_summary"]
        assert rec["frequency"], p["slug"]
        # website/2gis — «по событию»; остальные — конкретная частота.
        if p["slug"] in {"website", "2gis"}:
            assert "по событию" in freq.lower(), p["slug"]


def test_all_platforms_have_kpi() -> None:
    for p in _SVC.list_platforms():
        rec = _SVC.get_platform_recommendations(p["slug"])
        assert rec["kpi"], p["slug"]


def test_frequency_matches_spec() -> None:
    for slug, needle in _FREQUENCY_NEEDLE.items():
        rec = _SVC.get_platform_recommendations(slug)
        blob = " | ".join(rec["frequency"]) + " | " + rec["frequency_summary"]
        assert needle in blob, (slug, blob)


def test_instagram_reels_frequency() -> None:
    rec = _SVC.get_platform_recommendations("instagram")
    assert any("Reels" in f and "3–5" in f for f in rec["frequency"])


def test_percentages_are_practical_guidelines() -> None:
    """Проценты штрафов/охватов поданы как ориентир, не как гарантия платформы."""
    vk = _SVC.get_platform_recommendations("vk")
    penalty_lines = [r for r in vk["risks"] if "%" in r]
    assert penalty_lines
    for line in penalty_lines:
        assert "ориентир" in line.lower(), line
    # Instagram: «10 репостов» — практический ориентир.
    ig = _SVC.get_platform_recommendations("instagram")
    assert any("ориентир" in r.lower() and "репост" in r.lower() for r in ig["risks"])


def test_no_official_platform_guarantee_wording() -> None:
    uni = _SVC.get_universal_recommendations()
    blob = repr(_SVC.load_knowledge_base()).lower() + repr(uni).lower()
    assert "официально подтверждено платформой" not in blob


def test_universal_and_checklist_counts() -> None:
    uni = _SVC.get_universal_recommendations()
    assert len(uni["universal_principles"]) == 8
    assert len(uni["pre_publish_checklist"]) == 8


def test_weekly_rhythm_has_seven_days() -> None:
    uni = _SVC.get_universal_recommendations()
    for slug, row in uni["weekly_rhythm"]["platforms"].items():
        assert len(row) == 7, slug
