"""SEO-адаптер для контент-стратега (v0.6.6).

Подключает существующий офлайн SEO-слой (``seo_content_sources`` + ``topic_taxonomy``)
и отдаёт стратегу SEO-сигнал: ключевые слова, поисковый спрос, сезонность, и оценку
темы ``seo_score`` (0..1). Без сети и внешних API; неизвестный проект → нейтральный сигнал.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.repositories import project_repository
from app.services import topic_taxonomy

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


class SeoStrategyAdapter:
    """Мост к SEO-слою: ключевые слова, спрос, сезонность, seo_score темы."""

    def get_seo_signal(self, db: Session, project_id: int) -> dict[str, Any]:
        """SEO-сигнал проекта: топ-запросы, средний спрос, сезонность, поддержка."""
        slug = self._project_slug(db, project_id)
        keywords: list[str] = []
        seasonality: dict[str, Any] = {}
        supported = False
        demand_values: list[float] = []

        profile = self._seo_profile(slug)
        if profile is not None:
            supported = True
            for query in getattr(profile, "seo_queries", []) or []:
                kw = str(getattr(query, "query", "") or "").strip()
                if kw:
                    keywords.append(kw)

        # Спрос/сезонность из таксономии кластеров (есть безопасный fallback).
        for candidate in self._topic_candidates(slug):
            demand = candidate.get("base_search_demand_score")
            if isinstance(demand, (int, float)):
                demand_values.append(float(demand))
            for kw in candidate.get("base_seo_keywords", []) or []:
                if kw and str(kw) not in keywords:
                    keywords.append(str(kw))
            cluster = candidate.get("cluster") or candidate.get("topic")
            if cluster:
                cluster_profile = topic_taxonomy.get_cluster_profile(str(cluster))
                season = cluster_profile.get("seasonality")
                if season is not None:
                    seasonality[str(cluster)] = season

        avg_demand = round(sum(demand_values) / len(demand_values), 3) if demand_values else 0.0
        return {
            "project_id": project_id,
            "supported": supported,
            "keywords": keywords[:20],
            "avg_search_demand": avg_demand,
            "seasonality": seasonality,
            "seo_score": avg_demand,
        }

    def score_topic_seo(self, db: Session, project_id: int, topic: str) -> float:
        """Оценка темы по SEO-спросу (0..1): по кластеру темы + совпадению ключевых слов."""
        topic_l = (topic or "").strip().lower()
        if not topic_l:
            return 0.0
        cluster_profile = topic_taxonomy.get_cluster_profile(topic_l)
        demand = cluster_profile.get("search_demand")
        score = float(demand) if isinstance(demand, (int, float)) else 0.0
        # Небольшой бонус за совпадение с реальными поисковыми запросами проекта.
        signal = self.get_seo_signal(db, project_id)
        for kw in signal.get("keywords", []):
            if topic_l in str(kw).lower() or str(kw).lower() in topic_l:
                score = min(1.0, score + 0.15)
                break
        return round(max(0.0, min(1.0, score)), 3)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _project_slug(db: Session, project_id: int) -> str:
        project = project_repository.get_project_by_id(db, project_id)
        return str(getattr(project, "slug", "") or "") if project is not None else ""

    @staticmethod
    def _seo_profile(slug: str) -> Any | None:
        if not slug:
            return None
        try:
            from app.services import seo_content_sources

            return seo_content_sources.get_project_seo_profile(slug)
        except Exception:  # noqa: BLE001 — неизвестный проект/офлайн-источник
            return None

    @staticmethod
    def _topic_candidates(slug: str) -> list[dict[str, Any]]:
        if not slug:
            return []
        try:
            return list(topic_taxonomy.get_all_topic_candidates(slug))
        except Exception:  # noqa: BLE001 — таксономия не знает проект
            return []


def get_seo_strategy_adapter() -> SeoStrategyAdapter:
    """DI-фабрика SEO-адаптера стратегии."""
    return SeoStrategyAdapter()
