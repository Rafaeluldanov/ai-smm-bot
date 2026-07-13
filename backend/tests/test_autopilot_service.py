"""Тесты сервиса автопилота (v0.5.6). Offline; без live-публикаций и внешних вызовов."""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import autopilot_repository as autopilot_repo
from app.schemas.project import ProjectCreate
from app.services.autopilot_service import AutopilotError, AutopilotService
from app.services.billing_service import BillingService
from app.services.platform_connection_service import get_platform_connection_service


def _seed(db: Session, slug: str = "ap"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x", full_name="И")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc() -> AutopilotService:
    return AutopilotService(settings=Settings())


def _fully_setup(db: Session, account, project, owner) -> None:  # noqa: ANN001
    svc = _svc()
    svc.configure_yandex_disk(
        db, project.id, {"public_url": "https://disk.yandex.ru/d/x", "root_folder": "SMM"}, owner.id
    )
    svc.configure_calendar(
        db, project.id, {"platforms": ["telegram"], "frequency": "daily"}, owner.id
    )
    for i in range(6):
        db.add(
            MediaAsset(
                project_id=project.id,
                file_name=f"img{i}.jpg",
                yandex_disk_path=f"/SMM/img{i}.jpg",
                status="approved",
            )
        )
    db.commit()
    get_platform_connection_service().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCDEF", "external_id": "@ch"}
    )
    BillingService().credit_payment(db, account.id, 100, idempotency_key="seed")


def test_get_or_create_profile(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-prof")
    profile = _svc().get_or_create_profile(db_session, project.id, owner.id)
    assert profile.mode == "full_auto"
    assert profile.is_enabled is False
    # Идемпотентно: второй вызов возвращает тот же профиль.
    again = _svc().get_or_create_profile(db_session, project.id)
    assert again.id == profile.id


def test_health_check_missing_platform(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-nop")
    result = _svc().run_health_check(db_session, project.id)
    types = [b["type"] for b in result["blockers"]]
    assert "no_platform_connected" in types


def test_health_check_missing_yandex_disk(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-noyd")
    result = _svc().run_health_check(db_session, project.id)
    assert "no_yandex_disk" in [b["type"] for b in result["blockers"]]


def test_health_check_missing_calendar(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-nocal")
    _svc().configure_yandex_disk(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    result = _svc().run_health_check(db_session, project.id)
    assert "no_calendar" in [b["type"] for b in result["blockers"]]


def test_ready_when_platform_disk_calendar_media_balance(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-ready")
    _fully_setup(db_session, account, project, owner)
    result = _svc().run_health_check(db_session, project.id)
    setup_blockers = [b for b in result["blockers"] if b["severity"] in ("setup", "blocking")]
    assert not setup_blockers
    assert result["status"] == "ready"


def test_start_blocked_when_blockers(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-blk")
    out = _svc().start_autopilot(db_session, project.id, owner.id)
    assert out["ok"] is False
    assert out["status"] in ("setup_required", "blocked")


def test_start_running_when_ready(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-run")
    _fully_setup(db_session, account, project, owner)
    out = _svc().start_autopilot(db_session, project.id, owner.id)
    assert out["ok"] is True
    assert out["status"] == "running"
    # full_auto основной, но live выключен → авто-публикации нет (посты на проверку).
    assert out["auto_publish"] is False


def test_pause_sets_paused(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-pause")
    _fully_setup(db_session, account, project, owner)
    _svc().start_autopilot(db_session, project.id, owner.id)
    out = _svc().pause_autopilot(db_session, project.id, owner.id)
    assert out["status"] == "paused"
    profile = autopilot_repo.get_profile_by_project_id(db_session, project.id)
    assert profile.is_enabled is False


def test_configure_calendar_creates_plan_and_rules(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-cal")
    out = _svc().configure_calendar(
        db_session,
        project.id,
        {"platforms": ["telegram", "vk"], "frequency": "weekdays", "publish_times": ["11:00"]},
        owner.id,
    )
    assert out["ok"] is True
    assert out["plan_id"]
    assert out["calendar_rules"]["weekdays"] == [0, 1, 2, 3, 4]
    profile = autopilot_repo.get_profile_by_project_id(db_session, project.id)
    assert profile.calendar_rules["frequency"] == "weekdays"


def test_configure_yandex_disk_stores_resource(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-yd")
    out = _svc().configure_yandex_disk(
        db_session,
        project.id,
        {"public_url": "https://disk.yandex.ru/d/abc", "root_folder": "Media"},
        owner.id,
    )
    assert out["ok"] is True
    assert out["resource_id"] is not None
    profile = autopilot_repo.get_profile_by_project_id(db_session, project.id)
    assert profile.yandex_resource_id == out["resource_id"]


def test_yandex_disk_requires_url(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-ydreq")
    with pytest.raises(AutopilotError):
        _svc().configure_yandex_disk(db_session, project.id, {"public_url": ""}, owner.id)


def test_no_live_flags_modified(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-live")
    _fully_setup(db_session, account, project, owner)
    settings = Settings()
    AutopilotService(settings=settings).start_autopilot(db_session, project.id, owner.id)
    # Старт автопилота НЕ включает глобальные live-флаги публикации.
    assert settings.telegram_live_publishing_enabled is False
    assert settings.vk_live_publishing_enabled is False
    assert settings.instagram_live_publishing_enabled is False


def test_dashboard_no_raw_tokens(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-tok")
    get_platform_connection_service().upsert_connection(
        db_session,
        project.id,
        "telegram",
        {"api_key": "999999:SECRETtokenABCDEF", "external_id": "@c"},
    )
    dashboard = _svc().build_autopilot_dashboard(db_session, project.id)
    assert "999999:SECRET" not in str(dashboard)


def test_invalid_mode_rejected(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ap-mode")
    with pytest.raises(AutopilotError):
        _svc().update_autopilot_mode(db_session, project.id, "turbo", owner.id)


def test_project_not_found(db_session: Session) -> None:
    with pytest.raises(AutopilotError):
        _svc().get_or_create_profile(db_session, 999999)
