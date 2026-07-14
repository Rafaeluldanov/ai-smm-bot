"""Тесты сервиса Telegram live runbook (v0.6.3, offline).

Инварианты:
- чек-лист блокирует при отсутствии канала/календаря/media proxy/готовности;
- preview ничего не отправляет;
- без глобального флага и без подтверждения реальной публикации нет;
- happy-path публикации — только с fake-клиентом + всеми гейтами; глобальные флаги не меняются;
- пауза блокирует production-тест; результат уходит в мониторинг (LivePublishAttempt).
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.publishing import FakePublishingClient
from app.models.live_publish_attempt import LivePublishAttempt
from app.models.telegram_live_run_attempt import TelegramLiveRunAttempt
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import live_readiness_repository as lrr
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.telegram_live_rollout_service import TelegramLiveRolloutService
from app.services.telegram_live_runbook_service import (
    TelegramLiveRunbookError,
    TelegramLiveRunbookService,
)


def _base_settings(**kw: object) -> Settings:
    base: dict[str, object] = {"media_proxy_public_base_url": "https://media.example.com"}
    base.update(kw)
    return Settings(**base)


def _seed(db: Session, slug: str, *, connect: bool = True):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    if connect:
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@chan"}
        )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="T",
            status="approved",
            telegram_text="Привет #мерч",
            hashtags=["мерч"],
        ),
    )
    db.commit()
    return account, project, owner, post


def _enable_readiness(db: Session, account_id: int, project_id: int) -> None:
    pp = lrr.get_or_create_project_profile(db, account_id, project_id)
    lrr.update_project_profile(
        db, pp, {"status": "ready", "project_live_enabled": True, "full_auto_live_enabled": True}
    )
    plat = lrr.get_or_create_platform_profile(db, account_id, project_id, "telegram")
    lrr.update_platform_profile(db, plat, {"status": "ready", "platform_live_enabled": True})
    db.commit()


def _ready_rollout(settings: Settings) -> TelegramLiveRolloutService:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram", live_enabled=True)}
    )
    fake_pub = PostPublicationService(registry=registry, default_targets={"telegram": "@chan"})
    return TelegramLiveRolloutService(publication_service=fake_pub, settings=settings)


def test_checklist_blocked_without_connection(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-noconn", connect=False)
    svc = TelegramLiveRunbookService(settings=_base_settings())
    result = svc.build_checklist(db_session, project.id, dry_run=True)
    assert result["ready"] is False
    assert result["checklist"]["telegram"]["done"] is False
    assert any(b["type"] == "telegram" for b in result["blockers"])


def test_checklist_media_proxy_and_calendar_blockers(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-mp")
    # media proxy выключен → media proxy не готов; календаря нет.
    svc = TelegramLiveRunbookService(settings=Settings(media_proxy_enabled=False))
    result = svc.build_checklist(db_session, project.id, dry_run=True)
    assert result["checklist"]["media_proxy"]["done"] is False
    assert result["checklist"]["calendar"]["done"] is False
    types = {b["type"] for b in result["blockers"]}
    assert "media_proxy" in types and "calendar" in types


def test_check_persists_runbook(db_session: Session) -> None:
    from app.repositories import telegram_live_runbook_repository as rbr

    _a, project, _o, _p = _seed(db_session, "rb-persist")
    svc = TelegramLiveRunbookService(settings=_base_settings())
    svc.build_checklist(db_session, project.id, dry_run=False)
    runbook = rbr.get_by_project(db_session, project.id)
    assert runbook is not None and runbook.last_check_at is not None
    assert runbook.status in {"draft", "ready", "blocked", "enabled"}


def test_preview_does_not_send(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-preview")
    svc = TelegramLiveRunbookService(settings=_base_settings())
    before = db_session.query(LivePublishAttempt).count()
    result = svc.prepare_test_post(db_session, project.id)
    assert result["live_calls"] is False
    # preview создаёт runbook-запись, но НЕ технический LivePublishAttempt (нет отправки).
    assert db_session.query(LivePublishAttempt).count() == before
    assert db_session.query(TelegramLiveRunAttempt).count() == 1
    assert result["attempt"]["status"] == "preview"


def test_confirm_blocked_without_global_flag(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-confirm")
    _enable_readiness(db_session, _a.id, project.id)  # клиентские гейты, но global off
    svc = TelegramLiveRunbookService(settings=_base_settings())
    result = svc.confirm_live_publish(db_session, project.id, "ENABLE_TELEGRAM_LIVE")
    assert result["allowed"] is False
    assert any(b["type"] == "global_live_flag_disabled" for b in result["blockers"])


def test_publish_blocked_without_confirmation(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-noconfirm")
    _enable_readiness(db_session, _a.id, project.id)
    settings = _base_settings(
        telegram_live_publishing_enabled=True, telegram_live_rollout_allow_real_send=True
    )
    svc = TelegramLiveRunbookService(rollout_service=_ready_rollout(settings), settings=settings)
    result = svc.publish_test_post(
        db_session, project.id, confirmation_text=""
    )  # нет подтверждения
    assert result["published"] is False
    assert result["attempt"]["status"] == "blocked"


def test_publish_blocked_without_global_flag(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-noglobal")
    _enable_readiness(db_session, _a.id, project.id)
    svc = TelegramLiveRunbookService(settings=_base_settings())  # global off
    result = svc.publish_test_post(db_session, project.id, confirmation_text="ENABLE_TELEGRAM_LIVE")
    assert result["published"] is False
    assert result["attempt"]["status"] == "blocked"


def test_publish_happy_path_with_fake_client(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-go")
    _enable_readiness(db_session, _a.id, project.id)
    settings = _base_settings(
        telegram_live_publishing_enabled=True, telegram_live_rollout_allow_real_send=True
    )
    svc = TelegramLiveRunbookService(rollout_service=_ready_rollout(settings), settings=settings)
    result = svc.publish_test_post(db_session, project.id, confirmation_text="ENABLE_TELEGRAM_LIVE")
    assert result["published"] is True
    assert result["attempt"]["status"] == "published"
    # Технический LivePublishAttempt создан rollout-сервисом → мониторинг увидит его автоматически.
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 1


def test_pause_blocks_publish(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-pause")
    svc = TelegramLiveRunbookService(settings=_base_settings())
    svc.pause_runbook(db_session, project.id)
    with pytest.raises(TelegramLiveRunbookError):
        svc.publish_test_post(db_session, project.id, confirmation_text="ENABLE_TELEGRAM_LIVE")


def test_no_global_flags_changed(db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "rb-noflagchange")
    _enable_readiness(db_session, _a.id, project.id)
    settings = _base_settings(
        telegram_live_publishing_enabled=True, telegram_live_rollout_allow_real_send=True
    )
    svc = TelegramLiveRunbookService(rollout_service=_ready_rollout(settings), settings=settings)
    svc.publish_test_post(db_session, project.id, confirmation_text="ENABLE_TELEGRAM_LIVE")
    # runbook не меняет глобальные флаги.
    assert settings.vk_live_publishing_enabled is False


def test_missing_project_raises(db_session: Session) -> None:
    svc = TelegramLiveRunbookService(settings=_base_settings())
    with pytest.raises(TelegramLiveRunbookError) as exc:
        svc.build_checklist(db_session, 999999, dry_run=True)
    assert "не найден" in str(exc.value)
