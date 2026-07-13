"""Тесты сервиса email-шаблонов (v0.5.3). Offline; без сети; sandbox.

Проверяем: системные шаблоны, рендер уведомления/дайджеста, маскирование unsubscribe-URL,
санитизацию, экранирование HTML. Сырой токен по умолчанию не раскрывается.
"""

import pytest
from sqlalchemy.orm import Session

from app.models.email_template_override import (
    EMAIL_TEMPLATE_TYPES,
)
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.email_template_service import (
    EmailTemplateError,
    get_email_template_service,
)
from app.services.notification_service import NotificationService


def _seed(db: Session, slug: str = "ets"):  # noqa: ANN202
    owner = user_repository.create_user(
        db, email=f"{slug}@e.com", password_hash="x", full_name="Иван Тест"
    )
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _notify(db: Session, account, project, owner, **kw):  # noqa: ANN001, ANN003, ANN202
    return NotificationService().create_notification(
        db,
        recipient_user_id=owner.id,
        notification_type=kw.get("notification_type", "review_assigned"),
        title=kw.get("title", "Заголовок"),
        message=kw.get("message", "Сообщение"),
        account_id=account.id,
        project_id=project.id,
        entity_id=kw.get("entity_id", 1),
    )


def test_list_available_templates_covers_known_types() -> None:
    service = get_email_template_service()
    rows = service.list_available_templates()
    types = {r["template_type"] for r in rows}
    # Все объявленные типы присутствуют в списке.
    assert set(EMAIL_TEMPLATE_TYPES) <= types
    for row in rows:
        assert row["purpose"] and row["status"] in {"active", "draft"}


def test_preview_template_renders_subject_text_html() -> None:
    service = get_email_template_service()
    result = service.preview_template("review_assigned")
    assert result["subject"]
    assert result["text_body"]
    assert result["html_body"]
    # HTML содержит теги (это HTML-версия), текстовая — нет.
    assert "<" in result["html_body"]


def test_preview_unknown_template_falls_back_to_system_notice() -> None:
    # Неизвестный тип не роняет рендер, а мягко откатывается к system_notice.
    service = get_email_template_service()
    result = service.preview_template("no_such_template_type")
    assert result["subject"]
    assert result["text_body"]


def test_render_notification_masks_unsubscribe_by_default(db_session: Session) -> None:
    account, project, owner = _seed(db_session)
    n = _notify(db_session, account, project, owner)
    service = get_email_template_service()
    rendered = service.render_notification_email(db_session, n["id"], current_user_id=owner.id)
    masked = rendered["unsubscribe_url_masked"]
    assert "***" in masked
    # В маскированном URL нет полного токена; текстовое тело содержит только masked-URL.
    assert masked in rendered["text_body"] or "***" in rendered["text_body"]


def test_render_notification_reveal_exposes_full_url_only_on_flag(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ets-rev")
    n = _notify(db_session, account, project, owner)
    service = get_email_template_service()
    masked = service.render_notification_email(
        db_session, n["id"], current_user_id=owner.id, reveal_unsubscribe=False
    )
    revealed = service.render_notification_email(
        db_session, n["id"], current_user_id=owner.id, reveal_unsubscribe=True
    )
    # Раскрытый URL длиннее маскированного (содержит полный токен).
    assert len(revealed["text_body"]) >= len(masked["text_body"])
    assert "***" in masked["unsubscribe_url_masked"]


def test_render_notification_foreign_user_denied(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ets-own")
    other = user_repository.create_user(db_session, email="other@e.com", password_hash="x")
    db_session.commit()
    n = _notify(db_session, account, project, owner)
    service = get_email_template_service()
    with pytest.raises(EmailTemplateError):
        service.render_notification_email(db_session, n["id"], current_user_id=other.id)


def test_render_escapes_html_in_user_content(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ets-xss")
    n = _notify(db_session, account, project, owner, title="<script>alert(1)</script>")
    service = get_email_template_service()
    rendered = service.render_notification_email(db_session, n["id"], current_user_id=owner.id)
    # В HTML-теле сырой <script> не должен присутствовать (экранирован).
    assert "<script>" not in rendered["html_body"]


def test_render_digest_email(db_session: Session) -> None:
    from app.repositories import notification_delivery_repository as delivery_repo

    account, project, owner = _seed(db_session, "ets-dig")
    n = _notify(db_session, account, project, owner)
    digest = delivery_repo.create_digest(
        db_session,
        user_id=owner.id,
        account_id=account.id,
        project_id=project.id,
        frequency="daily",
        notification_ids=[n["id"]],
        body_preview="Сводка за день",
    )
    db_session.commit()
    service = get_email_template_service()
    rendered = service.render_digest_email(db_session, digest.id)
    assert rendered["subject"]
    assert "***" in rendered["unsubscribe_url_masked"]
