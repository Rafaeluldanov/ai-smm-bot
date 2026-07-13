"""Репозиторий авто-синхронизации Яндекс Диска — v0.5.7.

Профили (``project_yandex_sync_profiles``) и прогоны (``yandex_auto_sync_runs``). Публичные
представления (``public_*``) не содержат секретов/сырых токенов/внутренних путей — только маска
public_url. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project_yandex_sync_profile import ProjectYandexSyncProfile
from app.models.yandex_auto_sync_run import YandexAutoSyncRun


def _now() -> datetime:
    return datetime.now(UTC)


# ------------------------------------------------------------------ #
# Профиль                                                            #
# ------------------------------------------------------------------ #


def get_profile_by_project_id(db: Session, project_id: int) -> ProjectYandexSyncProfile | None:
    """Профиль синхронизации проекта (или None)."""
    stmt = select(ProjectYandexSyncProfile).where(ProjectYandexSyncProfile.project_id == project_id)
    return db.execute(stmt).scalars().first()


def create_profile(db: Session, **fields: Any) -> ProjectYandexSyncProfile:
    """Создать профиль синхронизации."""
    profile = ProjectYandexSyncProfile(**fields)
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_or_create_profile(
    db: Session,
    account_id: int | None,
    project_id: int,
    current_user_id: int | None = None,
) -> ProjectYandexSyncProfile:
    """Получить или создать профиль синхронизации проекта."""
    existing = get_profile_by_project_id(db, project_id)
    if existing is not None:
        return existing
    return create_profile(
        db,
        account_id=account_id,
        project_id=project_id,
        status="ready",
        is_enabled=True,
        source_type="public_disk_url",
        created_by_user_id=current_user_id,
        updated_by_user_id=current_user_id,
    )


def update_profile(
    db: Session, profile: ProjectYandexSyncProfile, fields: dict[str, Any]
) -> ProjectYandexSyncProfile:
    """Обновить произвольные поля профиля."""
    for key, value in fields.items():
        setattr(profile, key, value)
    db.commit()
    db.refresh(profile)
    return profile


def set_enabled(
    db: Session, profile: ProjectYandexSyncProfile, enabled: bool
) -> ProjectYandexSyncProfile:
    """Включить/выключить синхронизацию."""
    return update_profile(db, profile, {"is_enabled": bool(enabled)})


def set_status(
    db: Session, profile: ProjectYandexSyncProfile, status: str
) -> ProjectYandexSyncProfile:
    """Установить статус профиля."""
    return update_profile(db, profile, {"status": status})


def update_summary(
    db: Session, profile: ProjectYandexSyncProfile, summary: dict[str, Any]
) -> ProjectYandexSyncProfile:
    """Сохранить сводку последней синхронизации + счётчики."""
    return update_profile(db, profile, summary)


def update_blockers(
    db: Session, profile: ProjectYandexSyncProfile, blockers: list[Any]
) -> ProjectYandexSyncProfile:
    """Сохранить активные блокеры."""
    return update_profile(db, profile, {"active_blockers": blockers})


def list_enabled_profiles(db: Session, limit: int = 100) -> list[ProjectYandexSyncProfile]:
    """Включённые профили синхронизации (для воркера)."""
    stmt = (
        select(ProjectYandexSyncProfile)
        .where(ProjectYandexSyncProfile.is_enabled.is_(True))
        .order_by(ProjectYandexSyncProfile.id)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def list_due_profiles(
    db: Session, now: datetime | None = None, limit: int = 100
) -> list[ProjectYandexSyncProfile]:
    """Профили, у которых подошёл срок синхронизации (next_sync_at в прошлом или пуст)."""
    moment = now or _now()
    profiles = list_enabled_profiles(db, limit=limit)
    due: list[ProjectYandexSyncProfile] = []
    for p in profiles:
        nxt = p.next_sync_at
        if nxt is None:
            due.append(p)
            continue
        reference = nxt if nxt.tzinfo is not None else nxt.replace(tzinfo=UTC)
        if moment >= reference:
            due.append(p)
    return due[:limit]


def public_profile_view(profile: ProjectYandexSyncProfile) -> dict[str, Any]:
    """Безопасное представление профиля (public_url — маской; без сырых путей/токенов)."""
    return {
        "id": profile.id,
        "project_id": profile.project_id,
        "account_id": profile.account_id,
        "autopilot_profile_id": profile.autopilot_profile_id,
        "status": profile.status,
        "is_enabled": profile.is_enabled,
        "source_type": profile.source_type,
        "public_url_masked": _mask_url(profile.public_url),
        "has_public_url": bool((profile.public_url or "").strip()),
        "root_folder": profile.root_folder,
        "default_tags": list(profile.default_tags or []),
        "sync_frequency_minutes": profile.sync_frequency_minutes,
        "media_count": profile.media_count,
        "image_count": profile.image_count,
        "video_count": profile.video_count,
        "new_media_count": profile.new_media_count,
        "updated_media_count": profile.updated_media_count,
        "failed_media_count": profile.failed_media_count,
        "active_blockers": list(profile.active_blockers or []),
        "last_sync_status": profile.last_sync_status,
        "last_sync_at": profile.last_sync_at.isoformat() if profile.last_sync_at else None,
        "next_sync_at": profile.next_sync_at.isoformat() if profile.next_sync_at else None,
        "last_sync_summary": dict(profile.last_sync_summary or {}),
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }


# ------------------------------------------------------------------ #
# Прогоны                                                            #
# ------------------------------------------------------------------ #


def create_run(db: Session, **fields: Any) -> YandexAutoSyncRun:
    """Создать запись прогона синхронизации."""
    run = YandexAutoSyncRun(**fields)
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_run_by_id(db: Session, run_id: int) -> YandexAutoSyncRun | None:
    """Прогон по id (или None)."""
    return db.get(YandexAutoSyncRun, run_id)


def get_run_by_idempotency_key(db: Session, key: str) -> YandexAutoSyncRun | None:
    """Прогон по idempotency-ключу (для дедупликации воркер-прогонов)."""
    if not key:
        return None
    stmt = select(YandexAutoSyncRun).where(YandexAutoSyncRun.idempotency_key == key)
    return db.execute(stmt).scalars().first()


def update_run(db: Session, run: YandexAutoSyncRun, fields: dict[str, Any]) -> YandexAutoSyncRun:
    """Обновить произвольные поля прогона."""
    for key, value in fields.items():
        setattr(run, key, value)
    db.commit()
    db.refresh(run)
    return run


def mark_finished(
    db: Session, run: YandexAutoSyncRun, status: str, summary: dict[str, Any]
) -> YandexAutoSyncRun:
    """Отметить прогон завершённым с итоговым статусом и счётчиками."""
    fields = dict(summary)
    fields["status"] = status
    fields["finished_at"] = _now()
    return update_run(db, run, fields)


def mark_failed(db: Session, run: YandexAutoSyncRun, error: str | None) -> YandexAutoSyncRun:
    """Отметить прогон неуспешным (текст ошибки уже санитизирован)."""
    return update_run(
        db,
        run,
        {
            "status": "failed",
            "error_message": (error or "sync failed")[:512],
            "finished_at": _now(),
        },
    )


def list_runs_for_project(
    db: Session, project_id: int, limit: int = 100, offset: int = 0
) -> list[YandexAutoSyncRun]:
    """Прогоны синхронизации проекта (свежие первыми)."""
    stmt = (
        select(YandexAutoSyncRun)
        .where(YandexAutoSyncRun.project_id == project_id)
        .order_by(YandexAutoSyncRun.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def public_run_view(run: YandexAutoSyncRun) -> dict[str, Any]:
    """Безопасное представление прогона (без сырых путей/токенов; url — маской)."""
    return {
        "id": run.id,
        "project_id": run.project_id,
        "status": run.status,
        "source_type": run.source_type,
        "public_url_masked": run.public_url_masked,
        "root_folder": run.root_folder,
        "dry_run": run.dry_run,
        "files_seen": run.files_seen,
        "files_imported": run.files_imported,
        "files_updated": run.files_updated,
        "files_skipped": run.files_skipped,
        "files_failed": run.files_failed,
        "media_assets_created": run.media_assets_created,
        "media_assets_updated": run.media_assets_updated,
        "quality_snapshots_created": run.quality_snapshots_created,
        "fingerprints_created": run.fingerprints_created,
        "curation_tasks_created": run.curation_tasks_created,
        "blockers": list(run.blockers or []),
        "warnings": list(run.warnings or []),
        "error_message": run.error_message,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


def _mask_url(url: str | None) -> str | None:
    """Замаскировать публичную ссылку (показываем только домен + хвост)."""
    value = (url or "").strip()
    if not value:
        return None
    # https://disk.yandex.ru/d/abcdef123 → disk.yandex.ru/…c123
    import re

    m = re.search(r"https?://([^/]+)", value)
    domain = m.group(1) if m else value[:20]
    tail = value[-4:] if len(value) > 8 else ""
    return f"{domain}/…{tail}"
