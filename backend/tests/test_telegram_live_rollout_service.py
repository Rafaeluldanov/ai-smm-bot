"""Тесты сервиса Telegram live rollout (v0.6.0, offline).

Дашборд, эффективный статус, preview/dry-run без сети, publish-once заблокирован по умолчанию,
happy-path только с fake-клиентом + всеми гейтами. Ключевой инвариант: реальная отправка невозможна
без глобального флага; сервис глобальные флаги не меняет. Без реальных публикаций/сети.
"""

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.integrations.publishing import FakePublishingClient
from app.models.live_publish_attempt import LivePublishAttempt
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    live_readiness_repository as lrr,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.telegram_live_rollout_service import (
    TelegramLiveRolloutService,
    get_telegram_live_rollout_service,
)


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
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


def _ready_service() -> TelegramLiveRolloutService:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram", live_enabled=True)}
    )
    fake_pub = PostPublicationService(registry=registry, default_targets={"telegram": "@chan"})
    settings = Settings(
        telegram_live_publishing_enabled=True, telegram_live_rollout_allow_real_send=True
    )
    return TelegramLiveRolloutService(publication_service=fake_pub, settings=settings)


def test_dashboard_works(db_session: Session) -> None:
    _a, project, _o, _post = _seed(db_session, "tgr-dash")
    dash = get_telegram_live_rollout_service().build_dashboard(db_session, project.id)
    assert dash["status"] in ("draft", "blocked", "ready", "enabled")
    assert "telegram_platform_status" in dash and "recent_attempts" in dash


def test_effective_status_global_false_blocks(db_session: Session) -> None:
    _a, project, _o, _post = _seed(db_session, "tgr-eff")
    st = get_telegram_live_rollout_service().build_effective_telegram_live_status(
        db_session, project.id
    )
    assert st["can_send_real"] is False
    assert "global_live_flag_disabled" in st["blocked_reasons"]


def test_project_platform_full_auto_readiness_required(db_session: Session) -> None:
    acc, project, _o, _post = _seed(db_session, "tgr-req")
    # Даже с fake-клиентом и allow_real_send, без readiness профилей — can_attempt_live False.
    svc = _ready_service()
    st = svc.build_effective_telegram_live_status(db_session, project.id)
    assert st["can_attempt_live"] is False
    _enable_readiness(db_session, acc.id, project.id)
    st2 = svc.build_effective_telegram_live_status(db_session, project.id)
    assert st2["can_attempt_live"] is True
    assert st2["can_send_real"] is True


def test_preview_no_writes(db_session: Session) -> None:
    _a, project, _o, post = _seed(db_session, "tgr-prev")
    before = db_session.query(LivePublishAttempt).count()
    result = get_telegram_live_rollout_service().preview_post(db_session, project.id, post.id)
    assert result["writes"] is False
    assert result["live_calls"] is False
    assert db_session.query(LivePublishAttempt).count() == before


def test_run_dry_creates_blocked_attempt_no_debit(db_session: Session) -> None:
    acc, project, _o, post = _seed(db_session, "tgr-dry")
    before_balance = BillingService().get_balance(db_session, acc.id).balance_units
    result = get_telegram_live_rollout_service().run_once_dry(db_session, project.id, post.id)
    assert result["status"] in ("blocked", "skipped")
    assert result["live_calls"] is False
    assert result["units_charged"] == 0
    after_balance = BillingService().get_balance(db_session, acc.id).balance_units
    assert before_balance == after_balance


def test_publish_once_blocked_by_default(db_session: Session) -> None:
    _a, project, _o, post = _seed(db_session, "tgr-blk")
    result = get_telegram_live_rollout_service().publish_once_if_allowed(
        db_session, project.id, post.id, confirmation="ENABLE_TELEGRAM_LIVE"
    )
    assert result["status"] == "blocked"
    assert result["live_attempted"] is False
    assert result["live_calls"] is False
    types = {b["type"] for b in result["blockers"]}
    assert "external_call_blocked" in types  # rollout allow_real_send off


def test_publish_once_wrong_confirmation_rejected(db_session: Session) -> None:
    acc, project, _o, post = _seed(db_session, "tgr-wrong")
    _enable_readiness(db_session, acc.id, project.id)
    svc = _ready_service()
    result = svc.publish_once_if_allowed(db_session, project.id, post.id, confirmation="NOPE")
    assert result["status"] == "blocked"
    assert any(b["type"] == "safety_gate_failed" for b in result["blockers"])
    assert result["live_attempted"] is False


def test_publish_once_happy_path_with_fake_client(db_session: Session) -> None:
    acc, project, _o, post = _seed(db_session, "tgr-go")
    _enable_readiness(db_session, acc.id, project.id)
    svc = _ready_service()
    result = svc.publish_once_if_allowed(
        db_session, project.id, post.id, confirmation="ENABLE_TELEGRAM_LIVE"
    )
    assert result["status"] == "published"
    assert result["live_attempted"] is True
    assert result["live_calls"] is True


def test_publish_once_duplicate_blocked(db_session: Session) -> None:
    acc, project, _o, post = _seed(db_session, "tgr-dup")
    _enable_readiness(db_session, acc.id, project.id)
    svc = _ready_service()
    first = svc.publish_once_if_allowed(
        db_session, project.id, post.id, confirmation="ENABLE_TELEGRAM_LIVE"
    )
    assert first["status"] == "published"
    second = svc.publish_once_if_allowed(
        db_session, project.id, post.id, confirmation="ENABLE_TELEGRAM_LIVE"
    )
    assert second["status"] == "blocked"
    assert any(b["type"] == "duplicate_attempt" for b in second["blockers"])


def test_no_global_flags_changed(db_session: Session) -> None:
    acc, project, _o, post = _seed(db_session, "tgr-flags")
    _enable_readiness(db_session, acc.id, project.id)
    _ready_service().publish_once_if_allowed(
        db_session, project.id, post.id, confirmation="ENABLE_TELEGRAM_LIVE"
    )
    s = get_settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_no_secrets_in_attempt_view(db_session: Session) -> None:
    _a, project, _o, post = _seed(db_session, "tgr-sec")
    result = get_telegram_live_rollout_service().run_once_dry(db_session, project.id, post.id)
    assert "123456:ABCdef" not in str(result)
