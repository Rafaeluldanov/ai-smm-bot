"""PostPerformanceLearningService — сравнение эффективности постов (v0.6.5).

Аналитический помощник AI Learning Loop: собирает метрики поста, сравнивает посты,
находит «победителей» и «провалы». Только чтение аналитики — ничего не публикует,
внешние API не вызывает, live-флаги не трогает.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.repositories import analytics_repository
from app.services import analytics_metrics

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session


class PostPerformanceLearningService:
    """Сравнение и ранжирование постов по эффективности (0..100)."""

    def collect_post_metrics(self, db: Session, post_id: int) -> dict[str, Any]:
        """Собрать агрегированные метрики поста + performance score (0..100)."""
        snaps = analytics_repository.list_snapshots(db, post_id=post_id, limit=500)
        return self._aggregate(snaps, post_id)

    def compare_posts(self, db: Session, post_id_a: int, post_id_b: int) -> dict[str, Any]:
        """Сравнить два поста: кто эффективнее и почему."""
        a = self.collect_post_metrics(db, post_id_a)
        b = self.collect_post_metrics(db, post_id_b)
        if a["performance_score"] == b["performance_score"]:
            winner: int | None = None
            reason = "Посты сопоставимы по эффективности."
        else:
            better = a if a["performance_score"] > b["performance_score"] else b
            worse = b if better is a else a
            winner = better["post_id"]
            reason = self._explain_gap(better, worse)
        return {"post_a": a, "post_b": b, "winner_post_id": winner, "reason": reason}

    def detect_winners(
        self, db: Session, project_id: int, *, limit: int = 5, min_score: float = 55.0
    ) -> list[dict[str, Any]]:
        """Топ-посты проекта по эффективности (score >= min_score)."""
        ranked = self._rank_project_posts(db, project_id)
        winners = [r for r in ranked if r["performance_score"] >= min_score]
        return winners[:limit]

    def detect_failures(
        self, db: Session, project_id: int, *, limit: int = 5, max_score: float = 25.0
    ) -> list[dict[str, Any]]:
        """Худшие посты проекта (score <= max_score) — кандидаты на пересмотр."""
        ranked = self._rank_project_posts(db, project_id)
        failures = [r for r in reversed(ranked) if r["performance_score"] <= max_score]
        return failures[:limit]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _rank_project_posts(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Все посты проекта с метриками, отсортированные по убыванию score."""
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        # Последний снапшот на (post, platform).
        latest: dict[tuple[int, str], Any] = {}
        for snap in snapshots:
            key = (snap.post_id, snap.platform)
            prev = latest.get(key)
            if prev is None or (snap.id or 0) > (prev.id or 0):
                latest[key] = snap
        by_post: dict[int, list[Any]] = {}
        for snap in latest.values():
            by_post.setdefault(snap.post_id, []).append(snap)
        rows = [self._aggregate(snaps, post_id) for post_id, snaps in by_post.items()]
        rows.sort(key=lambda r: r["performance_score"], reverse=True)
        return rows

    def _aggregate(self, snapshots: list[Any], post_id: int) -> dict[str, Any]:
        """Свести снапшоты поста (последний на площадку) в метрики + score."""
        latest: dict[str, Any] = {}
        for snap in snapshots:
            prev = latest.get(snap.platform)
            if prev is None or (snap.id or 0) > (prev.id or 0):
                latest[snap.platform] = snap
        impressions = reach = likes = reactions = comments = shares = saves = clicks = 0
        for snap in latest.values():
            impressions += int(snap.impressions or 0)
            reach += int(snap.reach or 0)
            likes += int(snap.likes or 0)
            reactions += int(snap.reactions or 0)
            comments += int(snap.comments or 0)
            shares += int(snap.shares or 0)
            saves += int(snap.saves or 0)
            clicks += int(snap.clicks or 0)
        engagements = analytics_metrics.calculate_engagements(
            likes, reactions, comments, shares, saves
        )
        ctr = analytics_metrics.calculate_ctr(clicks, impressions, reach)
        er = analytics_metrics.calculate_engagement_rate(engagements, impressions, reach)
        score = analytics_metrics.calculate_performance_score(
            impressions, reach, engagements, clicks, ctr, er
        )
        return {
            "post_id": post_id,
            "impressions": impressions,
            "reach": reach,
            "engagements": engagements,
            "saves": saves,
            "shares": shares,
            "clicks": clicks,
            "ctr": ctr,
            "engagement_rate": er,
            "performance_score": score,
            "snapshots": len(latest),
        }

    @staticmethod
    def _explain_gap(better: dict[str, Any], worse: dict[str, Any]) -> str:
        """Короткое объяснение, почему один пост эффективнее другого."""
        reasons: list[str] = []
        if better["reach"] > worse["reach"] * 1.3:
            reasons.append("больше охват")
        if better["engagement_rate"] > worse["engagement_rate"] * 1.2:
            reasons.append("выше вовлечённость")
        if (better["saves"] + better["shares"]) > (worse["saves"] + worse["shares"]) * 1.3:
            reasons.append("больше сохранений/репостов")
        if better["ctr"] > worse["ctr"] * 1.2:
            reasons.append("выше CTR")
        gap = ", ".join(reasons) if reasons else "выше суммарная эффективность"
        return f"Пост {better['post_id']} эффективнее: {gap}."


def get_post_performance_learning_service() -> PostPerformanceLearningService:
    """DI-фабрика помощника сравнения постов."""
    return PostPerformanceLearningService()
