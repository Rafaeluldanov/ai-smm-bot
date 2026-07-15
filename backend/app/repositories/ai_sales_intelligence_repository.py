"""Репозиторий AI Sales & Lead Intelligence (v0.6.8): события лидов + атрибуция + профиль.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
События лидов НЕ удаляются (reset профиля историю сигналов не трогает).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ai_lead_event import AILeadEvent
from app.models.content_revenue_attribution import ContentRevenueAttribution
from app.models.sales_intelligence_profile import SalesIntelligenceProfile

# Поля профиля, которые сервис может обновлять пересчётом (белый список).
_PROFILE_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "best_lead_topics",
        "best_campaigns",
        "best_cta",
        "best_platforms",
        "conversion_patterns",
        "revenue_insights",
        "last_analysis_at",
    }
)
# Типы событий, несущих выручку.
_REVENUE_EVENTS: tuple[str, ...] = ("deal_won", "revenue_added")


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Lead events                                                                  #
# ---------------------------------------------------------------------------- #


def create_lead_event(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    event_type: str,
    source_type: str = "manual",
    status: str = "new",
    post_id: int | None = None,
    campaign_id: int | None = None,
    platform_key: str | None = None,
    value: float = 0.0,
    event_metadata: dict[str, Any] | None = None,
) -> AILeadEvent:
    """Записать событие лида/выручки (без секретов)."""
    event = AILeadEvent(
        project_id=project_id,
        account_id=account_id,
        event_type=event_type,
        source_type=source_type,
        status=status,
        post_id=post_id,
        campaign_id=campaign_id,
        platform_key=platform_key,
        value=float(value or 0.0),
        event_metadata=event_metadata or {},
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def get_lead_event(db: Session, lead_event_id: int) -> AILeadEvent | None:
    """Событие лида по id (или None)."""
    return db.get(AILeadEvent, lead_event_id)


def list_lead_events(
    db: Session,
    project_id: int,
    *,
    event_type: str | None = None,
    since: datetime | None = None,
    limit: int = 1000,
) -> list[AILeadEvent]:
    """События лидов проекта (свежие сверху), с фильтрами."""
    stmt = select(AILeadEvent).where(AILeadEvent.project_id == project_id)
    if event_type is not None:
        stmt = stmt.where(AILeadEvent.event_type == event_type)
    if since is not None:
        stmt = stmt.where(AILeadEvent.created_at >= since)
    stmt = stmt.order_by(AILeadEvent.id.desc()).limit(max(1, min(limit, 5000)))
    return list(db.execute(stmt).scalars().all())


def count_lead_events(db: Session, project_id: int) -> int:
    """Число событий лидов проекта."""
    stmt = select(func.count(AILeadEvent.id)).where(AILeadEvent.project_id == project_id)
    return int(db.execute(stmt).scalar_one())


# ---------------------------------------------------------------------------- #
# Attribution                                                                  #
# ---------------------------------------------------------------------------- #


def create_attribution(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    attribution_model: str,
    revenue_value: float,
    post_id: int | None = None,
    campaign_id: int | None = None,
    lead_event_id: int | None = None,
    confidence_score: float = 0.0,
    reasoning: list[Any] | None = None,
) -> ContentRevenueAttribution:
    """Записать строку атрибуции выручки на контент."""
    row = ContentRevenueAttribution(
        project_id=project_id,
        account_id=account_id,
        attribution_model=attribution_model,
        revenue_value=float(revenue_value or 0.0),
        post_id=post_id,
        campaign_id=campaign_id,
        lead_event_id=lead_event_id,
        confidence_score=float(confidence_score or 0.0),
        reasoning=reasoning or [],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_attributions(
    db: Session, project_id: int, *, attribution_model: str | None = None
) -> None:
    """Удалить строки атрибуции проекта (для пере-расчёта). События лидов не трогает."""
    from sqlalchemy import delete

    stmt = delete(ContentRevenueAttribution).where(
        ContentRevenueAttribution.project_id == project_id
    )
    if attribution_model is not None:
        stmt = stmt.where(ContentRevenueAttribution.attribution_model == attribution_model)
    db.execute(stmt)
    db.commit()


def list_attributions(
    db: Session, project_id: int, *, attribution_model: str | None = None, limit: int = 1000
) -> list[ContentRevenueAttribution]:
    """Строки атрибуции проекта."""
    stmt = select(ContentRevenueAttribution).where(
        ContentRevenueAttribution.project_id == project_id
    )
    if attribution_model is not None:
        stmt = stmt.where(ContentRevenueAttribution.attribution_model == attribution_model)
    stmt = stmt.order_by(ContentRevenueAttribution.id.desc()).limit(max(1, min(limit, 5000)))
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Profile                                                                      #
# ---------------------------------------------------------------------------- #


def get_profile(db: Session, project_id: int) -> SalesIntelligenceProfile | None:
    """Профиль продаж проекта (или None)."""
    stmt = select(SalesIntelligenceProfile).where(SalesIntelligenceProfile.project_id == project_id)
    return db.execute(stmt).scalars().first()


def get_or_create_profile(
    db: Session, project_id: int, account_id: int | None = None
) -> SalesIntelligenceProfile:
    """Получить или создать профиль (race-safe: при гонке ловим IntegrityError)."""
    existing = get_profile(db, project_id)
    if existing is not None:
        return existing
    profile = SalesIntelligenceProfile(
        project_id=project_id, account_id=account_id, status="learning"
    )
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
    db: Session, profile: SalesIntelligenceProfile, **fields: Any
) -> SalesIntelligenceProfile:
    """Обновить поля профиля (только белый список)."""
    for key, value in fields.items():
        if key in _PROFILE_FIELDS:
            setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------- #
# Revenue summary / views                                                      #
# ---------------------------------------------------------------------------- #


def build_revenue_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Агрегированная сводка выручки/лидов проекта (для UI/отчёта)."""
    events = list_lead_events(db, project_id, limit=5000)
    total_revenue = sum(float(e.value or 0.0) for e in events if e.event_type in _REVENUE_EVENTS)
    leads = sum(1 for e in events if e.event_type == "lead_created")
    deals = sum(1 for e in events if e.event_type in ("deal_created", "deal_won"))
    won = sum(1 for e in events if e.event_type == "deal_won")
    by_event: dict[str, int] = {}
    for e in events:
        by_event[e.event_type] = by_event.get(e.event_type, 0) + 1
    return {
        "project_id": project_id,
        "total_revenue": round(total_revenue, 2),
        "leads": leads,
        "deals": deals,
        "won_deals": won,
        "lead_events_count": len(events),
        "events_by_type": by_event,
    }


