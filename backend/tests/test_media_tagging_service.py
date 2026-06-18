"""Тесты сервиса тегирования медиафайлов."""

from app.services.media_tagging_service import MediaTaggingService


def test_extract_tags_hoodie_example() -> None:
    service = MediaTaggingService()
    tags = service.extract_tags_from_file_name("Худи с карманом с шелкографией и жаккардами.jpg")

    assert tags["products"] == ["худи"]
    assert tags["technologies"] == ["шелкография"]
    assert "карман" in tags["details"]
    assert "жаккард" in tags["details"]
    # Сервис также предлагает черновые темы на основе найденных тегов.
    assert "корпоративный мерч" in tags["topics"]


def test_extract_tags_no_keywords() -> None:
    service = MediaTaggingService()
    tags = service.extract_tags_from_file_name("IMG_1234.jpg")

    assert tags["products"] == []
    assert tags["technologies"] == []
    assert tags["details"] == []
    assert tags["topics"] == []
