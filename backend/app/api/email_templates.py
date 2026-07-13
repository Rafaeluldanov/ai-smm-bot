"""REST API email-шаблонов и preview (v0.5.3).

Preview/тестовая отправка — sandbox: реальной email-доставки нет. Пользователь может смотреть
СВОИ уведомления/дайджесты; проектные настройки — под project-гардом. Сырых токенов/SMTP-паролей
в ответах нет (unsubscribe URL — masked).
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_email_template_service
from app.api.security_guards import require_project_access
from app.config import Settings, get_settings
from app.models.user import User
from app.repositories import notification_delivery_repository as delivery_repo
from app.services import audit_log_service as audit_actions
from app.services.email_template_service import EmailTemplateError, EmailTemplateService
from app.services.notification_delivery import mask_destination

router = APIRouter(prefix="/email-templates", tags=["email-templates"])

DbSession = Annotated[Session, Depends(get_db)]
TplSvc = Annotated[EmailTemplateService, Depends(get_email_template_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except EmailTemplateError as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class PreviewRequest(BaseModel):
    """Preview шаблона (демо-данные) или конкретного уведомления."""

    template_type: str = "system_notice"
    notification_id: int | None = None
    sample: dict[str, Any] | None = None


class TestSendRequest(BaseModel):
    """Тестовая отправка (dry-run only)."""

    to: str
    template_type: str = "system_notice"


# --- Роуты ---


@router.get("")
def list_templates(service: TplSvc, user: CurrentUser) -> list[dict[str, Any]]:
    """Список типов email-шаблонов (тип/статус/назначение)."""
    return service.list_available_templates()


@router.post("/preview")
def preview(
    payload: PreviewRequest, db: DbSession, service: TplSvc, user: CurrentUser
) -> dict[str, Any]:
    """Preview шаблона на демо-данных или (если задан notification_id) на своём уведомлении."""
    if payload.notification_id is not None:
        notification_id = payload.notification_id
        return _run(
            lambda: service.render_notification_email(
                db,
                notification_id,
                template_type=payload.template_type,
                current_user_id=user.id,
            )
        )
    result = service.preview_template(payload.template_type, payload.sample)
    service._write_audit(  # noqa: SLF001 — аудит preview без сущности
        db,
        audit_actions.ACTION_EMAIL_TEMPLATE_PREVIEWED,
        user_id=user.id,
        metadata={"template_type": payload.template_type},
    )
    return result


@router.post("/notifications/{notification_id}/preview")
def preview_notification(
    notification_id: int, db: DbSession, service: TplSvc, user: CurrentUser
) -> dict[str, Any]:
    """Preview email конкретного уведомления (только владелец)."""
    return _run(
        lambda: service.render_notification_email(db, notification_id, current_user_id=user.id)
    )


@router.post("/digests/{digest_id}/preview")
def preview_digest(
    digest_id: int, db: DbSession, service: TplSvc, user: CurrentUser
) -> dict[str, Any]:
    """Preview email-дайджеста (только владелец)."""
    digest = delivery_repo.get_digest_by_id(db, digest_id)
    if digest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Дайджест не найден")
    if digest.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Нет доступа")
    return _run(lambda: service.render_digest_email(db, digest_id))


@router.get("/projects/{project_id}/settings", dependencies=[Depends(require_project_access)])
def project_settings(project_id: int, service: TplSvc, settings: SettingsDep) -> dict[str, Any]:
    """Статус email-шаблонов и SMTP-безопасности для проекта (без секретов)."""
    return {
        "project_id": project_id,
        "email_templates_enabled": settings.email_templates_enabled_effective,
        "template_preview_enabled": settings.email_template_preview_enabled_effective,
        "unsubscribe_footer_enabled": settings.email_unsubscribe_footer_enabled_effective,
        "smtp_live_send_enabled": settings.smtp_live_send_enabled_effective,
        "smtp_dry_run": settings.smtp_dry_run_effective,
        "smtp_configured": settings.smtp_configured,
        "notification_email_live_enabled": settings.notification_email_enabled_effective,
        "external_delivery_enabled": settings.notification_external_delivery_enabled_effective,
        "email_test_send_enabled": settings.email_test_send_enabled_effective,
    }


@router.post("/test-send-dry")
def test_send_dry(
    payload: TestSendRequest,
    db: DbSession,
    service: TplSvc,
    user: CurrentUser,
    settings: SettingsDep,
) -> dict[str, Any]:
    """Тестовый рендер письма (DRY-RUN only). Реальной отправки НЕТ ни при каких флагах здесь."""
    to_masked = mask_destination("email", payload.to)
    allowed = settings.email_test_allowed_recipients_list
    if not settings.email_test_send_enabled_effective:
        service._write_audit(  # noqa: SLF001
            db,
            audit_actions.ACTION_EMAIL_TEST_SEND_BLOCKED,
            user_id=user.id,
            metadata={"reason": "email_test_send_disabled", "template_type": payload.template_type},
        )
        preview = service.preview_template(payload.template_type)
        return {
            "would_send": False,
            "blocked": True,
            "reason": "Тестовая отправка выключена (EMAIL_TEST_SEND_ENABLED=false)",
            "to_masked": to_masked,
            "subject": preview["subject"],
        }
    if allowed and payload.to.strip().lower() not in allowed:
        service._write_audit(  # noqa: SLF001
            db,
            audit_actions.ACTION_EMAIL_TEST_SEND_BLOCKED,
            user_id=user.id,
            metadata={"reason": "recipient_not_allowed"},
        )
        return {
            "would_send": False,
            "blocked": True,
            "reason": "Получатель не в allowlist",
            "to_masked": to_masked,
        }
    preview = service.preview_template(payload.template_type, {"user_name": "Тест"})
    service._write_audit(  # noqa: SLF001
        db,
        audit_actions.ACTION_EMAIL_TEST_SEND_PREVIEWED,
        user_id=user.id,
        metadata={"template_type": payload.template_type},
    )
    return {
        "would_send": False,
        "dry_run": True,
        "to_masked": to_masked,
        "subject": preview["subject"],
        "text_body": preview["text_body"],
        "note": "Реальной email-отправки нет; это dry-run/sandbox.",
    }
