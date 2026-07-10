"""CLI: выдать/изменить роль пользователя в аккаунте (+ запись в аудит)."""

from __future__ import annotations

import argparse
import sys

from sqlalchemy.orm import Session

from app.db.session import get_sessionmaker
from app.repositories import account_repository, user_repository
from app.services.audit_log_service import AuditLogService

# owner/admin — управление; manager(member) — работа; viewer — только чтение.
_ROLES = {"owner", "admin", "manager", "member", "viewer"}


class AdminRoleError(Exception):
    """Ошибка выдачи роли (нет аккаунта/пользователя/неизвестная роль)."""


def grant_role(db: Session, account_id: int, user_id: int, role: str) -> bool:
    """Выдать/обновить роль пользователя в аккаунте. Возврат: создано ли членство."""
    if role not in _ROLES:
        raise AdminRoleError(f"Неизвестная роль: {role} (доступно: {sorted(_ROLES)})")
    if account_repository.get_account_by_id(db, account_id) is None:
        raise AdminRoleError(f"Аккаунт не найден: {account_id}")
    if user_repository.get_user_by_id(db, user_id) is None:
        raise AdminRoleError(f"Пользователь не найден: {user_id}")
    membership = account_repository.get_membership(db, account_id, user_id)
    if membership is None:
        account_repository.create_membership(db, account_id, user_id, role=role)
        created = True
    else:
        membership.role = role
        db.commit()
        created = False
    AuditLogService().record(
        db,
        "account.role.granted",
        account_id=account_id,
        user_id=user_id,
        entity_type="membership",
        entity_id=user_id,
        metadata={"role": role, "created": created},
    )
    return created


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Выдать роль в аккаунте (admin)")
    parser.add_argument("--account-id", type=int, required=True)
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--role", required=True, choices=sorted(_ROLES))
    return parser


def main() -> None:
    """Точка входа CLI."""
    args = build_parser().parse_args()
    try:
        with get_sessionmaker()() as db:
            created = grant_role(db, args.account_id, args.user_id, args.role)
    except AdminRoleError as exc:
        print(f"Ошибка: {exc}")
        sys.exit(1)

    action = "создано членство" if created else "роль обновлена"
    print(
        f"Готово: {action} — account_id={args.account_id}, user_id={args.user_id}, role={args.role}"
    )


if __name__ == "__main__":
    main()
