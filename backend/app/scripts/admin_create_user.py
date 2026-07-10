"""CLI: создать пользователя (и опционально аккаунт). Пароль/хеш не печатаются."""

from __future__ import annotations

import argparse
import getpass
import sys

from sqlalchemy.orm import Session

from app.core.security import PasswordHasher
from app.db.session import get_sessionmaker
from app.repositories import account_repository, user_repository
from app.schemas.project import normalize_slug


class AdminUserError(Exception):
    """Ошибка создания пользователя (дубль email и т. п.)."""


def create_user_and_account(
    db: Session,
    email: str,
    password: str,
    full_name: str | None = None,
    account_name: str | None = None,
    superuser: bool = False,
) -> tuple[int, int | None]:
    """Создать пользователя (+ аккаунт-owner при account_name). Возврат (user_id, account_id)."""
    if len(password) < 8:
        raise AdminUserError("Пароль должен быть не короче 8 символов")
    if user_repository.get_user_by_email(db, email) is not None:
        raise AdminUserError(f"Пользователь с email уже существует: {email}")
    user = user_repository.create_user(
        db,
        email=email,
        password_hash=PasswordHasher().hash(password),
        full_name=full_name,
        is_superuser=superuser,
    )
    account_id: int | None = None
    if account_name:
        slug = normalize_slug(account_name)
        if account_repository.get_account_by_slug(db, slug) is not None:
            slug = f"{slug}-{user.id}"
        account = account_repository.create_account(
            db, name=account_name, slug=slug, owner_user_id=user.id
        )
        account_repository.create_membership(db, account.id, user.id, role="owner")
        account_id = account.id
    return user.id, account_id


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Создать пользователя (admin)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--password", default=None, help="Если не задан — спросит интерактивно")
    parser.add_argument("--full-name", default=None)
    parser.add_argument("--account-name", default=None, help="Создать аккаунт-воркспейс")
    parser.add_argument("--superuser", action="store_true")
    return parser


def main() -> None:
    """Точка входа CLI. Пароль в открытом виде не выводится."""
    args = build_parser().parse_args()
    password = args.password or getpass.getpass("Пароль: ")
    try:
        with get_sessionmaker()() as db:
            user_id, account_id = create_user_and_account(
                db,
                email=args.email,
                password=password,
                full_name=args.full_name,
                account_name=args.account_name,
                superuser=args.superuser,
            )
    except AdminUserError as exc:
        print(f"Ошибка: {exc}")
        sys.exit(1)

    print(f"Пользователь создан: user_id={user_id}")
    if account_id is not None:
        print(f"Аккаунт создан: account_id={account_id} (роль owner)")
    # Пароль/хеш НЕ печатаются.


if __name__ == "__main__":
    main()
