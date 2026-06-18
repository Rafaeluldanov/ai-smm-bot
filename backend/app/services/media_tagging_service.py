"""Сервис тегирования медиафайлов.

Разбирает имя файла (и путь/источник) по словарям предметной области из
``media_taxonomy`` и формирует богатую структуру тегов. Реальный анализ
изображений (vision/AI) не выполняется — это задача следующих этапов.

Совместимость: ``extract_tags_from_file_name`` сохраняет прежнее поведение
для продуктов/технологий/деталей/тем (старые тесты продолжают проходить),
но возвращает расширенную структуру.
"""

from typing import Any

from app.services import media_taxonomy

# Маркер папки внешних картинок (для needs_review).
_EXTERNAL_FOLDER_MARKER = "04_Внешние_картинки_из_интернета"
_CONFIDENCE_REVIEW_THRESHOLD = 0.35


class MediaTaggingService:
    """Извлекает структурированные теги из метаданных медиафайла."""

    def analyze_file_name(
        self,
        file_name: str,
        project_slug: str | None = None,
        yandex_disk_path: str | None = None,
        source_type: str | None = None,
    ) -> dict[str, Any]:
        """Разобрать имя файла с учётом проекта, пути и источника.

        Возвращает структуру с тегами, темами, SEO, уверенностью и флагом
        необходимости ручной проверки (``needs_review``).
        """
        base = media_taxonomy.extract_keywords_by_taxonomy(file_name)

        categories = list(base["categories"])
        is_external = source_type == "external_stock" or (
            yandex_disk_path is not None and _EXTERNAL_FOLDER_MARKER in yandex_disk_path
        )
        if is_external and "external_reference" not in categories:
            categories.append("external_reference")

        tags: dict[str, Any] = {
            "products": base["products"],
            "technologies": base["technologies"],
            "details": base["details"],
            "materials": base["materials"],
            "colors": base["colors"],
            "categories": categories,
            "use_cases": base["use_cases"],
            "audiences": base["audiences"],
        }
        tags["topics"] = media_taxonomy.build_topics_from_tags(tags, project_slug)
        tags["seo_keywords"] = media_taxonomy.build_seo_keywords_from_tags(tags, project_slug)
        tags["matched_terms"] = base["matched_terms"]

        confidence = media_taxonomy.calculate_tag_confidence(tags)
        tags["confidence"] = confidence

        review_reasons = self._build_review_reasons(tags, confidence, source_type, yandex_disk_path)
        tags["needs_review"] = bool(review_reasons)
        tags["review_reasons"] = review_reasons
        return tags

    @staticmethod
    def _build_review_reasons(
        tags: dict[str, Any],
        confidence: float,
        source_type: str | None,
        yandex_disk_path: str | None,
    ) -> list[str]:
        reasons: list[str] = []
        if confidence < _CONFIDENCE_REVIEW_THRESHOLD:
            reasons.append("Низкая уверенность тегирования (confidence < 0.35)")
        if not tags["products"] and not tags["technologies"]:
            reasons.append("Не распознаны ни изделие, ни технология")
        if source_type == "external_stock":
            reasons.append("Внешний сток — требуется проверка прав/лицензии")
        if yandex_disk_path is not None and _EXTERNAL_FOLDER_MARKER in yandex_disk_path:
            reasons.append("Файл из папки внешних картинок из интернета")
        return reasons

    def extract_tags_from_file_name(self, file_name: str) -> dict[str, Any]:
        """Разобрать имя файла (совместимый интерфейс прежних этапов)."""
        return self.analyze_file_name(file_name)

    def suggest_content_topics(
        self, tags: dict[str, Any], project_slug: str | None = None
    ) -> list[str]:
        """Предложить темы публикаций на основе тегов."""
        return media_taxonomy.build_topics_from_tags(tags, project_slug)

    def suggest_seo_keywords(
        self, tags: dict[str, Any], project_slug: str | None = None
    ) -> list[str]:
        """Предложить SEO-ключевые слова на основе тегов."""
        return media_taxonomy.build_seo_keywords_from_tags(tags, project_slug)
