"""Модель аккаунта/воркспейса SaaS-платформы (владелец + участники)."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Account(Base, TimestampMixin):
    """Рабочее пространство (workspace) — контейнер проектов и биллинга."""

    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    # active | suspended | deleted
    status: Mapped[str] = mapped_column(String(20), default="active", index=True, nullable=False)
