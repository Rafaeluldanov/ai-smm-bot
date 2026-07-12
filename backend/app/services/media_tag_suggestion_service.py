"""Предложение тегов медиа без внешнего AI (media tag suggestion) — v0.4.8.

Правило-ориентированное предложение тегов из имени файла, существующих тегов, canonical-медиа
дубля, CRM-категорий/ключей/приоритетов, learning profile и недавних media decisions. Никаких
внешних AI/vision-вызовов; ничего не пишет; строго per-project; без путей/секретов в ответе.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.repositories import (
    media_asset_repository,
    media_duplicate_cluster_repository,
    schedule_media_decision_repository,
)

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.client_learning_service import ClientLearningService

logger = get_logger(__name__)

# MVP-словари классификации тегов (без внешнего AI).
_PRODUCT_TAGS = frozenset(
    {"футболка", "худи", "свитшот", "лонгслив", "поло", "жилет", "сумка", "кепка", "кружка"}
)
_TECHNOLOGY_TAGS = frozenset(
    {"вышивка", "шелкография", "dtf", "dtg", "уф", "гравировка", "тампопечать", "жаккард"}
)
_TAG_GROUPS = ("products", "technologies", "details", "categories", "use_cases", "topics")
_STOPWORDS = frozenset({"img", "photo", "image", "foto", "jpg", "jpeg", "png", "heic", "final"})


class MediaTagSuggestionService:
    """Правило-ориентированное предложение тегов медиа (без внешнего AI, без записи)."""

    def __init__(
        self,
        learning_service: ClientLearningService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._learning = learning_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Публичные методы                                                    #
    # ------------------------------------------------------------------ #

    def suggest_tags_for_asset(
        self, db: Session, project_id: int, media_asset_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Предложить теги для медиа из безопасных локальных источников (без AI)."""
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            return self.build_tag_suggestion_payload({}, set())

        signals: dict[str, set[str]] = {}
        existing = _asset_tag_set(asset)

        # 1) Имя файла.
        fn_tokens = {self.normalize_tag(t) for t in self.split_file_name_to_tokens(asset.file_name)}
        if fn_tokens:
            signals["file_name"] = fn_tokens
        # 2) Существующие теги.
        if existing:
            signals["existing_tags"] = existing
        # 3) Canonical-медиа дубля.
        cluster = media_duplicate_cluster_repository.find_cluster_for_media_asset(
            db, project_id, media_asset_id
        )
        if cluster is not None and cluster.canonical_media_asset_id:
            canon = media_asset_repository.get_media_asset_by_id(
                db, cluster.canonical_media_asset_id
            )
            if canon is not None and canon.id != media_asset_id:
                signals["duplicate_canonical"] = _asset_tag_set(canon)
        # 4-6) CRM: категория media_tags / product/technology priorities / keywords.
        crm_signals = self._crm_signals(db, project_id)
        signals.update({k: v for k, v in crm_signals.items() if v})
        # 7) Learning: high-performing/preferred теги.
        if self._use_learning():
            summary = self._learning_svc().summarize_learning(db, project_id, platform_key)
            high = {
                self.normalize_tag(t)
                for t in (summary.get("high_performing_tags", []) or [])
                + (summary.get("preferred_media_types", []) or [])
            }
            if high:
                signals["high_performing_tags"] = high
        # 8) Недавние media decisions.
        recent = self._recent_decision_tags(db, project_id)
        if recent:
            signals["learning_profile"] = recent

        return self.build_tag_suggestion_payload(signals, existing)

    def suggest_tags_for_cluster(
        self, db: Session, project_id: int, duplicate_cluster_id: int
    ) -> dict[str, Any]:
        """Предложить теги для кластера дублей (canonical + общие теги участников + имена)."""
        cluster = media_duplicate_cluster_repository.get_by_id(db, duplicate_cluster_id)
        if cluster is None or cluster.project_id != project_id:
            return self.build_tag_suggestion_payload({}, set())
        signals: dict[str, set[str]] = {}
        member_tag_sets: list[set[str]] = []
        fn_tokens: set[str] = set()
        canonical_existing: set[str] = set()
        for mid in cluster.member_media_asset_ids or []:
            asset = media_asset_repository.get_media_asset_by_id(db, mid)
            if asset is None:
                continue
            tags = _asset_tag_set(asset)
            member_tag_sets.append(tags)
            if mid == cluster.canonical_media_asset_id:
                canonical_existing = tags
            for tok in self.split_file_name_to_tokens(asset.file_name):
                fn_tokens.add(self.normalize_tag(tok))
        if canonical_existing:
            signals["duplicate_canonical"] = canonical_existing
        # Общие теги участников (пересечение непустых наборов).
        common = set.intersection(*member_tag_sets) if member_tag_sets else set()
        if common:
            signals["existing_tags"] = common
        if fn_tokens:
            signals["file_name"] = fn_tokens
        return self.build_tag_suggestion_payload(signals, canonical_existing)

    # ------------------------------------------------------------------ #
    # Чистые правила                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def normalize_tag(value: str) -> str:
        """Нормализовать тег: lower/trim/замена _-/удаление мусора."""
        norm = str(value or "").strip().lower().lstrip("#")
        norm = norm.replace("_", " ").replace("-", " ")
        norm = re.sub(r"\s+", " ", norm).strip()
        return norm

    @staticmethod
    def split_file_name_to_tokens(file_name: str | None) -> list[str]:
        """Разбить имя файла на теги (Cyrillic/Latin safe; без чисел и очень коротких слов)."""
        name = str(file_name or "")
        base = name.rsplit(".", 1)[0] if "." in name else name
        parts = re.split(r"[\s_\-.]+", base)
        tokens: list[str] = []
        for part in parts:
            tok = re.sub(r"\d+", "", part).strip().lower()
            if len(tok) < 3 or tok in _STOPWORDS:
                continue
            tokens.append(tok)
        return list(dict.fromkeys(tokens))

    @classmethod
    def classify_tag(cls, tag: str) -> str:
        """Классифицировать тег: product | technology | free (MVP-словарь)."""
        norm = cls.normalize_tag(tag)
        if norm in _PRODUCT_TAGS:
            return "product"
        if norm in _TECHNOLOGY_TAGS:
            return "technology"
        return "free"

    def build_tag_suggestion_payload(
        self, signals: dict[str, set[str]], existing: set[str]
    ) -> dict[str, Any]:
        """Собрать payload предложения тегов: теги/продукты/технологии/уверенность/сигналы."""
        all_tags: set[str] = set()
        for values in signals.values():
            all_tags |= {t for t in values if t}
        all_tags = {t for t in all_tags if t}
        products = sorted({t for t in all_tags if self.classify_tag(t) == "product"})
        technologies = sorted({t for t in all_tags if self.classify_tag(t) == "technology"})
        new_tags = sorted(all_tags - existing)

        sources = sorted(k for k, v in signals.items() if v)
        confidence = 0.4 + 0.12 * len(sources)
        if products or technologies:
            confidence += 0.1
        if not new_tags:
            confidence *= 0.5  # нечего добавить — низкая ценность
        confidence = round(max(0.0, min(0.95, confidence)), 3)

        risk_flags: list[str] = []
        if not sources:
            risk_flags.append("no_signals")
        if sources == ["file_name"]:
            risk_flags.append("only_filename")
        if not new_tags:
            risk_flags.append("no_new_tags")

        reasons: list[str] = []
        if "duplicate_canonical" in sources:
            reasons.append("Теги взяты у canonical-медиа дубля.")
        if "crm_category" in sources or "product_priorities" in sources:
            reasons.append("Теги согласованы с CRM-категорией/приоритетами.")
        if "high_performing_tags" in sources:
            reasons.append("Добавлены сильные теги из обучения.")
        if "file_name" in sources:
            reasons.append("Теги извлечены из имени файла.")

        return {
            "suggested_tags": new_tags[:15],
            "suggested_products": products[:8],
            "suggested_technologies": technologies[:8],
            "confidence_score": confidence,
            "source_signals": sources,
            "reasons": reasons[:6],
            "risk_flags": list(dict.fromkeys(risk_flags)),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _crm_signals(self, db: Session, project_id: int) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return out
        cats = crm_repo.list_categories_by_config(db, config.id)
        media_tags: set[str] = set()
        products: set[str] = set()
        technologies: set[str] = set()
        for cat in cats:
            media_tags |= {self.normalize_tag(t) for t in (cat.media_tags or [])}
            products |= {self.normalize_tag(k) for k in (cat.product_priorities or {})}
            technologies |= {self.normalize_tag(k) for k in (cat.technology_priorities or {})}
        keywords: set[str] = set()
        for kw in crm_repo.list_keywords_by_config(db, config.id):
            for value in (kw.product, kw.technology, kw.cluster):
                if value:
                    keywords.add(self.normalize_tag(value))
        if media_tags:
            out["crm_category"] = media_tags
        if products:
            out["product_priorities"] = products
        if technologies:
            out["technology_priorities"] = technologies
        if keywords:
            out["crm_keywords"] = keywords
        return out

    def _recent_decision_tags(self, db: Session, project_id: int) -> set[str]:
        tags: set[str] = set()
        for decision in schedule_media_decision_repository.list_for_project(
            db, project_id, limit=20
        ):
            for tag in decision.selected_media_tags or []:
                tags.add(self.normalize_tag(tag))
        return tags

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _use_learning(self) -> bool:
        return bool(getattr(self._resolve_settings(), "media_curation_use_learning", True))

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning


def _asset_tag_set(asset: Any) -> set[str]:
    tags = getattr(asset, "tags", None) or {}
    out: set[str] = set()
    for group in _TAG_GROUPS:
        for value in tags.get(group, []) or []:
            norm = MediaTagSuggestionService.normalize_tag(value)
            if norm:
                out.add(norm)
    return out


def get_media_tag_suggestion_service() -> MediaTagSuggestionService:
    """DI-фабрика сервиса предложения тегов."""
    return MediaTagSuggestionService()
