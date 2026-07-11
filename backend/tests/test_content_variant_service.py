"""Тесты сервиса генерации вариантов (v0.4.2, чистый — без БД)."""

from app.services.content_variant_service import ContentVariantService


def _svc() -> ContentVariantService:
    return ContentVariantService()


def test_generates_two_variants() -> None:
    vs = _svc().generate_text_variants("Базовый текст.", "Футболки", None, 2)
    assert len(vs) == 2
    assert {v["variant_key"] for v in vs} == {"A", "B"}


def test_generates_three_variants() -> None:
    vs = _svc().generate_text_variants("Базовый текст.", "Футболки", None, 3)
    assert len(vs) == 3
    assert [v["variant_key"] for v in vs] == ["A", "B", "C"]


def test_stronger_cta_variant_differs_from_baseline() -> None:
    vs = _svc().generate_text_variants("Футболки с логотипом для команды.", "Футболки", None, 2)
    assert vs[0]["text"] != vs[1]["text"]
    assert vs[0]["cta_type"] != vs[1]["cta_type"]


def test_short_direct_variant_differs() -> None:
    vs = _svc().generate_text_variants(
        "Длинный базовый текст поста про футболки для мероприятий.", "Футболки", None, 3
    )
    assert vs[2]["text_length_type"] == "short"
    assert vs[2]["text"] != vs[0]["text"]


def test_no_empty_variants() -> None:
    vs = _svc().generate_text_variants(None, "Тема", None, 3)
    assert all(v["text"].strip() for v in vs)


def test_respects_rejected_cta() -> None:
    profile = {"rejected_cta": ["Оставьте заявку — рассчитаем стоимость."]}
    vs = _svc().generate_text_variants(None, "Тема", profile, 3)
    for v in vs:
        assert "Оставьте заявку — рассчитаем стоимость." not in v["text"]


def test_all_cta_rejected_returns_no_rejected_cta() -> None:
    from app.services.content_variant_service import _CTA_TEMPLATES

    profile = {"rejected_cta": list(_CTA_TEMPLATES.values())}
    vs = _svc().generate_text_variants("Базовый текст.", "Тема", profile, 3)
    rejected = {c.lower() for c in _CTA_TEMPLATES.values()}
    for v in vs:
        # cta_text не должен быть одним из отклонённых шаблонов.
        assert str(v.get("cta_text", "")).lower() not in rejected or v["cta_text"] == ""
        assert v["text"].strip()  # вариант не пустой


def test_respects_forbidden_patterns() -> None:
    profile = {"forbidden_patterns": ["бесплатно"]}
    vs = _svc().generate_text_variants("Раздаём бесплатно всем!", "Тема", profile, 2)
    for v in vs:
        assert "бесплатно" not in v["text"].lower()


def test_variant_diff_summary() -> None:
    vs = _svc().generate_text_variants("Базовый текст поста.", "Тема", None, 2)
    diff = _svc().summarize_variant_diff(vs[0], vs[1])
    assert diff["cta_changed"] is True
    assert diff["text_changed"] is True


def test_cta_variants_prefer_client() -> None:
    profile = {"preferred_cta": ["Заказать со скидкой"]}
    ctas = _svc().generate_cta_variants(profile, "Тема")
    assert ctas[0] == "Заказать со скидкой"


def test_angle_variants_nonempty() -> None:
    angles = _svc().generate_angle_variants("Футболки", None)
    assert len(angles) >= 4
    assert all(a["lead"] for a in angles)
