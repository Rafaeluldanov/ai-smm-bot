"""Сервис rate-limit доставки уведомлений — v0.5.2.

Локальный DB-backed лимитер (окно + счётчик) per (user, channel). Проверка read-only не
инкрементит; запись attempt — отдельно (на фактической доставке). Внешних вызовов нет.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.repositories import notification_safety_repository as safety_repo

if TYPE_CHECKING:
    from app.config import Settings


class NotificationRateLimitService:
    """Проверка/учёт лимитов доставки уведомлений (per user/channel)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def get_limits_for_channel(self, channel: str) -> tuple[int, int]:
        """Вернуть (window_seconds, limit_value) для канала."""
        s = self._resolve_settings()
        if channel == "email":
            return 3600, int(s.notification_rate_limit_email_per_hour or 20)
        if channel == "telegram":
            return 3600, int(s.notification_rate_limit_telegram_per_hour or 30)
        if channel == "webhook":
            return 3600, int(s.notification_rate_limit_webhook_per_hour or 60)
        if channel == "digest":
            return 86400, int(s.notification_rate_limit_digest_per_day or 2)
        return 3600, int(s.notification_rate_limit_email_per_hour or 20)

    def build_bucket_key(
        self,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        project_id: int | None = None,
        notification_type: str | None = None,
    ) -> str:
        """Собрать стабильный ключ бакета (per user+channel; provider/project — уточнение)."""
        parts = [f"u={user_id}", f"c={channel}"]
        if provider:
            parts.append(f"p={provider}")
        return "|".join(parts)

    def check_delivery_allowed(
        self,
        db: Session,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        project_id: int | None = None,
        notification_type: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Проверить лимит (без инкремента). Возвращает allowed/limit/count/remaining/reset_at."""
        if not self._enabled():
            return {"allowed": True, "enabled": False, "channel": channel}
        window, limit = self.get_limits_for_channel(channel)
        key = self.build_bucket_key(user_id, channel, provider, project_id, notification_type)
        bucket = safety_repo.get_or_create_bucket(
            db,
            key,
            window,
            limit,
            scope="user",
            user_id=user_id,
            account_id=account_id,
            project_id=project_id,
            channel=channel,
            provider=provider,
            notification_type=notification_type,
        )
        allowed = bucket.count < bucket.limit_value
        return {
            "allowed": allowed,
            "enabled": True,
            "channel": channel,
            "limit": bucket.limit_value,
            "count": bucket.count,
            "remaining": max(0, bucket.limit_value - bucket.count),
            "reset_at": bucket.reset_at.isoformat() if bucket.reset_at else None,
            "scope": bucket.scope,
        }

    def record_delivery_attempt(
        self,
        db: Session,
        user_id: int | None,
        channel: str,
        provider: str | None = None,
        project_id: int | None = None,
        notification_type: str | None = None,
        account_id: int | None = None,
    ) -> dict[str, Any]:
        """Учесть одну попытку доставки (инкремент бакета)."""
        if not self._enabled():
            return {"recorded": False, "enabled": False}
        window, limit = self.get_limits_for_channel(channel)
        key = self.build_bucket_key(user_id, channel, provider, project_id, notification_type)
        bucket = safety_repo.get_or_create_bucket(
            db,
            key,
            window,
            limit,
            scope="user",
            user_id=user_id,
            account_id=account_id,
            project_id=project_id,
            channel=channel,
            provider=provider,
            notification_type=notification_type,
        )
        safety_repo.increment_bucket(db, bucket)
        return {"recorded": True, "count": bucket.count, "limit": bucket.limit_value}

    def build_rate_limit_dashboard(
        self, db: Session, project_id: int | None = None, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сводка бакетов лимитов (для UI)."""
        buckets = safety_repo.list_buckets(db, user_id=user_id, project_id=project_id)
        rows = [
            {
                "channel": b.channel,
                "scope": b.scope,
                "count": b.count,
                "limit": b.limit_value,
                "remaining": max(0, b.limit_value - b.count),
                "reset_at": b.reset_at.isoformat() if b.reset_at else None,
            }
            for b in buckets
        ]
        return {
            "project_id": project_id,
            "user_id": user_id,
            "enabled": self._enabled(),
            "buckets": rows,
        }

    def _enabled(self) -> bool:
        return bool(self._resolve_settings().notification_rate_limit_enabled_effective)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings


def get_notification_rate_limit_service() -> NotificationRateLimitService:
    """DI-фабрика сервиса rate-limit."""
    return NotificationRateLimitService()
