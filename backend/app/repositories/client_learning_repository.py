"""Репозиторий профилей обучения клиента (client_learning_profiles).

Профиль строго per-project (+ опционально per-platform). Данные одного клиента не
смешиваются с другим (все выборки фильтруют по ``project_id``).
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.client_learning_profile import ClientLearningProfile


def get_profile(
    db: Session, project_id: int, platform_key: str | None = None
) -> ClientLearningProfile | None:
    """Профиль (project × platform). ``platform_key=None`` — профиль всего проекта."""
    stmt = select(ClientLearningProfile).where(ClientLearningProfile.project_id == project_id)
    if platform_key is None:
        stmt = stmt.where(ClientLearningProfile.platform_key.is_(None))
    else:
        stmt = stmt.where(ClientLearningProfile.platform_key == platform_key)
    return db.scalars(stmt.order_by(ClientLearningProfile.id.desc())).first()


def list_profiles_for_project(db: Session, project_id: int) -> list[ClientLearningProfile]:
    """Все профили проекта (проектный + по площадкам)."""
    stmt = (
        select(ClientLearningProfile)
        .where(ClientLearningProfile.project_id == project_id)
        .order_by(ClientLearningProfile.id.asc())
    )
    return list(db.scalars(stmt).all())


def create_default_profile(
    db: Session,
    project_id: int,
    account_id: int | None = None,
    platform_key: str | None = None,
) -> ClientLearningProfile:
    """Создать пустой профиль по умолчанию (version=1, confidence=0)."""
    profile = ClientLearningProfile(
        account_id=account_id,
        project_id=project_id,
        platform_key=platform_key,
        profile_version=1,
        status="active",
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


def get_or_create_profile(
    db: Session,
    project_id: int,
    account_id: int | None = None,
    platform_key: str | None = None,
) -> ClientLearningProfile:
    """Вернуть существующий профиль или создать пустой."""
    existing = get_profile(db, project_id, platform_key)
    if existing is not None:
        return existing
    return create_default_profile(db, project_id, account_id, platform_key)


def upsert_profile(
    db: Session,
    project_id: int,
    account_id: int | None = None,
    platform_key: str | None = None,
    **fields: Any,
) -> ClientLearningProfile:
    """Создать/обновить профиль набором полей (без смены версии)."""
    profile = get_or_create_profile(db, project_id, account_id, platform_key)
    for field, value in fields.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


def update_profile_from_signals(
    db: Session, profile: ClientLearningProfile, **fields: Any
) -> ClientLearningProfile:
    """Обновить обученные поля профиля (веса/списки/счётчики)."""
    for field, value in fields.items():
        setattr(profile, field, value)
    db.commit()
    db.refresh(profile)
    return profile


def increment_version(db: Session, profile: ClientLearningProfile) -> ClientLearningProfile:
    """Поднять версию профиля на 1 (после пересчёта из событий)."""
    profile.profile_version = (profile.profile_version or 1) + 1
    db.commit()
    db.refresh(profile)
    return profile
