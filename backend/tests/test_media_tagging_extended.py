"""Тесты расширенного MediaTaggingService (Этап 3)."""

from app.services.media_tagging_service import MediaTaggingService

RICH_KEYS = {
    "products",
    "technologies",
    "details",
    "materials",
    "colors",
    "categories",
    "use_cases",
    "audiences",
    "topics",
    "seo_keywords",
    "matched_terms",
    "confidence",
    "needs_review",
    "review_reasons",
}


def test_rich_structure_present() -> None:
    tags = MediaTaggingService().analyze_file_name(
        "Худи с карманом с шелкографией и жаккардами.jpg"
    )
    assert RICH_KEYS.issubset(tags.keys())
    assert tags["products"] == ["худи"]
    assert tags["technologies"] == ["шелкография"]
    assert tags["needs_review"] is False
    assert tags["confidence"] >= 0.35


def test_tshirt_dtf_white() -> None:
    tags = MediaTaggingService().analyze_file_name("Футболка белая DTF тираж 500.png")
    assert "футболка" in tags["products"]
    assert "dtf" in tags["technologies"]
    assert "белый" in tags["colors"]
    assert "партия" in tags["details"]


def test_external_stock_needs_review() -> None:
    tags = MediaTaggingService().analyze_file_name(
        "стоковое фото.jpg", source_type="external_stock"
    )
    assert tags["needs_review"] is True
    assert any("прав" in reason.lower() for reason in tags["review_reasons"])
    assert "external_reference" in tags["categories"]


def test_low_confidence_needs_review() -> None:
    tags = MediaTaggingService().analyze_file_name("IMG_2024_random.jpg")
    assert tags["needs_review"] is True
    assert tags["confidence"] < 0.35


def test_external_path_needs_review() -> None:
    tags = MediaTaggingService().analyze_file_name(
        "Худи с шелкографией.jpg",
        yandex_disk_path="/SMM_BOT/01_TEEON/04_Внешние_картинки_из_интернета/h.jpg",
    )
    assert tags["needs_review"] is True
    assert "external_reference" in tags["categories"]
