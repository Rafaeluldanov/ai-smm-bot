"""Группировка похожих медиа проекта и сборка поста по группе (v0.1.14).

Сценарий: синхронизированные и протегированные собственные медиа проекта
объединяются в группы по общему тегу (приоритет: продукты → технологии → темы →
категории → детали), из группы собирается черновик поста с SEO-ссылкой на сайт
проекта, а несколько фото уходят одним VK-постом (несколько вложений).

Строгий отбор (как в :mod:`seo_media_selection_service`), плюс поддержка видео:
- только ``source_type=internal`` и ``license_type=company_owned``;
- только ``status`` из {``approved``, ``approved_video``};
- исключаются ``external_reference`` / ``external_stock`` (по категориям/источнику);
- видео попадает в группу (по имени файла/тегам), но помечается как НЕ загружаемое
  в VK на этом этапе (кадры не извлекаются — TODO будущего этапа).

Файлы не скачиваются — работаем с метаданными БД. Если у актива есть одобренная
улучшенная копия (approved enhanced variant), для VK-загрузки предпочитается её
путь (``media_path``); оригинал не перезаписывается.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.post import Post
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    post_repository,
    project_repository,
)
from app.schemas.post import PostCreate
from app.services.post_text_helpers import build_hashtags, get_brand_name
from app.services.site_link_selection_service import select_site_link
from app.services.topic_taxonomy import normalize_topic_key
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

# Приоритет группировки: (группа тегов, тип группы для candidate.group_type).
_GROUP_PRIORITY: tuple[tuple[str, str], ...] = (
    ("products", "product"),
    ("technologies", "technology"),
    ("topics", "topic"),
    ("categories", "category"),
    ("details", "detail"),
)
_TAG_GROUPS: tuple[str, ...] = tuple(name for name, _ in _GROUP_PRIORITY)

_USABLE_STATUSES: frozenset[str] = frozenset({"approved", "approved_video"})
_OWN_SOURCE_TYPE = "internal"
_OWN_LICENSE = "company_owned"
_EXCLUDED_CATEGORIES: frozenset[str] = frozenset({"external_reference", "external_stock"})

_VIDEO_EXTENSIONS: frozenset[str] = frozenset({"mov", "mp4", "m4v", "avi", "mkv", "webm"})


def _extension(name: str) -> str:
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _is_video_name(name: str | None) -> bool:
    return bool(name) and _extension(name or "") in _VIDEO_EXTENSIONS


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


@dataclass
class MediaGroupCandidate:
    """Кандидат-группа похожих медиа проекта."""

    group_key: str
    # product | technology | topic | category | detail | mixed
    group_type: str
    matched_tags: list[str]
    media_asset_ids: list[int]
    image_count: int
    video_count: int
    score: float
    warnings: list[str] = field(default_factory=list)

    @property
    def media_count(self) -> int:
        return len(self.media_asset_ids)


@dataclass
class MediaGroupPostDraft:
    """Черновик поста, собранный из группы медиа (до сохранения в БД)."""

    title: str
    text: str
    primary_media_asset_id: int | None
    media_asset_ids: list[int]
    generation_notes: dict[str, object]
    warnings: list[str] = field(default_factory=list)


class MediaGroupingService:
    """Группирует собственные approved-медиа проекта и собирает по ним пост."""

    # --- Публичные методы ---

    def group_project_media(
        self,
        db: Session,
        project_slug: str,
        tag: str | None = None,
        max_groups: int = 10,
        limit_media: int = 5,
        include_videos: bool = True,
    ) -> list[MediaGroupCandidate]:
        """Собрать группы похожих медиа проекта.

        ``tag`` фильтрует активы по совпадению тега (с учётом словоформ). Пустой
        список — если подходящих собственных медиа нет. ProjectNotFoundError —
        если проекта нет.
        """
        project = project_repository.get_project_by_slug(db, project_slug)
        if project is None:
            raise ProjectNotFoundError(project_slug)

        wanted = normalize_topic_key(tag) if tag else None
        assets = media_asset_repository.list_media_assets_by_project(db, project.id)
        usable = [asset for asset in assets if self._is_usable(asset, include_videos)]

        buckets: dict[str, dict[str, object]] = {}
        for asset in usable:
            keyed = self._grouping_key(asset, wanted)
            if keyed is None:
                continue
            group_key, group_type = keyed
            bucket = buckets.setdefault(group_key, {"group_type": group_type, "assets": []})
            assets_list = bucket["assets"]
            assert isinstance(assets_list, list)
            assets_list.append(asset)

        candidates = [
            self._build_candidate(str(key), bucket, limit_media) for key, bucket in buckets.items()
        ]
        candidates.sort(key=lambda cand: (-cand.score, cand.group_key))
        return candidates[:max_groups]

    def build_post_draft_from_group(
        self, db: Session, project_slug: str, group_candidate: MediaGroupCandidate
    ) -> MediaGroupPostDraft:
        """Собрать черновик поста по группе медиа (текст, SEO-ссылка, notes)."""
        assets = [
            asset
            for asset in (
                media_asset_repository.get_media_asset_by_id(db, media_id)
                for media_id in group_candidate.media_asset_ids
            )
            if asset is not None
        ]

        media_files: list[dict[str, object]] = []
        primary_media_asset_id: int | None = None
        products: set[str] = set()
        technologies: set[str] = set()
        for asset in assets:
            media_path, media_source, media_kind = self._preferred_media(db, asset)
            media_files.append(
                {
                    "id": asset.id,
                    "file_name": asset.file_name,
                    "yandex_disk_path": asset.yandex_disk_path,
                    "media_path": media_path,
                    "media_source": media_source,
                    "media_kind": media_kind,
                }
            )
            if media_kind == "image" and primary_media_asset_id is None:
                primary_media_asset_id = asset.id
            for product in (asset.tags or {}).get("products") or []:
                products.add(str(product))
            for technology in (asset.tags or {}).get("technologies") or []:
                technologies.add(str(technology))

        if primary_media_asset_id is None and assets:
            # Группа без фото (только видео) — главный актив всё равно фиксируем.
            primary_media_asset_id = assets[0].id

        image_count = sum(1 for item in media_files if item["media_kind"] == "image")
        video_count = sum(1 for item in media_files if item["media_kind"] == "video")
        selected_for_vk_upload = image_count > 0

        title = self._build_title(group_candidate)
        text, text_warnings = self._build_text(
            project_slug, group_candidate, products, technologies, video_count
        )
        warnings = list(dict.fromkeys([*group_candidate.warnings, *text_warnings]))

        generation_notes: dict[str, object] = {
            "media_group_key": group_candidate.group_key,
            "media_group_tags": list(group_candidate.matched_tags),
            "media_asset_ids": [asset.id for asset in assets],
            "media_files": media_files,
            "media_count": len(media_files),
            "image_count": image_count,
            "video_count": video_count,
            "selected_for_vk_upload": selected_for_vk_upload,
            "warnings": warnings,
        }
        return MediaGroupPostDraft(
            title=title,
            text=text,
            primary_media_asset_id=primary_media_asset_id,
            media_asset_ids=[asset.id for asset in assets],
            generation_notes=generation_notes,
            warnings=warnings,
        )

    def create_post_from_media_group(
        self,
        db: Session,
        project_slug: str,
        group_candidate: MediaGroupCandidate,
        status: str = "needs_review",
    ) -> Post:
        """Создать пост по группе медиа и вернуть сохранённый Post."""
        project = project_repository.get_project_by_slug(db, project_slug)
        if project is None:
            raise ProjectNotFoundError(project_slug)

        draft = self.build_post_draft_from_group(db, project_slug, group_candidate)
        hashtags = build_hashtags(
            project.slug, group_candidate.group_key, "", list(group_candidate.matched_tags)
        )
        return post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                media_asset_id=draft.primary_media_asset_id,
                title=draft.title,
                telegram_text=draft.text,
                vk_text=draft.text,
                instagram_text=draft.text,
                hashtags=hashtags,
                seo_keywords=list(group_candidate.matched_tags),
                status=status,
                generation_notes=draft.generation_notes,
            ),
        )

    # --- Внутреннее: отбор и группировка ---

    def _is_usable(self, asset: MediaAsset, include_videos: bool) -> bool:
        """Собственный approved-актив компании, пригодный к публикации."""
        if asset.source_type != _OWN_SOURCE_TYPE:
            return False
        if (asset.license_type or "").lower() != _OWN_LICENSE:
            return False
        if asset.status not in _USABLE_STATUSES:
            return False
        categories = {str(value).lower() for value in (asset.tags or {}).get("categories") or []}
        if categories & _EXCLUDED_CATEGORIES:
            return False
        return include_videos or not _is_video_name(asset.file_name)

    @staticmethod
    def _grouping_key(asset: MediaAsset, wanted: str | None) -> tuple[str, str] | None:
        """Определить (group_key, group_type) актива по приоритету групп тегов."""
        tags = asset.tags or {}
        if wanted is not None:
            for group_name, group_type in _GROUP_PRIORITY:
                for value in tags.get(group_name) or []:
                    if _loose_match(wanted, normalize_topic_key(str(value))):
                        # Все совпавшие активы объединяем под тег-фильтр.
                        return wanted, group_type
            return None
        for group_name, group_type in _GROUP_PRIORITY:
            values = tags.get(group_name) or []
            if values:
                normalized = normalize_topic_key(str(values[0]))
                if normalized:
                    return normalized, group_type
        return None

    def _build_candidate(
        self, group_key: str, bucket: dict[str, object], limit_media: int
    ) -> MediaGroupCandidate:
        group_type = str(bucket["group_type"])
        members = bucket["assets"]
        assert isinstance(members, list)
        # Фото раньше видео (чтобы лимит не вытеснял загружаемые изображения), затем новее.
        ordered = sorted(members, key=lambda asset: (_is_video_name(asset.file_name), -asset.id))

        warnings: list[str] = []
        if len(ordered) > limit_media:
            warnings.append(f"Группа усечена до {limit_media} медиа из {len(ordered)}")
            ordered = ordered[:limit_media]

        image_count = sum(1 for asset in ordered if not _is_video_name(asset.file_name))
        video_count = len(ordered) - image_count
        if video_count:
            warnings.append(f"Видео в группе ({video_count}) не загружается в VK — будет пропущено")
        if image_count == 0:
            warnings.append("В группе нет фото — VK-пост уйдёт только текстом")

        matched_tags = self._common_tags(ordered, group_key)
        score = round(
            float(image_count) + 0.5 * float(video_count) + 0.1 * float(len(matched_tags)), 3
        )
        return MediaGroupCandidate(
            group_key=group_key,
            group_type=group_type,
            matched_tags=matched_tags,
            media_asset_ids=[asset.id for asset in ordered],
            image_count=image_count,
            video_count=video_count,
            score=score,
            warnings=warnings,
        )

    @staticmethod
    def _common_tags(members: Iterable[MediaAsset], group_key: str) -> list[str]:
        """Общие (пересечение) нормализованные теги группы + сам ключ группы."""
        sets: list[set[str]] = []
        for asset in members:
            tags = asset.tags or {}
            values: set[str] = set()
            for group_name in _TAG_GROUPS:
                for value in tags.get(group_name) or []:
                    values.add(normalize_topic_key(str(value)))
            sets.append(values)
        common = set.intersection(*sets) if sets else set()
        common.add(group_key)
        common.discard("")
        return sorted(common)

    # --- Внутреннее: сборка поста ---

    @staticmethod
    def _preferred_media(db: Session, asset: MediaAsset) -> tuple[str | None, str, str]:
        """Вернуть (media_path, media_source, media_kind) с учётом enhanced-копии."""
        variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(db, asset.id)
        if variant is not None and variant.output_path:
            kind = "video" if _is_video_name(Path(variant.output_path).name) else "image"
            return variant.output_path, "enhanced_variant", kind
        kind = "video" if _is_video_name(asset.file_name) else "image"
        return None, "original", kind

    @staticmethod
    def _build_title(group_candidate: MediaGroupCandidate) -> str:
        label = group_candidate.group_key.strip() or "медиа"
        return f"{label.capitalize()}: подборка медиа ({group_candidate.image_count} фото)"

    @staticmethod
    def _build_text(
        project_slug: str,
        group_candidate: MediaGroupCandidate,
        products: set[str],
        technologies: set[str],
        video_count: int,
    ) -> tuple[str, list[str]]:
        """Собрать текст поста с одной SEO-ссылкой на сайт проекта."""
        brand = get_brand_name(project_slug)
        label = group_candidate.group_key.strip() or "изделия"
        blocks = [
            f"{label.capitalize()} — подборка работ {brand}.",
            "Показываем изделия и варианты фирменного нанесения: подберём материал, "
            "технологию и тираж под задачу вашего бизнеса.",
        ]
        warnings: list[str] = []
        link = select_site_link(
            project_slug,
            title=label,
            products=sorted(products),
            technologies=sorted(technologies),
            tags={"products": sorted(products), "technologies": sorted(technologies)},
        )
        if link is not None:
            blocks.append(f"Подробнее и расчёт тиража: {link.url}")
        else:
            warnings.append("SEO-ссылка на сайт не подобрана — добавьте ссылку вручную")
        if video_count:
            warnings.append(
                "Видео не загружается в VK на этом этапе — в пост уйдут только фото и текст"
            )
        return "\n\n".join(blocks), warnings
