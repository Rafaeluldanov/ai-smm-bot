"""Модель подписки на webhook-уведомления — v0.5.2.

Клиент задаёт webhook URL и (опционально) signing secret. URL и секрет считаются
чувствительными: хранятся зашифрованно + masked/hash; наружу отдаётся ТОЛЬКО masked/hash.
Payload подписывается HMAC-SHA256. Реальный вызов выключен по умолчанию (mock preview).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.2). --- #
WEBHOOK_SUBSCRIPTION_STATUSES: tuple[str, ...] = (
    "draft",
    "active",
    "disabled",
    "suppressed",
    "failed",
    "revoked",
)
WEBHOOK_SIGNATURE_ALGORITHMS: tuple[str, ...] = ("hmac_sha256",)


class WebhookSubscription(Base, TimestampMixin):
    """Подписка на webhook: URL/secret хранятся encrypted + masked; live-вызов выключен."""

    __tablename__ = "webhook_subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    project_id: Mapped[int | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, default=None
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True, default=None
    )

    title: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    status: Mapped[str] = mapped_column(String(20), index=True, default="draft", nullable=False)

    url_masked: Mapped[str | None] = mapped_column(String(255), default=None)
    url_hash: Mapped[str | None] = mapped_column(String(64), index=True, default=None)
    url_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    signing_secret_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    signing_secret_masked: Mapped[str | None] = mapped_column(String(64), default=None)
    signature_algorithm: Mapped[str] = mapped_column(
        String(20), default="hmac_sha256", nullable=False
    )

    event_types: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_error: Mapped[str | None] = mapped_column(String(512), default=None)
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    subscription_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONType, default=dict, nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
