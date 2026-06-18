"""Тесты таксономии форматов постов."""

import pytest

from app.services.post_template_taxonomy import (
    get_available_formats,
    get_template_for_format,
    infer_format_from_topic,
)


def test_available_formats() -> None:
    formats = get_available_formats()
    assert set(formats) == {"expert", "product", "technology", "case", "faq", "selling"}


def test_template_for_format_has_structure() -> None:
    template = get_template_for_format("expert")
    assert template["structure"] == ["hook", "explanation", "practical_value", "soft_cta"]
    assert template["cta_type"] == "soft"
    assert template["purpose"]
    assert template["tone"]


def test_template_for_unknown_format_raises() -> None:
    with pytest.raises(ValueError, match="Неизвестный формат"):
        get_template_for_format("totally-unknown")


def test_infer_uses_recommended_first() -> None:
    fmt = infer_format_from_topic("Футболки с логотипом на заказ", "футболки", ["product", "case"])
    assert fmt == "product"


def test_infer_technology_by_keyword() -> None:
    assert infer_format_from_topic("Шелкография на футболках", "шелкография") == "technology"


def test_infer_expert_by_keyword() -> None:
    assert infer_format_from_topic("Как выбрать ткань для футболок", "футболки") == "expert"


def test_infer_default_product() -> None:
    assert infer_format_from_topic("Футболки с логотипом на заказ", "футболки") == "product"