def public_lead_event_view(event: AILeadEvent) -> dict[str, Any]:
    """Безопасное представление события лида."""
    return {
        "id": event.id,
        "event_type": event.event_type,
        "status": event.status,
        "source_type": event.source_type,
        "post_id": event.post_id,
        "campaign_id": event.campaign_id,
        "platform_key": event.platform_key,
        "value": round(float(event.value or 0.0), 2),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def public_attribution_view(row: ContentRevenueAttribution) -> dict[str, Any]:
    """Безопасное представление строки атрибуции."""
    return {
        "id": row.id,
        "attribution_model": row.attribution_model,
        "revenue_value": round(float(row.revenue_value or 0.0), 2),
        "post_id": row.post_id,
        "campaign_id": row.campaign_id,
        "lead_event_id": row.lead_event_id,
        "confidence_score": round(float(row.confidence_score or 0.0), 1),
        "reasoning": list(row.reasoning or []),
    }


def public_profile_view(profile: SalesIntelligenceProfile) -> dict[str, Any]:
    """Безопасное представление профиля продаж (без секретов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "status": profile.status,
        "best_lead_topics": list(profile.best_lead_topics or []),
        "best_campaigns": list(profile.best_campaigns or []),
        "best_cta": list(profile.best_cta or []),
        "best_platforms": list(profile.best_platforms or []),
        "conversion_patterns": dict(profile.conversion_patterns or {}),
        "revenue_insights": dict(profile.revenue_insights or {}),
        "last_analysis_at": (
            profile.last_analysis_at.isoformat() if profile.last_analysis_at else None
        ),
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
