"""Репозиторий календарей автопостинга (Calendar Assistant) — v0.5.8.

Изолирует доступ к ``autopilot_calendar_plans``. Публичное представление (``public_plan_view``) не
содержит секретов/сырых токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.autopilot_calendar_plan import AutopilotCalendarPlan


def create_plan(db: Session, **fields: Any) -> AutopilotCalendarPlan:
    """Создать календарь автопостинга."""
    plan = AutopilotCalendarPlan(**fields)
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


def get_plan_by_id(db: Session, plan_id: int) -> AutopilotCalendarPlan | None:
    """Календарь по id (или None)."""
    return db.get(AutopilotCalendarPlan, plan_id)


def get_active_plan_for_project(db: Session, project_id: int) -> AutopilotCalendarPlan | None:
    """Активный календарь проекта (свежий active; иначе None)."""
    stmt = (
        select(AutopilotCalendarPlan)
        .where(
            AutopilotCalendarPlan.project_id == project_id,
            AutopilotCalendarPlan.status == "active",
        )
        .order_by(AutopilotCalendarPlan.id.desc())
    )
    return db.execute(stmt).scalars().first()


def list_plans_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[AutopilotCalendarPlan]:
    """Календари проекта (свежие первыми)."""
    stmt = (
        select(AutopilotCalendarPlan)
        .where(AutopilotCalendarPlan.project_id == project_id)
        .order_by(AutopilotCalendarPlan.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def update_plan(
    db: Session, plan: AutopilotCalendarPlan, fields: dict[str, Any]
) -> AutopilotCalendarPlan:
    """Обновить произвольные поля календаря."""
    for key, value in fields.items():
        setattr(plan, key, value)
    db.commit()
    db.refresh(plan)
    return plan


def activate_plan(db: Session, plan: AutopilotCalendarPlan) -> AutopilotCalendarPlan:
    """Активировать календарь (снимает active с прочих календарей проекта)."""
    for other in list_plans_for_project(db, plan.project_id):
        if other.id != plan.id and other.status == "active":
            other.status = "archived"
    plan.status = "active"
    db.commit()
    db.refresh(plan)
    return plan


def pause_plan(db: Session, plan: AutopilotCalendarPlan) -> AutopilotCalendarPlan:
    """Поставить календарь на паузу."""
    return update_plan(db, plan, {"status": "paused"})


def archive_plan(db: Session, plan: AutopilotCalendarPlan) -> AutopilotCalendarPlan:
    """Архивировать календарь (без удаления)."""
    return update_plan(db, plan, {"status": "archived"})


def set_linked_publishing_plans(
    db: Session, plan: AutopilotCalendarPlan, plan_ids: list[int]
) -> AutopilotCalendarPlan:
    """Сохранить связанные id CrmPublishingPlan."""
    return update_plan(db, plan, {"linked_publishing_plan_ids": list(plan_ids)})


def public_plan_view(plan: AutopilotCalendarPlan) -> dict[str, Any]:
    """Безопасное представление календаря (без секретов)."""
    return {
        "id": plan.id,
        "project_id": plan.project_id,
        "account_id": plan.account_id,
        "autopilot_profile_id": plan.autopilot_profile_id,
        "status": plan.status,
        "preset": plan.preset,
        "goal": plan.goal,
        "platforms": list(plan.platforms or []),
        "weekdays": list(plan.weekdays or []),
        "publish_times": list(plan.publish_times or []),
        "posts_per_day": plan.posts_per_day,
        "timezone": plan.timezone,
        "start_date": plan.start_date,
        "end_date": plan.end_date,
        "time_strategy": plan.time_strategy,
        "generated_rules": dict(plan.generated_rules or {}),
        "risk_flags": list(plan.risk_flags or []),
        "estimated_posts_per_month": plan.estimated_posts_per_month,
        "estimated_units_per_month": plan.estimated_units_per_month,
        "estimated_media_needed": plan.estimated_media_needed,
        "confidence_score": plan.confidence_score,
        "linked_publishing_plan_ids": list(plan.linked_publishing_plan_ids or []),
        "created_at": plan.created_at.isoformat() if plan.created_at else None,
        "updated_at": plan.updated_at.isoformat() if plan.updated_at else None,
    }
