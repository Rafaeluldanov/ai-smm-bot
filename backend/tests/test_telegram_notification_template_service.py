"""Тесты сервиса Telegram-шаблонов (v0.5.4). Offline; без сети; sandbox."""

import pytest
from sqlalchemy.orm import Session

from app.models.notification_telegram_binding import TELEGRAM_TEMPLATE_TYPES
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.notification_service import NotificationService
from app.services.telegram_notification_template_service import (
    TelegramTemplateError,
    get_telegram_notification_template_service,
)


def _seed(db: Session, slug: str = "tts"):  # noqa: ANN202
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


def test_system_templates_cover_known_types() -> None:
    service = get_telegram_notification_template_service()
    rows = service.list_available_templates()
    types = {r["template_type"] for r in rows}
    assert set(TELEGRAM_TEMPLATE_TYPES) <= types
    for row in rows:
        assert row["purpose"] and row["status"] in {"active", "draft"}


def test_preview_renders_subject_text_parse_mode() -> None:
    service = get_telegram_notification_template_service()
    result = service.preview_template("review_assigned")
    assert result["subject"]
    assert result["text"]
    assert result["parse_mode"] == "none"
    assert result["chars"] == len(result["text"])


def test_render_notification_text(db_session: Session) -> None:
    account, project, owner = _seed(db_session)
    n = _notify(db_session, account, project, owner)
    service = get_telegram_notification_template_service()
    rendered = service.render_notification_telegram(db_session, n["id"], current_user_id=owner.id)
    assert rendered["text"]
    assert rendered["notification_id"] == n["id"]


def test_render_notification_foreign_user_denied(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "tts-own")
    other = user_repository.create_user(db_session, email="other@e.com", password_hash="x")
    db_session.commit()
    n = _notify(db_session, account, project, owner)
    service = get_telegram_notification_template_service()
    with pytest.raises(TelegramTemplateError):
        service.render_notification_telegram(db_session, n["id"], current_user_id=other.id)


def test_render_trims_max_chars() -> None:
    service = get_telegram_notification_template_service()
    long_message = "А" * 9000
    result = service.preview_template("system_notice", {"message": long_message})
    # Обрезано до безопасного лимита (<= 4096).
    assert len(result["text"]) <= 4096


def test_sanitizes_tokens() -> None:
    service = get_telegram_notification_template_service()
    secret = "123456789:AAExampleABCDEFghijklmnop_qrstuvwx"
    result = service.preview_template("system_notice", {"message": f"token {secret}"})
    assert secret not in result["text"]


def test_unknown_variables_safe() -> None:
    service = get_telegram_notification_template_service()
    # Неизвестный тип откатывается к system_notice; неизвестные {{ }} → пусто (без исключений).
    result = service.preview_template("no_such_template_type")
    assert result["subject"]
    assert result["text"]


def test_render_digest_text(db_session: Session) -> None:
    from app.repositories import notification_delivery_repository as delivery_repo

    account, project, owner = _seed(db_session, "tts-dig")
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
    service = get_telegram_notification_template_service()
    rendered = service.render_digest_telegram(db_session, digest.id)
    assert rendered["subject"]
    assert rendered["digest_id"] == digest.id
