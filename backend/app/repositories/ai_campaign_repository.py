"""Репозиторий AI Campaign Manager (v0.6.7): кампании + этапы + рекомендации.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.ai_campaign import AICampaign
from app.models.ai_campaign_recommendation import AICampaignRecommendation
from app.models.ai_campaign_stage import AICampaignStage

# Поля кампании, которые сервис может обновлять (белый список).
_CAMPAIGN_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "goal",
        "status",
        "description",
        "product_context",
        "audience_context",
        "business_context",
        "start_date",
        "end_date",
        "strategy_snapshot",
        "kpi_targets",
        "approved_at",
        "applied_at",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Campaign                                                                     #
# ---------------------------------------------------------------------------- #


def create_campaign(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    name: str,
    goal: str,
    description: str | None = None,
    product_context: dict[str, Any] | None = None,
    audience_context: dict[str, Any] | None = None,
    business_context: dict[str, Any] | None = None,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    created_by_user_id: int | None = None,
) -> AICampaign:
    """Создать кампанию (status=draft)."""
    campaign = AICampaign(
        project_id=project_id,
        account_id=account_id,
        name=name[:255],
        goal=goal,
        status="draft",
        description=description,
        product_context=product_context or {},
        audience_context=audience_context or {},
        business_context=business_context or {},
        start_date=start_date,
        end_date=end_date,
        created_by_user_id=created_by_user_id,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def get_campaign(db: Session, campaign_id: int) -> AICampaign | None:
    """Кампания по id (или None)."""
    return db.get(AICampaign, campaign_id)


def list_campaigns(db: Session, project_id: int, *, limit: int = 200) -> list[AICampaign]:
    """Кампании проекта (свежие сверху)."""
    stmt = (
        select(AICampaign)
        .where(AICampaign.project_id == project_id)
        .order_by(AICampaign.id.desc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def update_campaign(db: Session, campaign: AICampaign, **fields: Any) -> AICampaign:
    """Обновить поля кампании (только белый список)."""
    for key, value in fields.items():
        if key in _CAMPAIGN_FIELDS:
            setattr(campaign, key, value)
    db.commit()
    db.refresh(campaign)
    return campaign


# ---------------------------------------------------------------------------- #
# Stages                                                                       #
# ---------------------------------------------------------------------------- #


def create_stage(
    db: Session,
    *,
    campaign_id: int,
    stage_type: str,
    order_number: int,
    title: str,
    description: str | None = None,
    goal: str | None = None,
    content_pillars: list[Any] | None = None,
    recommended_formats: list[Any] | None = None,
    recommended_topics: list[Any] | None = None,
    cta_strategy: dict[str, Any] | None = None,
    duration_days: int = 7,
) -> AICampaignStage:
    """Создать этап кампании."""
    stage = AICampaignStage(
        campaign_id=campaign_id,
        stage_type=stage_type,
        order_number=order_number,
        title=title[:255],
        description=description,
        goal=goal,
        content_pillars=content_pillars or [],
        recommended_formats=recommended_formats or [],
        recommended_topics=recommended_topics or [],
        cta_strategy=cta_strategy or {},
        duration_days=int(duration_days),
    )
    db.add(stage)
    db.commit()
    db.refresh(stage)
    return stage


def list_stages(db: Session, campaign_id: int) -> list[AICampaignStage]:
    """Этапы кампании по порядку."""
    stmt = (
        select(AICampaignStage)
        .where(AICampaignStage.campaign_id == campaign_id)
        .order_by(AICampaignStage.order_number.asc(), AICampaignStage.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def delete_stages(db: Session, campaign_id: int) -> None:
    """Удалить все этапы кампании (для пере-генерации плана этой же кампании)."""
    db.execute(delete(AICampaignStage).where(AICampaignStage.campaign_id == campaign_id))
    db.commit()


# ---------------------------------------------------------------------------- #
# Recommendations                                                              #
# ---------------------------------------------------------------------------- #


def create_recommendation(
    db: Session,
    *,
    campaign_id: int,
    recommendation_type: str,
    title: str,
    priority: int = 0,
    confidence_score: float = 0.0,
    reasoning: list[Any] | None = None,
    expected_result: dict[str, Any] | None = None,
) -> AICampaignRecommendation:
    """Создать рекомендацию кампании (status=generated)."""
    rec = AICampaignRecommendation(
        campaign_id=campaign_id,
        recommendation_type=recommendation_type,
        status="generated",
        priority=int(priority),
        title=title[:255],
        confidence_score=float(confidence_score or 0.0),
        reasoning=reasoning or [],
        expected_result=expected_result or {},
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def get_recommendation(db: Session, recommendation_id: int) -> AICampaignRecommendation | None:
    """Рекомендация кампании по id (или None)."""
    return db.get(AICampaignRecommendation, recommendation_id)


def list_recommendations(
    db: Session, campaign_id: int, *, status: str | None = None, limit: int = 200
) -> list[AICampaignRecommendation]:
    """Рекомендации кампании (по приоритету), с фильтром статуса."""
    stmt = select(AICampaignRecommendation).where(
        AICampaignRecommendation.campaign_id == campaign_id
    )
    if status is not None:
        stmt = stmt.where(AICampaignRecommendation.status == status)
    stmt = stmt.order_by(
        AICampaignRecommendation.priority.desc(), AICampaignRecommendation.id.desc()
    ).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def set_recommendation_status(
    db: Session,
    rec: AICampaignRecommendation,
    status: str,
    *,
    stamp_reviewed: bool = False,
    stamp_applied: bool = False,
) -> AICampaignRecommendation:
    """Сменить статус рекомендации с метками времени."""
    rec.status = status
    if stamp_reviewed:
        rec.reviewed_at = _now()
    if stamp_applied:
        rec.applied_at = _now()
    db.commit()
    db.refresh(rec)
    return rec


def accept_recommendation(db: Session, rec: AICampaignRecommendation) -> AICampaignRecommendation:
    """Одобрить рекомендацию (status=accepted)."""
    return set_recommendation_status(db, rec, "accepted", stamp_reviewed=True)


def reject_recommendation(db: Session, rec: AICampaignRecommendation) -> AICampaignRecommendation:
    """Отклонить рекомендацию (status=rejected)."""
    return set_recommendation_status(db, rec, "rejected", stamp_reviewed=True)


def apply_recommendation(db: Session, rec: AICampaignRecommendation) -> AICampaignRecommendation:
    """Пометить рекомендацию применённой (status=applied)."""
    return set_recommendation_status(db, rec, "applied", stamp_applied=True)


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_campaign_view(campaign: AICampaign) -> dict[str, Any]:
    """Безопасное представление кампании (без секретов)."""
    return {
        "id": campaign.id,
        "project_id": campaign.project_id,
        "account_id": campaign.account_id,
        "name": campaign.name,
        "goal": campaign.goal,
        "status": campaign.status,
        "description": campaign.description,
        "product_context": dict(campaign.product_context or {}),
        "audience_context": dict(campaign.audience_context or {}),
        "business_context": dict(campaign.business_context or {}),
        "start_date": campaign.start_date.isoformat() if campaign.start_date else None,
        "end_date": campaign.end_date.isoformat() if campaign.end_date else None,
        "strategy_snapshot": dict(campaign.strategy_snapshot or {}),
        "kpi_targets": dict(campaign.kpi_targets or {}),
        "approved_at": campaign.approved_at.isoformat() if campaign.approved_at else None,
        "applied_at": campaign.applied_at.isoformat() if campaign.applied_at else None,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


def public_stage_view(stage: AICampaignStage) -> dict[str, Any]:
    """Безопасное представление этапа."""
    return {
        "id": stage.id,
        "stage_type": stage.stage_type,
        "order_number": stage.order_number,
        "title": stage.title,
        "description": stage.description,
        "goal": stage.goal,
        "content_pillars": list(stage.content_pillars or []),
        "recommended_formats": list(stage.recommended_formats or []),
        "recommended_topics": list(stage.recommended_topics or []),
        "cta_strategy": dict(stage.cta_strategy or {}),
        "duration_days": stage.duration_days,
    }


def public_recommendation_view(rec: AICampaignRecommendation) -> dict[str, Any]:
    """Безопасное представление рекомендации."""
    return {
        "id": rec.id,
        "campaign_id": rec.campaign_id,
        "recommendation_type": rec.recommendation_type,
        "status": rec.status,
        "priority": rec.priority,
        "title": rec.title,
        "reasoning": list(rec.reasoning or []),
        "expected_result": dict(rec.expected_result or {}),
        "confidence_score": round(float(rec.confidence_score or 0.0), 1),
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "applied_at": rec.applied_at.isoformat() if rec.applied_at else None,
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
    }
