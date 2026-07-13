"""Репозиторий переопределений email-шаблонов (v0.5.3).

Хранит per-account/project override шаблонов. Секретов/сырых токенов не хранит (санитизация —
на сервисном слое). Если override нет — сервис берёт системный шаблон. Изоляция — на API/сервисе.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.email_template_override import (
    EMAIL_TEMPLATE_TYPES,
    EmailTemplateOverride,
)


def _now() -> datetime:
    return datetime.now(UTC)


def create_override(db: Session, **fields: Any) -> EmailTemplateOverride:
    """Создать override шаблона (subject/text/html санитизированы сервисом)."""
    override = EmailTemplateOverride(**fields)
    db.add(override)
    db.commit()
    db.refresh(override)
    return override


def get_override(db: Session, override_id: int) -> EmailTemplateOverride | None:
    """Override по id (или None)."""
    return db.get(EmailTemplateOverride, override_id)


def get_effective_template(
    db: Session,
    template_type: str,
    project_id: int | None = None,
    account_id: int | None = None,
) -> EmailTemplateOverride | None:
    """Активный override для (template_type, project|account) или None (→ системный шаблон).

    Приоритет: project-override > account-override.
    """
    stmt = select(EmailTemplateOverride).where(
        EmailTemplateOverride.template_type == template_type,
        EmailTemplateOverride.status == "active",
    )
    if project_id is not None:
        row = db.scalars(
            stmt.where(EmailTemplateOverride.project_id == project_id).order_by(
                EmailTemplateOverride.id.desc()
            )
        ).first()
        if row is not None:
            return row
    if account_id is not None:
        row = db.scalars(
            stmt.where(
                EmailTemplateOverride.account_id == account_id,
                EmailTemplateOverride.project_id.is_(None),
            ).order_by(EmailTemplateOverride.id.desc())
        ).first()
        if row is not None:
            return row
    return None


def list_overrides(
    db: Session,
    account_id: int | None = None,
    project_id: int | None = None,
    status: str | None = None,
    limit: int = 200,
) -> list[EmailTemplateOverride]:
    """Список override по аккаунту/проекту/статусу."""
    stmt = select(EmailTemplateOverride)
    if account_id is not None:
        stmt = stmt.where(EmailTemplateOverride.account_id == account_id)
    if project_id is not None:
        stmt = stmt.where(EmailTemplateOverride.project_id == project_id)
    if status is not None:
        stmt = stmt.where(EmailTemplateOverride.status == status)
    stmt = stmt.order_by(EmailTemplateOverride.id.desc()).limit(limit)
    return list(db.scalars(stmt).all())


def update_override(
    db: Session, override: EmailTemplateOverride, **fields: Any
) -> EmailTemplateOverride:
    """Обновить поля override."""
    for key, value in fields.items():
        setattr(override, key, value)
    override.updated_at = _now()
    db.commit()
    db.refresh(override)
    return override


def disable_override(
    db: Session, override: EmailTemplateOverride, current_user_id: int | None = None
) -> EmailTemplateOverride:
    """Отключить override (снова используется системный шаблон)."""
    override.status = "disabled"
    override.updated_by_user_id = current_user_id
    db.commit()
    db.refresh(override)
    return override


def list_template_types() -> tuple[str, ...]:
    """Все известные типы email-шаблонов."""
    return EMAIL_TEMPLATE_TYPES
