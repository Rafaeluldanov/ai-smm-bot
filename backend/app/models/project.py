"""Модель проекта (например, TEEON или «Фабрика сувениров»)."""

from sqlalchemy import Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin


class Project(Base, TimestampMixin):
    """Продвигаемый проект компании."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default=None)
    website_url: Mapped[str | None] = mapped_column(String(512), default=None)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
