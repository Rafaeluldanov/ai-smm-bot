"""Tenant-изоляция SaaS: проверки доступа пользователя к аккаунту/проекту.

Единая точка проверок «свой/чужой». Пользователь видит только те аккаунты, где он
владелец или участник (``AccountMembership``), и только проекты этих аккаунтов.
Проверки — чистые guard-функции, которые бросают ``SaasAccessError`` (маппится в
HTTP 403). Секреты здесь не участвуют; функции только сверяют владение.

ВАЖНО: устаревшие/сид-проекты могут иметь ``account_id=None`` (не привязаны к
аккаунту). Такой проект не принадлежит никому — доступ к нему решает вызывающий код
(guard возвращает False для любого пользователя, кроме явного обхода).
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.project import Project
from app.models.user import User
from app.repositories import account_repository, project_repository


class SaasAccessError(Exception):
    """Пользователь не имеет доступа к аккаунту/проекту (→ HTTP 403)."""


def user_can_access_account(db: Session, user: User, account_id: int) -> bool:
    """True, если пользователь владелец или участник аккаунта."""
    account = account_repository.get_account_by_id(db, account_id)
    if account is None:
        return False
    if account.owner_user_id == user.id:
        return True
    return account_repository.get_membership(db, account_id, user.id) is not None


def user_can_access_project(db: Session, user: User, project: Project) -> bool:
    """True, если проект привязан к доступному пользователю аккаунту."""
    if project.account_id is None:
        # Проект не привязан к аккаунту — не принадлежит ни одному tenant.
        return False
    return user_can_access_account(db, user, project.account_id)


def assert_user_can_access_account(db: Session, user: User, account_id: int) -> Account:
    """Проверить доступ к аккаунту или бросить ``SaasAccessError``."""
    if not user_can_access_account(db, user, account_id):
        raise SaasAccessError(f"Нет доступа к аккаунту #{account_id}")
    account = account_repository.get_account_by_id(db, account_id)
    assert account is not None  # доступ уже подтверждён выше
    return account


def assert_user_can_access_project(db: Session, user: User, project_id: int) -> Project:
    """Проверить доступ к проекту или бросить ``SaasAccessError``."""
    project = project_repository.get_project_by_id(db, project_id)
    if project is None or not user_can_access_project(db, user, project):
        raise SaasAccessError(f"Нет доступа к проекту #{project_id}")
    return project
