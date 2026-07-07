"""Подбор собственного медиа проекта под продукт/технологию (Задача 7).

Строгий отбор для SEO-постов TEEON:
- только ``project_slug=teeon`` (или явно переданный проект);
- ``source_type=internal``;
- ``license_type=company_owned``;
- ``status`` из {``approved``, ``approved_video``};
- при наличии собственных фото исключаются материалы с меткой
  ``external_reference``;
- сопоставление по тегам продуктов/технологий.

Если у актива есть одобренная улучшенная копия (approved enhanced variant),
возвращается ``preferred_media_path`` (путь к улучшенному файлу). Файлы не
скачиваются — работаем только с метаданными БД.
"""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    project_repository,
)
from app.schemas.seo import SeoMediaCandidate
from app.services.topic_taxonomy import normalize_topic_key
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

_USABLE_STATUSES: set[str] = {"approved", "approved_video"}
_TAG_GROUPS: tuple[str, ...] = ("products", "technologies", "details", "topics", "categories")
_EXTERNAL_REFERENCE = "external_reference"
_OWN_SOURCE_TYPE = "internal"
_OWN_LICENSE = "company_owned"


def _normset(values: Iterable[str]) -> set[str]:
    return {normalize_topic_key(v) for v in values if v}


def _loose_match(left: str, right: str) -> bool:
    """Совпадение тегов с учётом числа/падежа (кепки↔кепка, футболки↔футболок)."""
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    common = 0
    for char_left, char_right in zip(left, right, strict=False):
        if char_left != char_right:
            break
        common += 1
    return common >= 4 and len(left) >= 4 and len(right) >= 4


class SeoMediaSelectionService:
    """Отбор собственных approved-медиа проекта под продукт/технологию."""

    def select_media(
        self,
        db: Session,
        project_slug: str,
        products: Iterable[str] = (),
        technologies: Iterable[str] = (),
        limit: int = 5,
    ) -> list[SeoMediaCandidate]:
        """Вернуть подходящие собственные медиа (внешние — не берём).

        ProjectNotFoundError, если проекта нет. Пустой список — если своего
        approved-медиа под запрос нет (нужна досъёмка).
        """
        project = project_repository.get_project_by_slug(db, project_slug)
        if project is None:
            raise ProjectNotFoundError(project_slug)

        wanted = _normset(products) | _normset(technologies)
        assets = media_asset_repository.list_media_assets_by_project(db, project.id)
        own = [asset for asset in assets if self._is_own_usable(asset)]

        matched = [asset for asset in own if not wanted or self._matched_tags(asset, wanted)]
        # Исключаем reference-материалы при наличии собственных не-reference фото.
        non_reference = [asset for asset in matched if not self._is_external_reference(asset)]
        pool = non_reference or matched
        pool.sort(key=lambda asset: asset.id, reverse=True)

        candidates: list[SeoMediaCandidate] = []
        for asset in pool[:limit]:
            path, source, variant_id = self._preferred_media(db, asset)
            candidates.append(
                SeoMediaCandidate(
                    media_asset_id=asset.id,
                    file_name=asset.file_name,
                    source_type=asset.source_type,
                    license_type=asset.license_type,
                    status=asset.status,
                    matched_tags=sorted(self._matched_tags(asset, wanted)) if wanted else [],
                    media_source=source,
                    preferred_media_path=path,
                    variant_id=variant_id,
                )
            )
        return candidates

    def select_best(
        self,
        db: Session,
        project_slug: str,
        products: Iterable[str] = (),
        technologies: Iterable[str] = (),
    ) -> SeoMediaCandidate | None:
        """Лучший (самый свежий) подходящий собственный медиа-актив или None."""
        candidates = self.select_media(db, project_slug, products, technologies, limit=1)
        return candidates[0] if candidates else None

    @staticmethod
    def _is_own_usable(asset: MediaAsset) -> bool:
        """Собственный медиа-актив компании, пригодный к публикации."""
        return (
            asset.source_type == _OWN_SOURCE_TYPE
            and (asset.license_type or "").lower() == _OWN_LICENSE
            and asset.status in _USABLE_STATUSES
        )

    @staticmethod
    def _is_external_reference(asset: MediaAsset) -> bool:
        categories = (asset.tags or {}).get("categories") or []
        return any(_EXTERNAL_REFERENCE in str(value).lower() for value in categories)

    @staticmethod
    def _asset_tags(asset: MediaAsset) -> set[str]:
        tags = asset.tags or {}
        values: set[str] = set()
        for group in _TAG_GROUPS:
            for value in tags.get(group, []) or []:
                values.add(normalize_topic_key(str(value)))
        return values

    @classmethod
    def _matched_tags(cls, asset: MediaAsset, wanted: set[str]) -> set[str]:
        asset_tags = cls._asset_tags(asset)
        matched: set[str] = set()
        for want in wanted:
            for tag in asset_tags:
                if _loose_match(want, tag):
                    matched.add(tag)
        return matched

    @staticmethod
    def _preferred_media(db: Session, asset: MediaAsset) -> tuple[str | None, str, int | None]:
        """Путь к улучшенной копии, если она одобрена; иначе — оригинал."""
        variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(db, asset.id)
        if variant is not None:
            return variant.output_path, "enhanced_variant", variant.id
        return None, "original", None
