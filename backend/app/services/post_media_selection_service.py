"""Подбор медиа-актива под тему поста.

Берёт уже одобренные медиа проекта и выбирает наиболее подходящее по тегам
(совпадение с кластером темы и словами заголовка). Внешние стоковые картинки
допускаются только при подтверждённой лицензии. Если подходящего медиа нет —
возвращается ``None`` и предупреждение (пост будет помечен ``needs_media``).

Без сети, AI и реального просмотра файлов — только данные из БД и правила.
"""

from sqlalchemy.orm import Session

from app.models.media_asset import MediaAsset
from app.models.topic import Topic
from app.repositories import media_asset_repository
from app.services.topic_taxonomy import normalize_topic_key

# Статусы медиа, пригодные к публикации.
_USABLE_STATUSES: set[str] = {"approved", "approved_video"}

# Группы тегов медиа, по которым ищем совпадение с темой.
_TAG_GROUPS: tuple[str, ...] = (
    "products",
    "technologies",
    "details",
    "categories",
    "use_cases",
    "topics",
)

# Минимальная длина слова заголовка, учитываемого при сопоставлении.
_MIN_TOKEN_LEN = 4


def _loose_match(left: str, right: str) -> bool:
    """Свободное совпадение тегов: учитывает множественное/единственное число."""
    if left == right:
        return True
    if len(left) >= 5 and len(right) >= 5 and left[:5] == right[:5]:
        return True
    return left in right or right in left


class PostMediaSelectionService:
    """Выбирает лучший одобренный медиа-актив под тему поста."""

    def select_media_for_topic(
        self, db: Session, topic: Topic
    ) -> tuple[MediaAsset | None, list[str]]:
        """Подобрать медиа под тему. Возвращает (актив|None, предупреждения)."""
        warnings: list[str] = []
        assets = media_asset_repository.list_media_assets_by_project(db, topic.project_id)
        usable = [asset for asset in assets if self._is_usable(asset)]
        if not usable:
            warnings.append("Нет одобренных медиа для проекта — пост помечен needs_media")
            return None, warnings

        cluster_key = normalize_topic_key(topic.cluster or "")
        title_tokens = self._title_tokens(topic.title)

        scored: list[tuple[int, MediaAsset]] = []
        for asset in usable:
            score = self._match_score(asset, cluster_key, title_tokens)
            if score > 0:
                scored.append((score, asset))

        if not scored:
            warnings.append(
                "Не нашлось медиа, подходящего по тегам темы — нужна досъёмка (needs_media)"
            )
            return None, warnings

        # Стабильная сортировка по убыванию очков сохраняет порядок по id среди равных.
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[0][1], warnings

    @staticmethod
    def _is_usable(asset: MediaAsset) -> bool:
        """Пригоден ли актив: только approved/approved_video и допустимая лицензия."""
        if asset.status not in _USABLE_STATUSES:
            return False
        if asset.source_type == "external_stock":
            license_type = (asset.license_type or "").lower()
            if not license_type or "review" in license_type or "needs" in license_type:
                return False
        return True

    @staticmethod
    def _title_tokens(title: str) -> list[str]:
        """Значимые слова заголовка (нормализованные, без коротких предлогов)."""
        return [
            token for token in normalize_topic_key(title).split() if len(token) >= _MIN_TOKEN_LEN
        ]

    @classmethod
    def _asset_tags(cls, asset: MediaAsset) -> set[str]:
        """Все теги актива из значимых групп (нормализованные)."""
        tags = asset.tags or {}
        values: set[str] = set()
        for group in _TAG_GROUPS:
            for value in tags.get(group, []) or []:
                values.add(normalize_topic_key(str(value)))
        return values

    @classmethod
    def _match_score(cls, asset: MediaAsset, cluster_key: str, title_tokens: list[str]) -> int:
        """Очки соответствия: кластер важнее, слова заголовка добавляют вес."""
        asset_tags = cls._asset_tags(asset)
        if not asset_tags:
            return 0
        score = 0
        if cluster_key and any(_loose_match(cluster_key, tag) for tag in asset_tags):
            score += 3
        for token in title_tokens:
            if any(_loose_match(token, tag) for tag in asset_tags):
                score += 2
        return score
