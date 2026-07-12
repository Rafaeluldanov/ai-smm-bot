"""HTTP-гарды tenant-изоляции для FastAPI-роутов (аккаунт/проект/счёт/платформа).

Двухуровневая модель (безопасная и обратно совместимая):
- **Аутентифицированный** запрос — доступ проверяется строго: пользователь должен быть
  владельцем/участником аккаунта ресурса, иначе **404** (существование чужих ресурсов не
  раскрывается). Роли owner/admin требуются для изменения billing-профиля и т. п.
- **Анонимный** запрос — допускается только вне production (dev/local), где сохраняется
  back-compat для существующих тестов и локальной разработки. В production (или при
  ``security_require_auth=true``) анонимный доступ к защищённым роутам → **401**.

Секреты здесь не участвуют — гарды только сверяют владение. Вебхуки провайдеров НЕ
используют эти гарды (проверяются подписью/идемпотентностью, не токеном пользователя).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_user
from app.config import Settings, get_settings
from app.models.account import Account
from app.models.user import User
from app.repositories import (
    account_repository,
    content_experiment_repository,
    crm_bot_smm_repository,
    experiment_suggestion_repository,
    payment_repository,
    post_publication_repository,
    post_repository,
    project_repository,
)
from app.services import saas_security_service as security

DbSession = Annotated[Session, Depends(get_db)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
_AUTH_REQUIRED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED, detail="Требуется авторизация"
)


def _auth_required(settings: Settings) -> bool:
    """Требовать ли авторизацию на защищённых роутах (prod — всегда)."""
    return settings.is_production or settings.security_require_auth


def _account_role(db: Session, user: User, account: Account) -> str | None:
    if account.owner_user_id == user.id:
        return "owner"
    membership = account_repository.get_membership(db, account.id, user.id)
    return membership.role if membership is not None else None


def _guard_account(
    db: Session, settings: Settings, user: User | None, account_id: int, *, need_admin: bool = False
) -> None:
    """Проверить доступ к аккаунту (или права owner/admin) с учётом двух уровней."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return  # dev/local анонимно — back-compat
    account = account_repository.get_account_by_id(db, account_id)
    if account is None or not security.user_can_access_account(db, user, account_id):
        raise _NOT_FOUND
    if account.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт неактивен")
    if need_admin and _account_role(db, user, account) not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права владельца или администратора аккаунта",
        )


def _guard_project(db: Session, settings: Settings, user: User | None, project_id: int) -> None:
    """Проверить доступ к проекту (в т. ч. legacy-проекты без account_id)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return  # dev/local анонимно — back-compat
    project = project_repository.get_project_by_id(db, project_id)
    if project is None:
        raise _NOT_FOUND
    if project.account_id is None:
        # Legacy/seed-проект: в production скрываем, в dev — доступен.
        if settings.is_production and settings.security_hide_legacy_projects_in_prod:
            raise _NOT_FOUND
        return
    if not security.user_can_access_account(db, user, project.account_id):
        raise _NOT_FOUND


# --- Публичные guard-зависимости (используются в маршрутах) --- #


def require_account_member(
    account_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к аккаунту только участнику/владельцу (или dev-анонимно)."""
    _guard_account(db, settings, user, account_id)


def require_account_owner_or_admin(
    account_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: только owner/admin аккаунта (billing-профиль, опасные действия)."""
    _guard_account(db, settings, user, account_id, need_admin=True)


def require_project_access(
    project_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к проекту только участнику его аккаунта (или dev-анонимно)."""
    _guard_project(db, settings, user, project_id)


def require_project_platform_access(
    project_id: int, platform: str, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард платформенного воркспейса: доступ к проекту (платформа — из его конфига)."""
    _guard_project(db, settings, user, project_id)


def require_invoice_access(
    invoice_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: счёт принадлежит аккаунту текущего пользователя."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    invoice = payment_repository.get_invoice(db, invoice_id)
    if invoice is None or not security.user_can_access_account(db, user, invoice.account_id):
        raise _NOT_FOUND


def require_post_access(
    post_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к посту (через проект → аккаунт) для аналитики."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    post = post_repository.get_post_by_id(db, post_id)
    if post is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, post.project_id)


def require_publication_access(
    publication_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к публикации (через пост → проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    publication = post_publication_repository.get_publication_by_id(db, publication_id)
    if publication is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, publication.project_id)


def require_experiment_access(
    experiment_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к эксперименту (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    experiment = content_experiment_repository.get_experiment_by_id(db, experiment_id)
    if experiment is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, experiment.project_id)


def require_variant_access(
    variant_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к варианту эксперимента (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    variant = content_experiment_repository.get_variant_by_id(db, variant_id)
    if variant is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, variant.project_id)


def require_suggestion_access(
    suggestion_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: доступ к предложению эксперимента (через проект → аккаунт)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    suggestion = experiment_suggestion_repository.get_by_id(db, suggestion_id)
    if suggestion is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, suggestion.project_id)


def require_vk_resource_access(
    resource_id: int, db: DbSession, user: OptionalUser, settings: SettingsDep
) -> None:
    """Гард: VK-ресурс принадлежит проекту/аккаунту пользователя (status/check)."""
    if user is None:
        if _auth_required(settings):
            raise _AUTH_REQUIRED
        return
    resource = crm_bot_smm_repository.get_resource_by_id(db, resource_id)
    if resource is None:
        raise _NOT_FOUND
    _guard_project(db, settings, user, resource.project_id)


def guard_account_in_body(
    db: Session, settings: Settings, user: User | None, account_id: int
) -> None:
    """In-route гард для роутов с account_id в теле запроса (onboarding/analytics run)."""
    _guard_account(db, settings, user, account_id)


def guard_project_in_body(
    db: Session, settings: Settings, user: User | None, project_id: int
) -> None:
    """In-route гард для роутов с project_id в теле запроса."""
    _guard_project(db, settings, user, project_id)
