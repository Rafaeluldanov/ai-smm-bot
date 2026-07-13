"""Сервис Telegram-шаблонов уведомлений — v0.5.4.

Короткие текстовые шаблоны для Telegram (в отличие от email — компактнее, plain text по
умолчанию). Рендеринг — безопасная подстановка ``{{ variable }}`` (без Jinja): неизвестные
переменные → пустая строка. Текст санитизируется (секреты/токены убираются), нормализуется по
пробелам и обрезается до лимита символов. parse_mode по умолчанию ``none`` (без markdown).

БЕЗОПАСНОСТЬ:
- финальный текст проходит ``redact_sensitive_text`` (секреты/токены-провайдеров замаскированы);
- никаких bot token / chat_id / сырых токенов в шаблонах и результате.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text
from app.models.notification_telegram_binding import TELEGRAM_TEMPLATE_TYPES
from app.repositories import (
    account_repository,
    notification_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    notification_delivery_repository as delivery_repo,
)
from app.services import audit_log_service as audit_actions
from app.services.notification_service import sanitize_text

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_INTERNAL_PATH_RE = re.compile(
    r"(?i)(?:disk:/\S+|/(?:Users|home|var|etc|tmp|mnt|srv|opt|root)/\S+|[A-Za-z]:\\\S+)"
)
_WS_RE = re.compile(r"[ \t]+")
_MULTI_NL_RE = re.compile(r"\n{3,}")
_FALLBACK_TEMPLATE = "system_notice"

# Короткие Telegram-шаблоны (subject — заголовок для лога; text — тело сообщения). {{ var }}.
SYSTEM_TEMPLATES: dict[str, dict[str, str]] = {
    "review_assigned": {
        "purpose": "Вам назначена задача ревью",
        "subject": "Задача ревью: {{ title }}",
        "text": (
            "🔔 {{ app_name }}: вам назначена задача ревью в «{{ project_name }}».\n"
            "{{ title }}\n{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "review_mentioned": {
        "purpose": "Вас упомянули в комментарии",
        "subject": "Упоминание: {{ title }}",
        "text": (
            "💬 {{ app_name }}: вас упомянули в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "review_comment": {
        "purpose": "Новый комментарий ревью",
        "subject": "Комментарий: {{ title }}",
        "text": (
            "💬 {{ app_name }}: новый комментарий в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "review_changes_requested": {
        "purpose": "Запрошены правки",
        "subject": "Правки: {{ title }}",
        "text": (
            "✏️ {{ app_name }}: по посту запрошены правки в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "review_approved": {
        "purpose": "Пост одобрен",
        "subject": "Одобрено: {{ title }}",
        "text": (
            "✅ {{ app_name }}: пост одобрен в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "review_rejected": {
        "purpose": "Пост отклонён",
        "subject": "Отклонено: {{ title }}",
        "text": (
            "❌ {{ app_name }}: пост отклонён в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "task_overdue": {
        "purpose": "Задача просрочена",
        "subject": "Просрочено: {{ title }}",
        "text": (
            "⏰ {{ app_name }}: задача просрочена в «{{ project_name }}» "
            "(приоритет {{ priority }}).\n{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "post_needs_review": {
        "purpose": "Пост ждёт ревью",
        "subject": "Пост ждёт ревью: {{ title }}",
        "text": (
            "📝 {{ app_name }}: новый пост ждёт ревью в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "experiment_suggestion_created": {
        "purpose": "Новые A/B-предложения",
        "subject": "A/B-предложения: {{ project_name }}",
        "text": (
            "🧪 {{ app_name }}: новые A/B-предложения в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "experiment_winner_selected": {
        "purpose": "Выбран победитель эксперимента",
        "subject": "Победитель A/B: {{ project_name }}",
        "text": (
            "🏆 {{ app_name }}: выбран победитель эксперимента в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "learning_profile_updated": {
        "purpose": "Профиль обучения обновлён",
        "subject": "Обучение обновлено: {{ project_name }}",
        "text": (
            "📚 {{ app_name }}: профиль обучения обновлён в «{{ project_name }}».\n"
            "{{ message }}\nОткрыть: {{ action_url }}"
        ),
    },
    "billing_balance_low": {
        "purpose": "Низкий баланс",
        "subject": "Низкий баланс units",
        "text": (
            "💳 {{ app_name }}: низкий баланс units.\n{{ message }}\nПополнить: {{ action_url }}"
        ),
    },
    "digest_daily": {
        "purpose": "Ежедневный дайджест",
        "subject": "Ежедневный дайджест",
        "text": (
            "🗒 {{ app_name }}: ежедневный дайджест — {{ digest_count }} уведомлений.\n"
            "{{ digest_body }}"
        ),
    },
    "digest_weekly": {
        "purpose": "Еженедельный дайджест",
        "subject": "Еженедельный дайджест",
        "text": (
            "🗓 {{ app_name }}: еженедельный дайджест — {{ digest_count }} уведомлений.\n"
            "{{ digest_body }}"
        ),
    },
    "system_notice": {
        "purpose": "Системное уведомление",
        "subject": "{{ title }}",
        "text": "🔔 {{ app_name }}: {{ message }}\n{{ action_url }}",
    },
}


class TelegramTemplateError(Exception):
    """Ошибка рендеринга Telegram-шаблона (нет доступа/сущности) — API → 400/404."""


class TelegramNotificationTemplateService:
    """Системные Telegram-шаблоны + рендеринг notification/digest (короткий plain text)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Шаблоны                                                            #
    # ------------------------------------------------------------------ #

    def get_system_template(self, template_type: str) -> dict[str, str]:
        """Системный шаблон по типу (или заглушка system_notice)."""
        if template_type in SYSTEM_TEMPLATES:
            return SYSTEM_TEMPLATES[template_type]
        return dict(SYSTEM_TEMPLATES[_FALLBACK_TEMPLATE])

    def list_available_templates(self) -> list[dict[str, str]]:
        """Список известных Telegram-шаблонов (тип/статус/назначение)."""
        out: list[dict[str, str]] = []
        for t in TELEGRAM_TEMPLATE_TYPES:
            tpl = SYSTEM_TEMPLATES.get(t)
            out.append(
                {
                    "template_type": t,
                    "status": "active" if tpl is not None else "draft",
                    "purpose": (tpl or {}).get("purpose", "Системное уведомление"),
                }
            )
        return out

    def preview_template(
        self, template_type: str, sample_data: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Preview Telegram-шаблона на демо-данных (без БД)."""
        tpl = self.get_system_template(template_type)
        variables = {
            "app_name": "Botfleet",
            "user_name": "Пользователь",
            "project_name": "Проект",
            "title": "Пример уведомления",
            "message": "Текст уведомления для предпросмотра.",
            "action_url": "/ui/notifications",
            "priority": "normal",
            "created_at": "",
            "entity_type": "notification",
            "entity_id": "1",
            "digest_count": "0",
            "digest_body": "Новых уведомлений нет.",
        }
        if sample_data:
            variables.update({k: str(v) for k, v in sample_data.items()})
        return self._render(template_type, tpl, variables)

    # ------------------------------------------------------------------ #
    # Рендер уведомления / дайджеста                                     #
    # ------------------------------------------------------------------ #

    def render_notification_telegram(
        self,
        db: Session,
        notification_id: int,
        template_type: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Отрендерить короткий Telegram-текст для уведомления."""
        notification = notification_repository.get_notification_by_id(db, notification_id)
        if notification is None:
            raise TelegramTemplateError("Уведомление не найдено")
        if current_user_id is not None and notification.recipient_user_id != current_user_id:
            raise TelegramTemplateError("Нет доступа к уведомлению")
        ttype = template_type or self._template_type_for(notification.notification_type)
        tpl = self.get_system_template(ttype)
        user = (
            user_repository.get_user_by_id(db, notification.recipient_user_id)
            if notification.recipient_user_id
            else None
        )
        project = (
            project_repository.get_project_by_id(db, notification.project_id)
            if notification.project_id
            else None
        )
        account = (
            account_repository.get_account_by_id(db, notification.account_id)
            if notification.account_id
            else None
        )
        variables = self.build_template_variables(notification, user, project, account)
        rendered = self._render(ttype, tpl, variables)
        rendered["notification_id"] = notification_id
        self._write_audit(
            db,
            audit_actions.ACTION_TELEGRAM_NOTIFICATION_PREVIEWED,
            account_id=notification.account_id,
            project_id=notification.project_id,
            user_id=current_user_id,
            metadata={"notification_id": notification_id, "template_type": ttype},
        )
        return rendered

    def render_digest_telegram(self, db: Session, digest_id: int) -> dict[str, Any]:
        """Отрендерить короткий Telegram-дайджест по сохранённому дайджесту."""
        digest = delivery_repo.get_digest_by_id(db, digest_id)
        if digest is None:
            raise TelegramTemplateError("Дайджест не найден")
        ttype = "digest_weekly" if digest.frequency == "weekly" else "digest_daily"
        tpl = self.get_system_template(ttype)
        user = user_repository.get_user_by_id(db, digest.user_id)
        project = (
            project_repository.get_project_by_id(db, digest.project_id)
            if digest.project_id
            else None
        )
        variables = {
            "app_name": "Botfleet",
            "user_name": self._user_name(user),
            "project_name": project.name if project is not None else "—",
            "digest_count": str(len(digest.notification_ids or [])),
            "digest_body": sanitize_text(digest.body_preview or "Новых уведомлений нет.", 3000),
            "action_url": "/ui/notifications",
        }
        rendered = self._render(ttype, tpl, variables)
        rendered["digest_id"] = digest_id
        return rendered

    def build_template_variables(
        self, notification: Any, user: Any = None, project: Any = None, account: Any = None
    ) -> dict[str, str]:
        """Собрать переменные Telegram-шаблона из уведомления/пользователя/проекта/аккаунта."""
        return {
            "app_name": account.name if account is not None else "Botfleet",
            "user_name": self._user_name(user),
            "project_name": project.name if project is not None else "—",
            "title": sanitize_text(notification.title or "", 200),
            "message": sanitize_text(notification.message or "", 800),
            "action_url": notification.action_url or "/ui/notifications",
            "priority": notification.priority or "normal",
            "created_at": (notification.created_at.isoformat() if notification.created_at else ""),
            "entity_type": notification.entity_type or "",
            "entity_id": str(notification.entity_id or ""),
        }

    def sanitize_telegram_text(self, text: str) -> str:
        """Убрать секреты/токены, нормализовать пробелы, обрезать до лимита символов."""
        cleaned = redact_sensitive_text(text or "")
        cleaned = _INTERNAL_PATH_RE.sub("[путь скрыт]", cleaned)
        # Нормализация пробелов: схлопнуть табы/пробелы и лишние переводы строк.
        cleaned = _WS_RE.sub(" ", cleaned)
        cleaned = _MULTI_NL_RE.sub("\n\n", cleaned)
        cleaned = "\n".join(line.rstrip() for line in cleaned.splitlines())
        limit = self._max_chars()
        return cleaned.strip()[:limit]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _render(
        self, template_type: str, tpl: dict[str, str], variables: dict[str, Any]
    ) -> dict[str, Any]:
        subject = self.sanitize_telegram_text(
            _render_placeholders(tpl.get("subject", ""), variables)
        )
        text = self.sanitize_telegram_text(_render_placeholders(tpl.get("text", ""), variables))
        return {
            "template_type": template_type,
            "subject": subject,
            "text": text,
            "parse_mode": self._parse_mode(),
            "chars": len(text),
        }

    def _template_type_for(self, notification_type: str) -> str:
        return notification_type if notification_type in SYSTEM_TEMPLATES else _FALLBACK_TEMPLATE

    def _user_name(self, user: Any) -> str:
        if user is None:
            return "коллега"
        return sanitize_text(user.full_name or (user.email or "").split("@")[0] or "коллега", 120)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _parse_mode(self) -> str:
        mode = str(self._resolve_settings().notification_telegram_parse_mode or "none")
        return mode if mode in ("none", "markdown_v2", "html") else "none"

    def _max_chars(self) -> int:
        return int(self._resolve_settings().notification_telegram_max_message_chars_safe)

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None = None,
        project_id: int | None = None,
        user_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            user_id=user_id,
            entity_type="telegram_notification",
            metadata=metadata or {},
        )


def _render_placeholders(template_str: str, variables: dict[str, Any]) -> str:
    """Безопасная подстановка ``{{ var }}`` (неизвестные → '')."""

    def _sub(match: re.Match[str]) -> str:
        value = variables.get(match.group(1), "")
        return "" if value is None else str(value)

    return _PLACEHOLDER_RE.sub(_sub, template_str or "")


def get_telegram_notification_template_service() -> TelegramNotificationTemplateService:
    """DI-фабрика сервиса Telegram-шаблонов."""
    return TelegramNotificationTemplateService()
