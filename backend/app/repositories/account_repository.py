"""Репозиторий аккаунтов (workspace) и членств."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.account import Account
from app.models.account_membership import AccountMembership


def get_account_by_id(db: Session, account_id: int) -> Account | None:
    """Вернуть аккаунт по id или None."""
    return db.get(Account, account_id)


def get_account_by_slug(db: Session, slug: str) -> Account | None:
    """Вернуть аккаунт по slug или None."""
    return db.scalars(select(Account).where(Account.slug == slug)).first()


def create_account(db: Session, name: str, slug: str, owner_user_id: int) -> Account:
    """Создать аккаунт с владельцем."""
    account = Account(name=name, slug=slug, owner_user_id=owner_user_id, status="active")
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def create_membership(
    db: Session, account_id: int, user_id: int, role: str = "owner", status: str = "active"
) -> AccountMembership:
    """Создать членство пользователя в аккаунте."""
    membership = AccountMembership(account_id=account_id, user_id=user_id, role=role, status=status)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def get_membership(db: Session, account_id: int, user_id: int) -> AccountMembership | None:
    """Вернуть членство по (account_id, user_id) или None."""
    stmt = select(AccountMembership).where(
        AccountMembership.account_id == account_id, AccountMembership.user_id == user_id
    )
    return db.scalars(stmt).first()


def list_accounts_for_user(db: Session, user_id: int) -> list[Account]:
    """Вернуть аккаунты, в которых состоит пользователь (по членствам)."""
    stmt = (
        select(Account)
        .join(AccountMembership, AccountMembership.account_id == Account.id)
        .where(AccountMembership.user_id == user_id)
        .order_by(Account.id)
    )
    return list(db.scalars(stmt).all())


def list_memberships_for_account(db: Session, account_id: int) -> list[AccountMembership]:
    """Вернуть членства аккаунта."""
    stmt = (
        select(AccountMembership)
        .where(AccountMembership.account_id == account_id)
        .order_by(AccountMembership.id)
    )
    return list(db.scalars(stmt).all())
