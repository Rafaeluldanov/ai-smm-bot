"""Подбор медиа-актива под тему поста.

Берёт уже одобренные медиа проекта и выбирает наиболее подходящее по тегам
(совпадение с кластером темы и словами заголовка). ПРИОРИТЕТ — собственные
медиа компании (``source_type=internal``, ``license_type=company_owned``); внешние
картинки (``external_stock``) и старые reference-материалы (метка
``external_reference`` в ``tags.categories``) используются ТОЛЬКО как fallback,
если своих подходящих медиа нет. Если подходящего медиа нет — возвращается
``None`` и предупреждение (пост будет помечен ``needs_media``).

Для батчевой генерации (weekly/autonomous) можно передать
``exclude_media_asset_ids``, чтобы распределять разные медиа между постами и не
ставить один и тот же актив во все посты подряд.

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

# Источник «собственных» медиа и метка внешнего reference-материала.
_PREFERRED_SOURCE_TYPE = "internal"
_EXTERNAL_REFERENCE = "external_reference"

# Бонусы/штрафы скоринга: свои медиа в приоритете, внешние — только fallback.
_BONUS_INTERNAL = 30
_BONUS_COMPANY_OWNED = 20
_BONUS_HIGH_CONFIDENCE = 10
_BONUS_NO_REVIEW = 5
_PENALTY_EXTERNAL_STOCK = 50
_PENALTY_EXTERNAL_REFERENCE = 80
_PENALTY_RESTRICTED_LICENSE = 20
_PENALTY_NEEDS_REVIEW = 10
_HIGH_CONFIDENCE_THRESHOLD = 0.5
_RESTRICTED_LICENSES: set[str] = {"external_needs_review", "commercial_use_required"}


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
        self,
        db: Session,
        topic: Topic,
        exclude_media_asset_ids: set[int] | None = None,
    ) -> tuple[MediaAsset | None, list[str]]:
        """Подобрать медиа под тему. Возвращает (актив|None, предупреждения).

        ``exclude_media_asset_ids`` — id уже использованных в этом прогоне активов;
        при наличии альтернатив выбирается другой актив (распределение по постам).
        Если все подходящие исключены — переиспользуется лучший (с предупреждением).
        """
        exclude = exclude_media_asset_ids or set()
        warnings: list[str] = []
        assets = media_asset_repository.list_media_assets_by_project(db, topic.project_id)
        usable = [asset for asset in assets if self._is_usable(asset)]
        if not usable:
            warnings.append("Нет одобренных медиа для проекта — пост помечен needs_media")
            return None, warnings

        cluster_key = normalize_topic_key(topic.cluster or "")
        title_tokens = self._title_tokens(topic.title)

        candidates = [
            asset for asset in usable if self._match_score(asset, cluster_key, title_tokens) > 0
        ]
        if not candidates:
            warnings.append(
                "Не нашлось медиа, подходящего по тегам темы — нужна досъёмка (needs_media)"
            )
            return None, warnings

        # ПРИОРИТЕТ: собственные internal-медиа без метки external_reference.
        # Внешние (external_stock / external_reference) — только если своих нет.
        preferred = [asset for asset in candidates if self._is_preferred(asset)]
        pool = preferred or candidates
        if not preferred:
            warnings.append(
                "Подходящих собственных медиа нет — использую внешнее изображение как fallback"
            )

        # Лучший по совокупному скору; среди равных — более свежий (больший id).
        ranked = sorted(
            pool,
            key=lambda asset: (self._total_score(asset, cluster_key, title_tokens), asset.id),
            reverse=True,
        )

        available = [asset for asset in ranked if asset.id not in exclude]
        if available:
            return available[0], warnings

        warnings.append(
            "Все подходящие медиа уже использованы — переиспользую лучшее (нужно больше фото)"
        )
        return ranked[0], warnings

    @classmethod
    def _is_preferred(cls, asset: MediaAsset) -> bool:
        """Собственный медиа-актив компании (internal, без метки external_reference)."""
        return asset.source_type == _PREFERRED_SOURCE_TYPE and not cls._is_external_reference(asset)

    @staticmethod
    def _is_external_reference(asset: MediaAsset) -> bool:
        """Есть ли метка ``external_reference`` в ``tags.categories``."""
        categories = (asset.tags or {}).get("categories") or []
        return any(_EXTERNAL_REFERENCE in str(value).lower() for value in categories)

    @staticmethod
    def _confidence(tags: dict[str, object]) -> float:
        try:
            return float(tags.get("confidence") or 0.0)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 0.0

    @classmethod
    def _total_score(cls, asset: MediaAsset, cluster_key: str, title_tokens: list[str]) -> int:
        """Совокупный скор: базовое совпадение по тегам + бонусы − штрафы."""
        score = cls._match_score(asset, cluster_key, title_tokens)
        tags = asset.tags or {}
        license_type = (asset.license_type or "").lower()
        needs_review = bool(tags.get("needs_review"))

        if asset.source_type == _PREFERRED_SOURCE_TYPE:
            score += _BONUS_INTERNAL
        if license_type == "company_owned":
            score += _BONUS_COMPANY_OWNED
        if cls._confidence(tags) >= _HIGH_CONFIDENCE_THRESHOLD:
            score += _BONUS_HIGH_CONFIDENCE
        if not needs_review:
            score += _BONUS_NO_REVIEW

        if asset.source_type == "external_stock":
            score -= _PENALTY_EXTERNAL_STOCK
        if cls._is_external_reference(asset):
            score -= _PENALTY_EXTERNAL_REFERENCE
        if license_type in _RESTRICTED_LICENSES:
            score -= _PENALTY_RESTRICTED_LICENSE
        if needs_review:
            score -= _PENALTY_NEEDS_REVIEW
        return score

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
