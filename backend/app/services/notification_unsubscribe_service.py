"""Сервис отписки (unsubscribe/opt-out) — v0.5.2.

Выдаёт и проверяет токен отписки (HMAC-SHA256 + base64url JSON, как auth_token_service),
создаёт opt-out из токена или напрямую (для авторизованного пользователя). Токены и секреты
НИКОГДА не логируются; некорректный токен → None (детали не раскрываются).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.notification_opt_out import NOTIFICATION_OPT_OUT_SCOPES
from app.repositories import notification_safety_repository as safety_repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.models.notification_opt_out import NotificationOptOut
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_VALID_CHANNELS = ("email", "telegram", "webhook", "digest", "in_app")


class NotificationUnsubscribeError(Exception):
    """Ошибка отписки (нет доступа/сущности/невалидный токен) — API → 400/404."""


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


class NotificationUnsubscribeService:
    """Отписка через токен или напрямую (opt-out) + отзыв. Без утечки токенов/секретов."""

    def __init__(
        self, audit_service: AuditLogService | None = None, settings: Settings | None = None
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # --- Токены --- #

    def issue_unsubscribe_token(
        self,
        user_id: int,
        scope: str,
        channel: str | None = None,
        project_id: int | None = None,
        notification_type: str | None = None,
    ) -> str:
        """Выдать подписанный токен отписки (HMAC-SHA256)."""
        scope = scope if scope in NOTIFICATION_OPT_OUT_SCOPES else "global"
        now = int(time.time())
        payload = {
            "uid": user_id,
            "scope": scope,
            "ch": channel,
            "pid": project_id,
            "nt": notification_type,
            "iat": now,
            "exp": now + self._token_ttl_seconds(),
        }
        body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
        sig = self._sign(body)
        return f"{body}.{sig}"

    def verify_unsubscribe_token(self, token: str) -> dict[str, Any] | None:
        """Проверить токен отписки. Возвращает payload или None (невалиден/просрочен)."""
        try:
            body, _, sig = (token or "").partition(".")
            if not body or not sig:
                return None
            expected = self._sign(body)
            if not hmac.compare_digest(sig, expected):
                return None
            payload = json.loads(_b64url_decode(body).decode("utf-8"))
            if not isinstance(payload, dict):
                return None
            if int(payload.get("exp", 0)) < int(time.time()):
                return None
            return payload
        except Exception:  # noqa: BLE001 — невалидный токен не роняет запрос
            return None

    def build_unsubscribe_url(self, token: str) -> str:
        """Собрать URL отписки (относительный, без утечки токена в логи)."""
        base = str(getattr(self._resolve_settings(), "app_base_url", "") or "").rstrip("/")
        return f"{base}/unsubscribe?token={token}"

    # --- Opt-out --- #

    def create_opt_out_from_token(
        self, db: Session, token: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Создать opt-out из токена (для публичной страницы отписки)."""
        payload = self.verify_unsubscribe_token(token)
        if payload is None:
            raise NotificationUnsubscribeError("Недействительная ссылка отписки")
        return self._create_opt_out(
            db,
            user_id=int(payload["uid"]),
            scope=str(payload.get("scope", "global")),
            channel=payload.get("ch"),
            project_id=payload.get("pid"),
            notification_type=payload.get("nt"),
            reason=reason or "unsubscribe_link",
            created_by_user_id=None,
        )

    def create_opt_out(
        self,
        db: Session,
        user_id: int,
        scope: str,
        channel: str | None = None,
        project_id: int | None = None,
        notification_type: str | None = None,
        reason: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать opt-out напрямую (для авторизованного пользователя)."""
        return self._create_opt_out(
            db,
            user_id=user_id,
            scope=scope,
            channel=channel,
            project_id=project_id,
            notification_type=notification_type,
            reason=reason,
            created_by_user_id=current_user_id,
        )

    def revoke_opt_out(
        self, db: Session, opt_out_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отменить отписку (только владелец)."""
        opt_out = safety_repo.get_opt_out_by_id(db, opt_out_id)
        if opt_out is None:
            raise NotificationUnsubscribeError("Отписка не найдена")
        if current_user_id is not None and opt_out.user_id != current_user_id:
            raise NotificationUnsubscribeError("Нет доступа к отписке")
        safety_repo.revoke_opt_out(db, opt_out, current_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_OPT_OUT_REVOKED,
            opt_out,
            {"opt_out_id": opt_out.id},
        )
        return self._view(opt_out)

    def list_opt_outs(
        self, db: Session, user_id: int, status: str = "active"
    ) -> list[dict[str, Any]]:
        """Отписки пользователя (view без секретов)."""
        rows = safety_repo.list_opt_outs_for_user(db, user_id, status=status)
        return [self._view(o) for o in rows]

    # --- Внутреннее --- #

    def _create_opt_out(
        self,
        db: Session,
        user_id: int,
        scope: str,
        channel: str | None,
        project_id: int | None,
        notification_type: str | None,
        reason: str | None,
        created_by_user_id: int | None,
    ) -> dict[str, Any]:
        if scope not in NOTIFICATION_OPT_OUT_SCOPES:
            raise NotificationUnsubscribeError(f"Недопустимый scope: {scope}")
        if channel is not None and channel not in _VALID_CHANNELS:
            raise NotificationUnsubscribeError(f"Недопустимый канал: {channel}")
        account_id = self._account_id(db, project_id)
        opt_out = safety_repo.create_opt_out(
            db,
            user_id=user_id,
            account_id=account_id,
            project_id=project_id,
            channel=channel,
            notification_type=notification_type,
            scope=scope,
            reason=(reason or "")[:255] or None,
            status="active",
            created_by_user_id=created_by_user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_NOTIFICATION_OPT_OUT_CREATED,
            opt_out,
            {"opt_out_id": opt_out.id, "scope": scope, "channel": channel},
        )
        return self._view(opt_out)

    @staticmethod
    def _view(opt_out: NotificationOptOut) -> dict[str, Any]:
        return {
            "id": opt_out.id,
            "user_id": opt_out.user_id,
            "account_id": opt_out.account_id,
            "project_id": opt_out.project_id,
            "channel": opt_out.channel,
            "notification_type": opt_out.notification_type,
            "scope": opt_out.scope,
            "reason": opt_out.reason,
            "status": opt_out.status,
            "created_at": opt_out.created_at.isoformat() if opt_out.created_at else None,
        }

    def _account_id(self, db: Session, project_id: int | None) -> int | None:
        if project_id is None:
            return None
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _sign(self, body: str) -> str:
        secret = self._resolve_settings().notification_unsubscribe_token_secret_effective
        mac = hmac.new(secret.encode("utf-8"), body.encode("ascii"), hashlib.sha256).digest()
        return _b64url_encode(mac)

    def _token_ttl_seconds(self) -> int:
        return int(self._resolve_settings().notification_unsubscribe_token_ttl_seconds)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self, db: Session, action: str, opt_out: NotificationOptOut, extra: dict[str, Any]
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=opt_out.account_id,
            project_id=opt_out.project_id,
            user_id=opt_out.user_id,
            entity_type="notification_opt_out",
            metadata=extra,
        )


def get_notification_unsubscribe_service() -> NotificationUnsubscribeService:
    """DI-фабрика сервиса отписки."""
    return NotificationUnsubscribeService()
