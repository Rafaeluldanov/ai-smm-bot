"""Модель переопределения email-шаблона (override) — v0.5.3.

Системные email-шаблоны живут в коде (``email_template_service``). Эта модель — foundation для
пер-аккаунт/проект переопределений: если override нет — используется системный шаблон. В MVP
редактирование выключено по умолчанию (``EMAIL_TEMPLATE_OVERRIDES_ENABLED=false``).

БЕЗОПАСНОСТЬ:
- ``subject/text/html`` санитизируются на сервисном слое; секретов/сырых токенов не хранит;
- строго account/project-scoped.
"""

from typing import Any

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.3): единые перечисления (Часть 1). --- #
EMAIL_TEMPLATE_TYPES: tuple[str, ...] = (
    "review_assigned",
    "review_mentioned",
    "review_comment",
    "review_changes_requested",
    "review_approved",
    "review_rejected",
    "task_overdue",
    "post_needs_review",
    "post_approved",
    "post_rejected",
    "experiment_suggestion_created",
    "experiment_winner_selected",
    "learning_profile_updated",
    "billing_balance_low",
    "digest_daily",
    "digest_weekly",
    "system_notice",
)
EMAIL_RENDER_FORMATS: tuple[str, ...] = ("text", "html", "both")
EMAIL_TEMPLATE_STATUSES: tuple[str, ...] = ("active", "draft", "disabled")
EMAIL_DELIVERY_MODES: tuple[str, ...] = ("preview", "mock", "smtp_live_blocked", "smtp_live")


class EmailTemplateOverride(Base, TimestampMixin):
    """Переопределение системного email-шаблона на уровне аккаунта/проекта (foundation)."""

    __tablename__ = "email_template_overrides"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="SET NULL"), index=True, default=None
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    template_type: Mapped[str] = mapped_column(
        String(40), index=True, default="system_notice", nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), index=True, default="active", nullable=False)

    subject_template: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    text_template: Mapped[str] = mapped_column(Text, default="", nullable=False)
    html_template: Mapped[str | None] = mapped_column(Text, default=None)
    variables_schema: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)

    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    override_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
