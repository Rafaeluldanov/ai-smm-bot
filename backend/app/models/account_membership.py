"""Модель членства пользователя в аккаунте (роль + статус)."""

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class AccountMembership(Base, TimestampMixin):
    """Связь пользователь↔аккаунт с ролью. Уникальна по (account_id, user_id)."""

    __tablename__ = "account_memberships"
    __table_args__ = (
        UniqueConstraint("account_id", "user_id", name="uq_account_membership_account_user"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # owner | admin | manager | viewer
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    # active | invited | disabled
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
