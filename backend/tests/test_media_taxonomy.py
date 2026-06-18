"""Тесты словарей и правил анализа (media_taxonomy)."""

from app.services import media_taxonomy as tax


def test_normalize_text_strips_extension_and_separators() -> None:
    result = tax.normalize_text("Худи_с_шелкографией.JPG")
    assert result == "худи с шелкографией"
    assert ".jpg" not in result
    assert "_" not in result


def test_normalize_text_yo_to_e() -> None:
    assert tax.normalize_text("Чёрная-футболка.png") == "черная футболка"


def test_extract_hoodie() -> None:
    tags = tax.extract_keywords_by_taxonomy("Худи с карманом с шелкографией и жаккардами.jpg")
    assert tags["products"] == ["худи"]
    assert tags["technologies"] == ["шелкография"]
    assert "карман" in tags["details"]
    assert "жаккард" in tags["details"]
    assert "apparel" in tags["categories"]
    assert "branding" in tags["categories"]


def test_extract_tshirt_dtf() -> None:
    tags = tax.extract_keywords_by_taxonomy("Футболка белая DTF тираж 500.png")
    assert "футболка" in tags["products"]
    assert "dtf" in tags["technologies"]
    assert "белый" in tags["colors"]
    assert "партия" in tags["details"]  # "тираж" -> канонический detail "партия"


def test_extract_mug_uv() -> None:
    tags = tax.extract_keywords_by_taxonomy("Кружка с УФ печатью логотипа.jpg")
    assert "кружка" in tags["products"]
    assert "уф-печать" in tags["technologies"]
    assert "логотип" in tags["details"]
    assert "souvenirs" in tags["categories"]


def test_extract_diary_emboss_engraving() -> None:
    tags = tax.extract_keywords_by_taxonomy("Ежедневник с тиснением и гравировкой.jpg")
    assert "ежедневник" in tags["products"]
    assert "тиснение" in tags["technologies"]
    assert "гравировка" in tags["technologies"]


def test_build_topics_and_seo() -> None:
    tags = {"products": ["худи"], "technologies": ["шелкография"]}
    topics = tax.build_topics_from_tags(tags)
    seo = tax.build_seo_keywords_from_tags(tags)
    assert "худи с логотипом" in topics
    assert "шелкография на худи" in topics
    assert "корпоративный мерч" in topics
    assert "худи с логотипом на заказ" in seo
    assert "корпоративный мерч на заказ" in seo


def test_confidence_high_and_low() -> None:
    rich = {"products": ["худи"], "technologies": ["шелкография"], "details": ["карман"]}
    poor: dict[str, list[str]] = {"products": [], "technologies": []}
    assert tax.calculate_tag_confidence(rich) >= 0.35
    assert tax.calculate_tag_confidence(poor) == 0.0


def test_no_false_positive_for_polo_substring() -> None:
    # "поло" не должно ловиться в "наполовину".
    tags = tax.extract_keywords_by_taxonomy("Скидка наполовину баннер.jpg")
    assert "поло" not in tags["products"]
