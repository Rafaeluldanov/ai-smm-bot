"""Репозиторий AI Business Growth Agent (v0.6.9): профиль роста + рекомендации.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.business_growth_profile import BusinessGrowthProfile
from app.models.business_growth_recommendation import BusinessGrowthRecommendation

# Поля профиля, которые сервис может обновлять (белый список).
_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "business_goal",
        "growth_targets",
        "current_state",
        "strengths",
        "weaknesses",
        "opportunities",
        "risks",
        "growth_score",
        "last_analysis_at",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Profile                                                                      #
# ---------------------------------------------------------------------------- #


def get_profile(db: Session, project_id: int) -> BusinessGrowthProfile | None:
    """Профиль роста проекта (или None)."""
    stmt = select(BusinessGrowthProfile).where(BusinessGrowthProfile.project_id == project_id)
    return db.execute(stmt).scalars().first()


def get_or_create_profile(
    db: Session, project_id: int, account_id: int | None = None
) -> BusinessGrowthProfile:
    """Получить или создать профиль (race-safe: при гонке ловим IntegrityError)."""
    existing = get_profile(db, project_id)
    if existing is not None:
        return existing
    profile = BusinessGrowthProfile(project_id=project_id, account_id=account_id, status="learning")
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:  # параллельное создание — берём чужой профиль
        db.rollback()
        existing = get_profile(db, project_id)
        if existing is not None:
            return existing
        raise
    db.refresh(profile)
    return profile


def update_profile(
    db: Session, profile: BusinessGrowthProfile, **fields: Any
) -> BusinessGrowthProfile:
    """Обновить поля профиля (только белый список)."""
    for key, value in fields.items():
        if key in _PROFILE_FIELDS:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------- #
# Recommendations                                                              #
# ---------------------------------------------------------------------------- #


def create_recommendation(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    recommendation_type: str,
    title: str,
    description: str | None = None,
    priority: int = 0,
    confidence_score: float = 0.0,
    reasoning: list[Any] | None = None,
    source_signals: list[Any] | None = None,
    expected_impact: dict[str, Any] | None = None,
    apply_payload: dict[str, Any] | None = None,
) -> BusinessGrowthRecommendation:
    """Создать рекомендацию роста (status=generated)."""
    rec = BusinessGrowthRecommendation(
        project_id=project_id,
        account_id=account_id,
        recommendation_type=recommendation_type,
        status="generated",
        priority=int(priority),
        title=title[:255],
        description=description,
        confidence_score=float(confidence_score or 0.0),
        reasoning=reasoning or [],
        source_signals=source_signals or [],
        expected_impact=expected_impact or {},
        apply_payload=apply_payload or {},
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def get_recommendation_by_id(
    db: Session, recommendation_id: int
) -> BusinessGrowthRecommendation | None:
    """Рекомендация по id (или None)."""
    return db.get(BusinessGrowthRecommendation, recommendation_id)


def list_recommendations(
    db: Session,
    project_id: int,
    *,
    status: str | None = None,
    limit: int = 200,
) -> list[BusinessGrowthRecommendation]:
    """Рекомендации проекта (по приоритету), с фильтром статуса."""
    stmt = select(BusinessGrowthRecommendation).where(
        BusinessGrowthRecommendation.project_id == project_id
    )
    if status is not None:
        stmt = stmt.where(BusinessGrowthRecommendation.status == status)
    stmt = stmt.order_by(
        BusinessGrowthRecommendation.priority.desc(),
        BusinessGrowthRecommendation.id.desc(),
    ).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def set_status(
    db: Session,
    rec: BusinessGrowthRecommendation,
    status: str,
    *,
    stamp_reviewed: bool = False,
    stamp_applied: bool = False,
) -> BusinessGrowthRecommendation:
    """Сменить статус рекомендации с проставлением меток времени."""
    rec.status = status
    if stamp_reviewed:
        rec.reviewed_at = _now()
    if stamp_applied:
        rec.applied_at = _now()
    db.commit()
    db.refresh(rec)
    return rec


def accept(db: Session, rec: BusinessGrowthRecommendation) -> BusinessGrowthRecommendation:
    """Одобрить рекомендацию (status=accepted)."""
    return set_status(db, rec, "accepted", stamp_reviewed=True)


def reject(db: Session, rec: BusinessGrowthRecommendation) -> BusinessGrowthRecommendation:
    """Отклонить рекомендацию (status=rejected)."""
    return set_status(db, rec, "rejected", stamp_reviewed=True)


def apply(db: Session, rec: BusinessGrowthRecommendation) -> BusinessGrowthRecommendation:
    """Пометить рекомендацию применённой (status=applied)."""
    return set_status(db, rec, "applied", stamp_applied=True)


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_profile_view(profile: BusinessGrowthProfile) -> dict[str, Any]:
    """Безопасное представление профиля роста (без секретов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "status": profile.status,
        "business_goal": dict(profile.business_goal or {}),
        "growth_targets": dict(profile.growth_targets or {}),
        "current_state": dict(profile.current_state or {}),
        "strengths": list(profile.strengths or []),
        "weaknesses": list(profile.weaknesses or []),
        "opportunities": list(profile.opportunities or []),
        "risks": list(profile.risks or []),
        "growth_score": round(float(profile.growth_score or 0.0), 1),
        "last_analysis_at": (
            profile.last_analysis_at.isoformat() if profile.last_analysis_at else None
        ),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


def public_recommendation_view(rec: BusinessGrowthRecommendation) -> dict[str, Any]:
    """Безопасное представление рекомендации роста."""
    return {
        "id": rec.id,
        "project_id": rec.project_id,
        "recommendation_type": rec.recommendation_type,
        "status": rec.status,
        "priority": rec.priority,
        "title": rec.title,
        "description": rec.description,
        "reasoning": list(rec.reasoning or []),
        "source_signals": list(rec.source_signals or []),
        "expected_impact": dict(rec.expected_impact or {}),
        "confidence_score": round(float(rec.confidence_score or 0.0), 1),
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "applied_at": rec.applied_at.isoformat() if rec.applied_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }


def build_growth_summary(db: Session, profile: BusinessGrowthProfile) -> dict[str, Any]:
    """Сводка профиля роста + счётчик открытых рекомендаций (для UI/отчёта)."""
    return {
        **public_profile_view(profile),
        "recommendations_open": len(
            list_recommendations(db, profile.project_id, status="generated")
        ),
    }
