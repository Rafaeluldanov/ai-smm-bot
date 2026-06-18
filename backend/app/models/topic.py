"""Модель темы публикации, выбираемой ботом."""

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin


class Topic(Base, TimestampMixin):
    """Тема для будущего поста (выбирается ботом, не человеком).

    Это РЕКОМЕНДОВАННАЯ/выбранная тема, а не готовый пост. Бизнес-уникальность —
    пара (project_id, title): один и тот же заголовок в проекте не дублируется.
    """

    __tablename__ = "topics"
    __table_args__ = (Index("ix_topics_project_id_title", "project_id", "title", unique=True),)

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    # Тематический кластер (группа близких тем), например "худи".
    cluster: Mapped[str | None] = mapped_column(String(255), index=True, default=None)

    # Итоговый приоритет, рассчитанный ботом (0..100): SEO + тренды + сезонность + медиа.
    priority_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    # Бизнес-приоритет направления (стратегические направления месяца).
    business_priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    seo_keywords: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)

    # Статус: "candidate" | "recommended" | "planned" | "archived"
    status: Mapped[str] = mapped_column(String(50), default="candidate", index=True, nullable=False)
