"""Базовый класс моделей и общие типы/миксины.

JSON-поля используют ``JSONB`` на PostgreSQL и обычный ``JSON`` на других СУБД
(например, SQLite в тестах) благодаря ``with_variant``.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Тип для JSON-полей, совместимый с PostgreSQL (JSONB) и прочими СУБД (JSON).
JSONType = JSON().with_variant(JSONB, "postgresql")


class Base(DeclarativeBase):
    """Базовый декларативный класс для всех моделей."""


class TimestampMixin:
    """Поля created_at / updated_at для моделей."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
