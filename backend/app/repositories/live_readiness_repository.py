"""Репозиторий готовности к реальной автопубликации (live readiness) — v0.5.9.

Изолирует доступ к ``project_live_readiness_profiles`` и ``platform_live_readiness``. Публичные
представления не содержат секретов/сырых токенов (только признаки наличия). Tenant isolation — на
сервис/API-слое. Репозиторий сам НЕ включает и НЕ обходит глобальные live-флаги.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.platform_live_readiness import PlatformLiveReadiness
from app.models.project_live_readiness_profile import ProjectLiveReadinessProfile


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# ProjectLiveReadinessProfile                                                  #
# ---------------------------------------------------------------------------- #


def get_project_profile(db: Session, project_id: int) -> ProjectLiveReadinessProfile | None:
    """Профиль готовности проекта (или None)."""
    stmt = select(ProjectLiveReadinessProfile).where(
        ProjectLiveReadinessProfile.project_id == project_id
    )
    return db.execute(stmt).scalars().first()


def get_or_create_project_profile(
    db: Session,
    account_id: int | None,
    project_id: int,
    autopilot_profile_id: int | None = None,
) -> ProjectLiveReadinessProfile:
    """Получить или создать профиль готовности проекта."""
    profile = get_project_profile(db, project_id)
    if profile is not None:
        if (
            autopilot_profile_id is not None
            and profile.autopilot_profile_id != autopilot_profile_id
        ):
            profile.autopilot_profile_id = autopilot_profile_id
            db.commit()
            db.refresh(profile)
        return profile
    profile = ProjectLiveReadinessProfile(
        account_id=account_id,
        project_id=project_id,
        autopilot_profile_id=autopilot_profile_id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_project_profile(
    db: Session, profile: ProjectLiveReadinessProfile, fields: dict[str, Any]
) -> ProjectLiveReadinessProfile:
    """Обновить произвольные поля профиля проекта."""
    for key, value in fields.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


def set_project_live_enabled(
    db: Session, profile: ProjectLiveReadinessProfile, enabled: bool, user_id: int | None = None
) -> ProjectLiveReadinessProfile:
    """Включить/выключить per-project live (НЕ трогает глобальные флаги)."""
    fields: dict[str, Any] = {"project_live_enabled": bool(enabled)}
    if enabled:
        fields["confirmed_by_user_id"] = user_id
        fields["confirmed_at"] = _now()
    else:
        fields["disabled_by_user_id"] = user_id
        fields["disabled_at"] = _now()
        fields["full_auto_live_enabled"] = False
    return update_project_profile(db, profile, fields)


def set_full_auto_live_enabled(
    db: Session, profile: ProjectLiveReadinessProfile, enabled: bool, user_id: int | None = None
) -> ProjectLiveReadinessProfile:
    """Включить/выключить full-auto live для проекта (НЕ трогает глобальные флаги)."""
    fields: dict[str, Any] = {"full_auto_live_enabled": bool(enabled)}
    if enabled:
        fields["confirmed_by_user_id"] = user_id
        fields["confirmed_at"] = _now()
    return update_project_profile(db, profile, fields)


def update_project_check_result(
    db: Session, profile: ProjectLiveReadinessProfile, result: dict[str, Any]
) -> ProjectLiveReadinessProfile:
    """Сохранить результат readiness-проверки проекта."""
    fields: dict[str, Any] = {
        "status": result.get("status", profile.status),
        "readiness_score": int(result.get("readiness_score", profile.readiness_score) or 0),
        "blockers": result.get("blockers", []),
        "warnings": result.get("warnings", []),
        "checklist": result.get("checklist", {}),
        "platform_statuses": result.get("platform_statuses", {}),
        "billing_status": result.get("billing_status", {}),
        "media_status": result.get("media_status", {}),
        "schedule_status": result.get("schedule_status", {}),
        "security_status": result.get("security_status", {}),
        "live_mode": result.get("live_mode", profile.live_mode),
        "last_check_at": _now(),
        "last_check_status": result.get("status", profile.status),
    }
    return update_project_profile(db, profile, fields)


def list_project_profiles(
    db: Session, account_id: int | None = None, status: str | None = None, limit: int = 100
) -> list[ProjectLiveReadinessProfile]:
    """Список профилей проектов (с фильтрами по аккаунту/статусу)."""
    stmt = select(ProjectLiveReadinessProfile)
    if account_id is not None:
        stmt = stmt.where(ProjectLiveReadinessProfile.account_id == account_id)
    if status is not None:
        stmt = stmt.where(ProjectLiveReadinessProfile.status == status)
    stmt = stmt.order_by(ProjectLiveReadinessProfile.id.desc()).limit(limit)
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# PlatformLiveReadiness                                                        #
# ---------------------------------------------------------------------------- #


def get_platform_profile(
    db: Session, project_id: int, platform_key: str
) -> PlatformLiveReadiness | None:
    """Профиль готовности площадки (или None)."""
    stmt = select(PlatformLiveReadiness).where(
        PlatformLiveReadiness.project_id == project_id,
        PlatformLiveReadiness.platform_key == platform_key,
    )
    return db.execute(stmt).scalars().first()


def get_or_create_platform_profile(
    db: Session,
    account_id: int | None,
    project_id: int,
    platform_key: str,
    resource_id: int | None = None,
) -> PlatformLiveReadiness:
    """Получить или создать профиль готовности площадки."""
    profile = get_platform_profile(db, project_id, platform_key)
    if profile is not None:
        if resource_id is not None and profile.resource_id != resource_id:
            profile.resource_id = resource_id
            db.commit()
            db.refresh(profile)
        return profile
    profile = PlatformLiveReadiness(
        account_id=account_id,
        project_id=project_id,
        platform_key=platform_key,
        resource_id=resource_id,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def update_platform_profile(
    db: Session, profile: PlatformLiveReadiness, fields: dict[str, Any]
) -> PlatformLiveReadiness:
    """Обновить произвольные поля профиля площадки."""
    for key, value in fields.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


def set_platform_live_enabled(
    db: Session, profile: PlatformLiveReadiness, enabled: bool, user_id: int | None = None
) -> PlatformLiveReadiness:
    """Включить/выключить per-platform live (НЕ трогает глобальные флаги)."""
    fields: dict[str, Any] = {"platform_live_enabled": bool(enabled)}
    if enabled:
        fields["confirmed_by_user_id"] = user_id
        fields["confirmed_at"] = _now()
    else:
        fields["disabled_by_user_id"] = user_id
        fields["disabled_at"] = _now()
    return update_platform_profile(db, profile, fields)


def update_platform_check_result(
    db: Session, profile: PlatformLiveReadiness, result: dict[str, Any]
) -> PlatformLiveReadiness:
    """Сохранить результат readiness-проверки площадки."""
    fields: dict[str, Any] = {
        "status": result.get("status", profile.status),
        "readiness_score": int(result.get("readiness_score", profile.readiness_score) or 0),
        "credentials_present": bool(result.get("credentials_present", profile.credentials_present)),
        "credentials_checked_at": _now(),
        "last_probe_status": result.get("last_probe_status", profile.last_probe_status),
        "last_probe_at": _now(),
        "blockers": result.get("blockers", []),
        "warnings": result.get("warnings", []),
        "required_fields": result.get("required_fields", []),
        "missing_fields": result.get("missing_fields", []),
        "capabilities": result.get("capabilities", {}),
        "media_requirements": result.get("media_requirements", {}),
    }
    return update_platform_profile(db, profile, fields)


def list_platform_profiles(db: Session, project_id: int) -> list[PlatformLiveReadiness]:
    """Профили готовности всех площадок проекта."""
    stmt = (
        select(PlatformLiveReadiness)
        .where(PlatformLiveReadiness.project_id == project_id)
        .order_by(PlatformLiveReadiness.platform_key.asc())
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Публичные представления (без секретов)                                       #
# ---------------------------------------------------------------------------- #


def public_project_profile_view(profile: ProjectLiveReadinessProfile) -> dict[str, Any]:
    """Безопасное представление профиля проекта (без секретов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "autopilot_profile_id": profile.autopilot_profile_id,
        "status": profile.status,
        "live_mode": profile.live_mode,
        "project_live_enabled": bool(profile.project_live_enabled),
        "full_auto_live_enabled": bool(profile.full_auto_live_enabled),
        "readiness_score": profile.readiness_score,
        "blockers": list(profile.blockers or []),
        "warnings": list(profile.warnings or []),
        "checklist": dict(profile.checklist or {}),
        "platform_statuses": dict(profile.platform_statuses or {}),
        "billing_status": dict(profile.billing_status or {}),
        "media_status": dict(profile.media_status or {}),
        "schedule_status": dict(profile.schedule_status or {}),
        "security_status": dict(profile.security_status or {}),
        "last_check_at": profile.last_check_at.isoformat() if profile.last_check_at else None,
        "last_check_status": profile.last_check_status,
        "confirmed_at": profile.confirmed_at.isoformat() if profile.confirmed_at else None,
        "disabled_at": profile.disabled_at.isoformat() if profile.disabled_at else None,
    }


def public_platform_profile_view(profile: PlatformLiveReadiness) -> dict[str, Any]:
    """Безопасное представление профиля площадки (без секретов/токенов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "platform_key": profile.platform_key,
        "resource_id": profile.resource_id,
        "status": profile.status,
        "platform_live_enabled": bool(profile.platform_live_enabled),
        "credentials_present": bool(profile.credentials_present),
        "readiness_score": profile.readiness_score,
        "blockers": list(profile.blockers or []),
        "warnings": list(profile.warnings or []),
        "required_fields": list(profile.required_fields or []),
        "missing_fields": list(profile.missing_fields or []),
        "capabilities": dict(profile.capabilities or {}),
        "media_requirements": dict(profile.media_requirements or {}),
        "confirmation_required": bool(profile.confirmation_required),
        "last_probe_status": profile.last_probe_status,
        "last_probe_at": profile.last_probe_at.isoformat() if profile.last_probe_at else None,
    }
