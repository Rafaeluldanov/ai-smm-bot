"""Репозиторий профилей автопилота проекта — v0.5.6.

Изолирует доступ к ``project_autopilot_profiles``. Публичное представление (``public_profile_view``)
не содержит секретов/сырых токенов/внутренних путей. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_autopilot_profile import ProjectAutopilotProfile


def get_profile_by_project_id(db: Session, project_id: int) -> ProjectAutopilotProfile | None:
    """Профиль автопилота проекта (или None)."""
    stmt = select(ProjectAutopilotProfile).where(ProjectAutopilotProfile.project_id == project_id)
    return db.execute(stmt).scalars().first()


def create_profile(db: Session, **fields: Any) -> ProjectAutopilotProfile:
    """Создать профиль автопилота."""
    profile = ProjectAutopilotProfile(**fields)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_or_create_profile(
    db: Session,
    account_id: int | None,
    project_id: int,
    default_mode: str = "full_auto",
    current_user_id: int | None = None,
) -> ProjectAutopilotProfile:
    """Получить или создать профиль автопилота проекта (без побочных live-эффектов)."""
    existing = get_profile_by_project_id(db, project_id)
    if existing is not None:
        return existing
    return create_profile(
        db,
        account_id=account_id,
        project_id=project_id,
        status="setup_required",
        mode=default_mode,
        is_enabled=False,
        created_by_user_id=current_user_id,
        updated_by_user_id=current_user_id,
    )


def update_profile(
    db: Session, profile: ProjectAutopilotProfile, fields: dict[str, Any]
) -> ProjectAutopilotProfile:
    """Обновить произвольные поля профиля."""
    for key, value in fields.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


def set_status(
    db: Session, profile: ProjectAutopilotProfile, status: str
) -> ProjectAutopilotProfile:
    """Установить статус профиля."""
    return update_profile(db, profile, {"status": status})


def set_enabled(
    db: Session, profile: ProjectAutopilotProfile, enabled: bool
) -> ProjectAutopilotProfile:
    """Включить/выключить автопилот (флаг is_enabled)."""
    return update_profile(db, profile, {"is_enabled": bool(enabled)})


def update_calendar_rules(
    db: Session, profile: ProjectAutopilotProfile, rules: dict[str, Any]
) -> ProjectAutopilotProfile:
    """Сохранить упрощённые правила календаря."""
    return update_profile(db, profile, {"calendar_rules": rules})


def update_content_rules(
    db: Session, profile: ProjectAutopilotProfile, rules: dict[str, Any]
) -> ProjectAutopilotProfile:
    """Сохранить правила контента (цель/тон/глубина/CTA)."""
    return update_profile(db, profile, {"content_rules": rules})


def update_quality_rules(
    db: Session, profile: ProjectAutopilotProfile, rules: dict[str, Any]
) -> ProjectAutopilotProfile:
    """Сохранить правила качества медиатеки."""
    return update_profile(db, profile, {"quality_rules": rules})


def update_setup_progress(
    db: Session, profile: ProjectAutopilotProfile, progress: dict[str, Any]
) -> ProjectAutopilotProfile:
    """Сохранить прогресс мастера настройки."""
    return update_profile(db, profile, {"setup_progress": progress})


def update_blockers(
    db: Session, profile: ProjectAutopilotProfile, blockers: list[Any]
) -> ProjectAutopilotProfile:
    """Сохранить активные блокеры."""
    return update_profile(db, profile, {"active_blockers": blockers})


def list_profiles_for_account(
    db: Session, account_id: int, limit: int = 200
) -> list[ProjectAutopilotProfile]:
    """Профили автопилота аккаунта (свежие первыми)."""
    stmt = (
        select(ProjectAutopilotProfile)
        .where(ProjectAutopilotProfile.account_id == account_id)
        .order_by(ProjectAutopilotProfile.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_running_profiles(db: Session, limit: int = 100) -> list[ProjectAutopilotProfile]:
    """Работающие профили (is_enabled=true, status=running)."""
    stmt = (
        select(ProjectAutopilotProfile)
        .where(
            ProjectAutopilotProfile.is_enabled.is_(True),
            ProjectAutopilotProfile.status == "running",
        )
        .order_by(ProjectAutopilotProfile.id.desc())
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def public_profile_view(profile: ProjectAutopilotProfile) -> dict[str, Any]:
    """Безопасное представление профиля (без секретов/сырых токенов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "status": profile.status,
        "mode": profile.mode,
        "is_enabled": profile.is_enabled,
        "yandex_resource_id": profile.yandex_resource_id,
        "primary_platforms": list(profile.primary_platforms or []),
        "calendar_rules": dict(profile.calendar_rules or {}),
        "content_rules": dict(profile.content_rules or {}),
        "quality_rules": dict(profile.quality_rules or {}),
        "setup_progress": dict(profile.setup_progress or {}),
        "active_blockers": list(profile.active_blockers or []),
        "last_health_status": profile.last_health_status,
        "last_health_check_at": (
            profile.last_health_check_at.isoformat() if profile.last_health_check_at else None
        ),
        "next_planned_post_at": (
            profile.next_planned_post_at.isoformat() if profile.next_planned_post_at else None
        ),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
