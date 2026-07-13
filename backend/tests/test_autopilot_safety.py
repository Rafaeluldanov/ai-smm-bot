"""Статические/поведенческие safety-проверки автопилота (v0.5.6, Часть 14).

full_auto — основной режим, но он НЕ включает глобальные live-флаги, НЕ вызывает publish_due и НЕ
обходит live-gates: первый пост создаётся как needs_review. Без реальных внешних вызовов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.autopilot_service import AutopilotService
from app.services.billing_service import BillingService
from app.services.platform_connection_service import get_platform_connection_service

_AUTOPILOT_MODULES = (
    "app.services.autopilot_service",
    "app.repositories.autopilot_repository",
    "app.api.autopilot",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_due_import_or_call() -> None:
    for module in _AUTOPILOT_MODULES:
        src = _source(module)
        for token in ("scripts.publish_due", "publish_due(", "publish-due", "import publish_due"):
            assert token not in src, f"{token} в {module}"


def test_api_does_not_call_live_publish() -> None:
    src = _source("app.api.autopilot").lower()
    for token in ("publish_due", "wall.post", "sendmessage", "vk_live", "telegram_live"):
        assert token not in src


def test_start_autopilot_does_not_mutate_global_live_flags() -> None:
    src = _source("app.services.autopilot_service")
    # Автопилот не присваивает live-флаги публикации.
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
    ):
        assert token not in src


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_full_auto_primary_does_not_enable_live_flags(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "aps-live")
    settings = Settings()
    assert settings.autopilot_default_mode_safe == "full_auto"
    svc = AutopilotService(settings=settings)
    svc.get_or_create_profile(db_session, project.id, owner.id)
    # Даже full_auto по умолчанию не включает глобальные live-флаги.
    assert settings.telegram_live_publishing_enabled is False
    assert settings.vk_live_publishing_enabled is False
    assert settings.instagram_live_publishing_enabled is False
    assert settings.payments_live_enabled is False


def test_live_disabled_blocker_visible(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "aps-blk")
    svc = AutopilotService(settings=Settings())
    svc.configure_yandex_disk(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    svc.configure_calendar(db_session, project.id, {"platforms": ["telegram"]}, owner.id)
    for i in range(6):
        db_session.add(
            MediaAsset(project_id=project.id, file_name=f"i{i}.jpg", yandex_disk_path=f"/i{i}.jpg")
        )
    db_session.commit()
    get_platform_connection_service().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "1:x", "external_id": "@c"}
    )
    BillingService().credit_payment(db_session, account.id, 100, idempotency_key="k")
    health = svc.run_health_check(db_session, project.id)
    assert "live_flags_disabled" in [b["type"] for b in health["blockers"]]


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.autopilot_auto_start_live is False
    assert s.autopilot_health_check_worker_enabled is False
    assert s.autopilot_show_advanced_settings is False
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.payments_live_enabled is False
