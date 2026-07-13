"""Сервис email-шаблонов и рендеринга — v0.5.3.

Системные шаблоны живут в коде (не во внешних файлах). Рендеринг — безопасная подстановка
``{{ variable }}`` (без Jinja): неизвестные переменные → пустая строка; в HTML значения
экранируются. Добавляет футер отписки (masked URL по умолчанию). Реальной отправки нет.

БЕЗОПАСНОСТЬ:
- финальный текст проходит ``redact_sensitive_text`` (секреты/токены-провайдеров замаскированы);
- сырой токен отписки — ТОЛЬКО внутри полного URL при ``reveal=True``; по умолчанию masked;
- в preview/логи не попадают SMTP-пароль и внутренние пути.
"""

from __future__ import annotations

import html as _html
import re
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text
from app.models.email_template_override import EMAIL_TEMPLATE_TYPES
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
    from app.services.notification_unsubscribe_service import NotificationUnsubscribeService

logger = get_logger(__name__)

_PLACEHOLDER_RE = re.compile(r"\{\{\s*(\w+)\s*\}\}")
_INTERNAL_PATH_RE = re.compile(
    r"(?i)(?:disk:/\S+|/(?:Users|home|var|etc|tmp|mnt|srv|opt|root)/\S+|[A-Za-z]:\\\S+)"
)

# Системные email-шаблоны (subject/text/html/purpose). Плейсхолдеры: {{ var }}.
# Футер-метки — сентинелы (НЕ {{ var }}), чтобы пережить рендер и подставиться сырыми
# (иначе _render съел бы {{ ... }} как неизвестную переменную ещё до .replace).
_FOOTER_MARK = "@@UNSUB_FOOTER_TEXT@@"
_FOOTER_MARK_HTML = "@@UNSUB_FOOTER_HTML@@"

SYSTEM_TEMPLATES: dict[str, dict[str, str]] = {
    "review_assigned": {
        "purpose": "Вам назначена задача ревью",
        "subject": "[{{ app_name }}] Вам назначена задача: {{ notification_title }}",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nВам назначена задача ревью в проекте "
            "«{{ project_name }}».\n\n{{ notification_message }}\n\nОткрыть: {{ action_url }}\n"
            + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>Вам назначена задача ревью в проекте "
            "<b>{{ project_name }}</b>.</p><p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Открыть задачу</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "review_mentioned": {
        "purpose": "Вас упомянули в комментарии",
        "subject": "[{{ app_name }}] Вас упомянули: {{ notification_title }}",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nВас упомянули в проекте «{{ project_name }}».\n\n"
            "{{ notification_message }}\n\nОткрыть: {{ action_url }}\n" + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>Вас упомянули в проекте "
            "<b>{{ project_name }}</b>.</p><p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Открыть</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "task_overdue": {
        "purpose": "Задача просрочена",
        "subject": "[{{ app_name }}] Задача просрочена: {{ notification_title }}",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nЗадача в проекте «{{ project_name }}» просрочена "
            "(приоритет {{ priority }}).\n\n{{ notification_message }}\n\n"
            "Открыть: {{ action_url }}\n" + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>Задача в проекте <b>{{ project_name }}</b> "
            "просрочена (приоритет {{ priority }}).</p><p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Открыть</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "post_needs_review": {
        "purpose": "Пост ждёт ревью",
        "subject": "[{{ app_name }}] Пост ждёт ревью в «{{ project_name }}»",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nВ проекте «{{ project_name }}» новый пост ждёт "
            "ревью.\n\n{{ notification_message }}\n\nОткрыть: {{ action_url }}\n" + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p>"
            "<p>В проекте <b>{{ project_name }}</b> новый пост ждёт ревью.</p>"
            "<p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Открыть</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "experiment_suggestion_created": {
        "purpose": "Новые A/B-предложения",
        "subject": "[{{ app_name }}] Новые A/B-предложения в «{{ project_name }}»",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\n{{ notification_message }}\n\nОткрыть: "
            "{{ action_url }}\n" + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Открыть</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "billing_balance_low": {
        "purpose": "Низкий баланс",
        "subject": "[{{ app_name }}] Низкий баланс units",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\n{{ notification_message }}\n\nПополнить: "
            "{{ action_url }}\n" + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>{{ notification_message }}</p>"
            "<p><a href='{{ action_url }}'>Пополнить</a></p>" + _FOOTER_MARK_HTML
        ),
    },
    "digest_daily": {
        "purpose": "Ежедневный дайджест",
        "subject": "[{{ app_name }}] Ежедневный дайджест — {{ digest_count }} уведомлений",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nВаш ежедневный дайджест:\n\n{{ digest_body }}\n"
            + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>Ваш ежедневный дайджест:</p>"
            "<pre>{{ digest_body }}</pre>" + _FOOTER_MARK_HTML
        ),
    },
    "digest_weekly": {
        "purpose": "Еженедельный дайджест",
        "subject": "[{{ app_name }}] Еженедельный дайджест — {{ digest_count }} уведомлений",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\nВаш еженедельный дайджест:\n\n{{ digest_body }}\n"
            + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>Ваш еженедельный дайджест:</p>"
            "<pre>{{ digest_body }}</pre>" + _FOOTER_MARK_HTML
        ),
    },
    "system_notice": {
        "purpose": "Системное уведомление",
        "subject": "[{{ app_name }}] {{ notification_title }}",
        "text": (
            "Здравствуйте, {{ user_name }}!\n\n{{ notification_message }}\n\n{{ action_url }}\n"
            + _FOOTER_MARK
        ),
        "html": (
            "<p>Здравствуйте, {{ user_name }}!</p><p>{{ notification_message }}</p>"
            "<p>{{ action_url }}</p>" + _FOOTER_MARK_HTML
        ),
    },
}

