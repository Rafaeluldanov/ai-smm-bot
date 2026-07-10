"""Тесты tenant-изоляции SaaS (offline, без сети/секретов).

Проверяют guard-функции доступа: пользователь видит только свои аккаунты/проекты;
чужой доступ запрещён; проект без account_id никому не принадлежит. Плюс маскировка
секретов на уровне сервиса секретов.
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.crm_secret_service import mask_secret
from app.services.saas_security_service import (
    SaasAccessError,
    assert_user_can_access_account,
    assert_user_can_access_project,
    user_can_access_account,
    user_can_access_project,
)


def _user(db: Session, email: str):  # noqa: ANN202 - тестовый помощник
    return user_repository.create_user(db, email=email, password_hash="x")


def _account_with_project(db: Session, owner, name: str, slug: str):  # noqa: ANN001,ANN202
    account = account_repository.create_account(db, name=name, slug=slug, owner_user_id=owner.id)
    account_repository.create_membership(db, account.id, owner.id, role="owner")
    project = project_repository.create_project(db, ProjectCreate(name=name, slug=slug + "-proj"))
    project.account_id = account.id
    db.commit()
    db.refresh(project)
    return account, project


def test_owner_can_access_own_account_and_project(db_session: Session) -> None:
    owner = _user(db_session, "owner@example.com")
    account, project = _account_with_project(db_session, owner, "A", "acc-a")
    assert user_can_access_account(db_session, owner, account.id) is True
    assert user_can_access_project(db_session, owner, project) is True
    assert assert_user_can_access_account(db_session, owner, account.id).id == account.id
    assert assert_user_can_access_project(db_session, owner, project.id).id == project.id


def test_user_a_cannot_access_user_b_project(db_session: Session) -> None:
    user_a = _user(db_session, "a@example.com")
    user_b = _user(db_session, "b@example.com")
    _account_a, project_a = _account_with_project(db_session, user_a, "A", "acc-a")

    # B не входит в аккаунт A — доступа к проекту A нет.
    assert user_can_access_project(db_session, user_b, project_a) is False
    with pytest.raises(SaasAccessError):
        assert_user_can_access_project(db_session, user_b, project_a.id)


def test_user_a_cannot_access_user_b_account(db_session: Session) -> None:
    user_a = _user(db_session, "a2@example.com")
    user_b = _user(db_session, "b2@example.com")
    account_a, _project = _account_with_project(db_session, user_a, "A", "acc-a2")

    assert user_can_access_account(db_session, user_b, account_a.id) is False
    with pytest.raises(SaasAccessError):
        assert_user_can_access_account(db_session, user_b, account_a.id)


def test_member_can_access_shared_account(db_session: Session) -> None:
    owner = _user(db_session, "owner3@example.com")
    member = _user(db_session, "member3@example.com")
    account, project = _account_with_project(db_session, owner, "A", "acc-a3")
    account_repository.create_membership(db_session, account.id, member.id, role="manager")

    assert user_can_access_account(db_session, member, account.id) is True
    assert user_can_access_project(db_session, member, project) is True


def test_project_without_account_is_not_accessible(db_session: Session) -> None:
    user = _user(db_session, "orphan@example.com")
    project = project_repository.create_project(
        db_session, ProjectCreate(name="Orphan", slug="orphan")
    )
    assert project.account_id is None
    assert user_can_access_project(db_session, user, project) is False


def test_secret_masking_hides_value() -> None:
    masked = mask_secret("super-secret-token-1234")
    assert "super-secret-token" not in masked
    assert masked.endswith("1234")  # видно только хвост
    assert masked.startswith("•")
