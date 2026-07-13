"""Тесты сервиса live-readiness (v0.5.9, offline).

Готовность проекта/площадок, блокеры, включение с подтверждением/порогом, эффективный гейт.
Ключевой инвариант: per-project/per-platform switch НЕ обходит глобальные live-флаги; сервис их
никогда не меняет. Без реальных публикаций и внешних вызовов.
"""

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models.media_asset import MediaAsset
from app.repositories import (
    account_repository,
    autopilot_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.autopilot_service import AutopilotService
from app.services.billing_service import BillingService
from app.services.live_readiness_service import LiveReadinessError, LiveReadinessService
from app.services.platform_connection_service import PlatformConnectionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _make_ready(db: Session, account, project) -> None:
    """Полностью подготовить проект: автопилот, календарь, медиа, баланс, telegram."""
    ap = autopilot_repository.get_or_create_profile(
        db, account_id=account.id, project_id=project.id, default_mode="full_auto"
    )
    ap.is_enabled = True
    ap.status = "running"
    db.commit()
    AutopilotService().configure_calendar(
        db,
        project.id,
        {"platforms": ["telegram"], "frequency": "weekdays", "publish_times": ["10:00"]},
    )
    for i in range(40):
        db.add(
            MediaAsset(project_id=project.id, file_name=f"i{i}.jpg", yandex_disk_path=f"/i{i}.jpg")
        )
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{project.id}")
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@chan"}
    )
    db.commit()


def test_project_profile_created(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lr-prof")
    profile = LiveReadinessService().get_or_create_project_profile(db_session, project.id)
    assert profile.project_id == project.id
    assert profile.project_live_enabled is False
    assert profile.status == "not_checked"


def test_missing_autopilot_and_calendar_blockers(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lr-block")
    chk = LiveReadinessService().run_project_readiness_check(db_session, project.id, dry_run=True)
    types = {b["type"] for b in chk["blockers"]}
    assert "no_autopilot_profile" in types
    assert "no_calendar" in types
    assert "no_media" in types
    assert chk["can_enable_live"] is False


def test_insufficient_balance_blocker(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-bal")
    _make_ready(db_session, acc, project)
    # Слить весь баланс.
    BillingService().debit_for_action(
        db_session, acc.id, units=500, usage_type="test_drain", idempotency_key="lr-drain"
    )
    db_session.commit()
    chk = LiveReadinessService().run_project_readiness_check(db_session, project.id, dry_run=True)
    assert any(b["type"] == "insufficient_balance" for b in chk["blockers"])


def test_ready_when_all_conditions_met(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-ready")
    _make_ready(db_session, acc, project)
    chk = LiveReadinessService().run_project_readiness_check(db_session, project.id, dry_run=True)
    assert chk["status"] == "ready"
    assert chk["readiness_score"] >= 85
    assert chk["can_enable_live"] is True


def test_enable_project_requires_confirmation(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-conf")
    _make_ready(db_session, acc, project)
    svc = LiveReadinessService()
    try:
        svc.enable_project_live(db_session, project.id, "WRONG")
        raise AssertionError("should have raised")
    except LiveReadinessError as exc:
        assert "подтверждение" in str(exc).lower()


def test_enable_project_requires_score_threshold(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lr-thresh")  # не готов
    svc = LiveReadinessService()
    try:
        svc.enable_project_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
        raise AssertionError("should have raised")
    except LiveReadinessError as exc:
        assert "готов" in str(exc).lower()


def test_enable_platform_requires_confirmation(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-pconf")
    _make_ready(db_session, acc, project)
    svc = LiveReadinessService()
    try:
        svc.enable_platform_live(db_session, project.id, "telegram", "WRONG")
        raise AssertionError("should have raised")
    except LiveReadinessError as exc:
        assert "подтверждение" in str(exc).lower()


def test_full_auto_requires_project_and_platform_ready(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-fa")
    _make_ready(db_session, acc, project)
    svc = LiveReadinessService()
    # Без project live включения — full-auto нельзя.
    try:
        svc.enable_full_auto_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
        raise AssertionError("should have raised")
    except LiveReadinessError:
        pass
    # Включаем project + platform → теперь full-auto проходит.
    svc.enable_project_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    svc.enable_platform_live(db_session, project.id, "telegram", "ENABLE_PLATFORM_LIVE")
    result = svc.enable_full_auto_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    assert result["full_auto_live_enabled"] is True


def test_effective_gate_requires_global_flag(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-gate")
    _make_ready(db_session, acc, project)
    svc = LiveReadinessService()
    svc.enable_project_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    svc.enable_platform_live(db_session, project.id, "telegram", "ENABLE_PLATFORM_LIVE")
    svc.enable_full_auto_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    # Глобальный флаг выключен → публиковать нельзя.
    gate_off = svc.build_effective_live_gate(db_session, project.id, "telegram")
    assert gate_off["can_publish_live"] is False
    assert "global_live_flag_disabled" in gate_off["blocked_reasons"]
    # Глобальный флаг включён (через settings) → можно.
    svc_on = LiveReadinessService(settings=Settings(telegram_live_publishing_enabled=True))
    gate_on = svc_on.build_effective_live_gate(db_session, project.id, "telegram")
    assert gate_on["can_publish_live"] is True


def test_no_global_live_flags_changed(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-noflags")
    _make_ready(db_session, acc, project)
    svc = LiveReadinessService()
    svc.enable_project_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    svc.enable_platform_live(db_session, project.id, "telegram", "ENABLE_PLATFORM_LIVE")
    svc.enable_full_auto_live(db_session, project.id, "ENABLE_LIVE_AUTOPILOT")
    s = get_settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_dashboard_and_no_secrets(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lr-dash")
    _make_ready(db_session, acc, project)
    dash = LiveReadinessService().build_project_live_dashboard(db_session, project.id)
    assert "status_label" in dash and "checklist" in dash and "confirmation" in dash
    assert "123456:ABCdef" not in str(dash)


def test_coming_soon_platforms(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lr-soon")
    res = LiveReadinessService().run_platform_readiness_check(
        db_session, project.id, "max", dry_run=True
    )
    assert res["coming_soon"] is True
    assert res["status"] == "blocked"