# Типы уведомлений без собственного шаблона → системный шаблон-заглушка (по типу).
_FALLBACK_TEMPLATE = "system_notice"


class EmailTemplateError(Exception):
    """Ошибка рендеринга email (нет доступа/сущности/шаблона) — API → 400/404."""


class EmailTemplateService:
    """Системные email-шаблоны + рендеринг notification/digest + футер отписки (masked)."""

    def __init__(
        self,
        unsubscribe_service: NotificationUnsubscribeService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._unsub = unsubscribe_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Шаблоны                                                            #
    # ------------------------------------------------------------------ #

    def get_system_template(self, template_type: str) -> dict[str, str]:
        """Системный шаблон по типу (или заглушка system_notice)."""
        if template_type in SYSTEM_TEMPLATES:
            return SYSTEM_TEMPLATES[template_type]
        base = dict(SYSTEM_TEMPLATES[_FALLBACK_TEMPLATE])
        base["_resolved_type"] = _FALLBACK_TEMPLATE
        return base

    def list_available_templates(self) -> list[dict[str, str]]:
        """Список известных шаблонов (тип/статус/назначение)."""
        out: list[dict[str, str]] = []
        for t in EMAIL_TEMPLATE_TYPES:
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
        """Preview шаблона на демо-данных (без БД/токена; footer — плейсхолдер)."""
        tpl = self.get_system_template(template_type)
        variables = {
            "app_name": "Botfleet",
            "user_name": "Пользователь",
            "project_name": "Проект",
            "notification_title": "Пример уведомления",
            "notification_message": "Текст уведомления для предпросмотра.",
            "action_url": "/ui/notifications",
            "priority": "normal",
            "entity_type": "notification",
            "entity_id": "1",
            "created_at": "",
            "digest_count": "0",
            "digest_body": "Новых уведомлений нет.",
        }
        if sample_data:
            variables.update({k: str(v) for k, v in sample_data.items()})
        footer = {
            "text": "\nОтписаться: /unsubscribe?token=…",
            "html": (
                "<p style='color:#888;font-size:12px'>Отписаться: "
                "<a href='/unsubscribe?token=…'>ссылка</a></p>"
            ),
            "url": "/unsubscribe?token=…",
            "url_masked": "/unsubscribe?token=…",
        }
        return self._render_all(template_type, tpl, variables, footer)

    # ------------------------------------------------------------------ #
    # Рендер уведомления                                                 #
    # ------------------------------------------------------------------ #

    def render_notification_email(
        self,
        db: Session,
        notification_id: int,
        template_type: str | None = None,
        render_format: str = "both",  # noqa: ARG002 — формат влияет только на потребителя
        current_user_id: int | None = None,
        reveal_unsubscribe: bool = False,
    ) -> dict[str, Any]:
        """Отрендерить email для уведомления (шаблон по типу, футер отписки masked)."""
        notification = notification_repository.get_notification_by_id(db, notification_id)
        if notification is None:
            raise EmailTemplateError("Уведомление не найдено")
        if current_user_id is not None and notification.recipient_user_id != current_user_id:
            raise EmailTemplateError("Нет доступа к уведомлению")
        ttype = template_type or self._template_type_for(notification.notification_type)
        tpl = self.get_system_template(ttype)
        user = (
            user_repository.get_user_by_id(db, notification.recipient_user_id)
            if notification.recipient_user_id
            else None
        )
        variables = self.build_template_variables(db, notification, user)
        footer = self.build_unsubscribe_footer(
            notification.recipient_user_id,
            channel="email",
            project_id=notification.project_id,
            notification_type=notification.notification_type,
            reveal=reveal_unsubscribe,
        )
        variables["unsubscribe_url"] = (
            footer["url_masked"] if not reveal_unsubscribe else footer["url"]
        )
        rendered = self._render_all(ttype, tpl, variables, footer)
        self._write_audit(
            db,
            audit_actions.ACTION_EMAIL_NOTIFICATION_PREVIEWED,
            account_id=notification.account_id,
            project_id=notification.project_id,
            user_id=current_user_id,
            metadata={"notification_id": notification_id, "template_type": ttype},
        )
        rendered.update(
            {
                "notification_id": notification_id,
                "action_url": variables.get("action_url"),
                "has_unsubscribe_footer": self._footer_enabled(),
                "unsubscribe_url_masked": footer["url_masked"],
            }
        )
        return rendered

    # ------------------------------------------------------------------ #
    # Рендер дайджеста                                                   #
    # ------------------------------------------------------------------ #

    def render_digest_email(
        self,
        db: Session,
        digest_id: int,
        render_format: str = "both",  # noqa: ARG002
    ) -> dict[str, Any]:
        """Отрендерить email-дайджест по сохранённому дайджесту."""
        digest = delivery_repo.get_digest_by_id(db, digest_id)
        if digest is None:
            raise EmailTemplateError("Дайджест не найден")
        ttype = "digest_weekly" if digest.frequency == "weekly" else "digest_daily"
        tpl = self.get_system_template(ttype)
        user = user_repository.get_user_by_id(db, digest.user_id)
        variables = {
            "app_name": "Botfleet",
            "user_name": self._user_name(user),
            "project_name": self._project_name(db, digest.project_id),
            "digest_count": str(len(digest.notification_ids or [])),
            "digest_body": sanitize_text(digest.body_preview or "Новых уведомлений нет.", 4000),
            "action_url": "/ui/notifications",
        }
        footer = self.build_unsubscribe_footer(
            digest.user_id, channel="digest", project_id=digest.project_id
        )
        variables["unsubscribe_url"] = footer["url_masked"]
        rendered = self._render_all(ttype, tpl, variables, footer)
        rendered.update(
            {
                "digest_id": digest_id,
                "has_unsubscribe_footer": self._footer_enabled(),
                "unsubscribe_url_masked": footer["url_masked"],
            }
        )
        return rendered

    # ------------------------------------------------------------------ #
    # Переменные / футер / рендер                                        #
    # ------------------------------------------------------------------ #

    def build_template_variables(
        self, db: Session, notification: Any, user: Any = None
    ) -> dict[str, str]:
        """Собрать переменные шаблона из уведомления/пользователя/проекта."""
        return {
            "app_name": "Botfleet",
            "user_name": self._user_name(user),
            "project_name": self._project_name(db, notification.project_id),
            "notification_title": sanitize_text(notification.title or "", 200),
            "notification_message": sanitize_text(notification.message or "", 1000),
            "action_url": notification.action_url or "/ui/notifications",
            "entity_type": notification.entity_type or "",
            "entity_id": str(notification.entity_id or ""),
            "priority": notification.priority or "normal",
            "created_at": notification.created_at.isoformat() if notification.created_at else "",
        }

    def build_unsubscribe_footer(
        self,
        user_id: int | None,
        channel: str = "email",
        project_id: int | None = None,
        notification_type: str | None = None,
        reveal: bool = False,
    ) -> dict[str, str]:
        """Собрать футер отписки. Полный URL с токеном — только при reveal; иначе masked."""
        if user_id is None or not self._footer_enabled():
            return {"text": "", "html": "", "url": "", "url_masked": ""}
        token = self._unsub_svc().issue_unsubscribe_token(
            user_id,
            "channel",
            channel=channel,
            project_id=project_id,
            notification_type=notification_type,
        )
        full_url = self._unsub_svc().build_unsubscribe_url(token)
        masked_url = _mask_unsubscribe_url(full_url, token)
        display = full_url if reveal else masked_url
        text = f"\n—\nЕсли не хотите получать такие письма — отписаться: {display}"
        html = (
            "<hr><p style='color:#888;font-size:12px'>Если не хотите получать такие письма — "
            f"<a href='{_html.escape(display)}'>отписаться</a>.</p>"
        )
        return {"text": text, "html": html, "url": full_url, "url_masked": masked_url}

    def sanitize_rendered_email(self, rendered: dict[str, Any]) -> dict[str, Any]:
        """Замаскировать секреты/токены-провайдеров и внутренние пути в готовом письме."""
        out = dict(rendered)
        for key in ("subject", "text_body", "html_body"):
            if isinstance(out.get(key), str):
                out[key] = _sanitize(out[key])
        return out

    def _render_all(
        self,
        template_type: str,
        tpl: dict[str, str],
        variables: dict[str, Any],
        footer: dict[str, str],
    ) -> dict[str, Any]:
        subject = _render(tpl.get("subject", ""), variables, escape=False)
        text_body = _render(tpl.get("text", ""), variables, escape=False)
        text_body = text_body.replace(_FOOTER_MARK, footer.get("text", ""))
        html_src = tpl.get("html") or ""
        html_body = _render(html_src, variables, escape=True)
        # Сентинел @@...@@ переживает escape=True (нет спецсимволов) → подставляем сырой футер.
        html_body = html_body.replace(_FOOTER_MARK_HTML, footer.get("html", ""))
        rendered = {
            "template_type": template_type,
            "subject": subject.strip(),
            "text_body": text_body.strip(),
            "html_body": html_body.strip(),
        }
        return self.sanitize_rendered_email(rendered)

    def _template_type_for(self, notification_type: str) -> str:
        return notification_type if notification_type in SYSTEM_TEMPLATES else _FALLBACK_TEMPLATE

    def _user_name(self, user: Any) -> str:
        if user is None:
            return "коллега"
        return sanitize_text(user.full_name or (user.email or "").split("@")[0] or "коллега", 120)

    def _project_name(self, db: Session, project_id: int | None) -> str:
        if project_id is None:
            return "—"
        project = project_repository.get_project_by_id(db, project_id)
        return sanitize_text(project.name, 120) if project is not None else "—"

    def _account_name(self, db: Session, account_id: int | None) -> str:
        if account_id is None:
            return "—"
        account = account_repository.get_account_by_id(db, account_id)
        return sanitize_text(account.name, 120) if account is not None else "—"

    def _footer_enabled(self) -> bool:
        return bool(self._resolve_settings().email_unsubscribe_footer_enabled_effective)

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _unsub_svc(self) -> NotificationUnsubscribeService:
        if self._unsub is None:
            from app.services.notification_unsubscribe_service import (
                NotificationUnsubscribeService,
            )

            self._unsub = NotificationUnsubscribeService(settings=self._settings)
        return self._unsub

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
            entity_type="email_template",
            metadata=metadata or {},
        )


def _render(template_str: str, variables: dict[str, Any], escape: bool = False) -> str:
    """Безопасная подстановка ``{{ var }}`` (неизвестные → ''; в html значения экранируются)."""

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        value = variables.get(name, "")
        text = "" if value is None else str(value)
        return _html.escape(text) if escape else text

    return _PLACEHOLDER_RE.sub(_sub, template_str or "")


def _sanitize(text: str) -> str:
    cleaned = redact_sensitive_text(text or "")
    return _INTERNAL_PATH_RE.sub("[путь скрыт]", cleaned)


def _mask_unsubscribe_url(url: str, token: str) -> str:
    """Замаскировать токен в URL отписки (для preview/логов)."""
    if not token:
        return url
    short = token[:6] + "***"
    return url.replace(token, short)


def get_email_template_service() -> EmailTemplateService:
    """DI-фабрика сервиса email-шаблонов."""
    return EmailTemplateService()
