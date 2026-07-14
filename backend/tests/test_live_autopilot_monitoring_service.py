"""Тесты сервиса мониторинга live-автопилота (v0.6.1, offline).

Инварианты:
- health-check в dry-run НЕ пишет в БД; non-dry сохраняет снимок;
- повторные сбои → инцидент + degraded; авто-пауза по умолчанию только preview (не действует);
- пауза требует подтверждения и реально выключает per-project live (движок это учитывает);
- возобновление НЕ перевзводит реальную публикацию;
- секретов/токенов в представлениях нет; глобальные live-флаги не меняются.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.live_autopilot_incident import LiveAutopilotIncident
from app.models.live_autopilot_monitor_snapshot import LiveAutopilotMonitorSnapshot
from app.repositories import (
    account_repository,
    live_publish_attempt_repository,
    project_repository,
    user_repository,
)
from app.repositories import live_readiness_repository as lrr
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.live_autopilot_monitoring_service import (
    LiveAutopilotMonitoringError,
    LiveAutopilotMonitoringService,
)
from app.services.platform_connection_service import PlatformConnectionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, owner


def _attempt(db: Session, account, project, status: str) -> None:
    live_publish_attempt_repository.create_attempt(
        db,
        account_id=account.id,
        project_id=project.id,
        platform_key="telegram",
        status=status,
        mode="live",
        trigger="auto_schedule",
    )


def _enable_project_live(db: Session, account, project) -> None:
    pp = lrr.get_or_create_project_profile(db, account.id, project.id)
    lrr.update_project_profile(
        db, pp, {"status": "ready", "project_live_enabled": True, "full_auto_live_enabled": True}
    )
    db.commit()


def test_dashboard_unknown_without_attempts(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lam-dash")
    d = LiveAutopilotMonitoringService().build_dashboard(db_session, project.id)
    assert d["health_status"] == "unknown"
    assert "kill_switch" in d and d["kill_switch"]["enabled"] is True
    assert d["auto_pause"]["enabled"] is False


def test_health_check_dry_run_no_writes(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-dry")
    # Сеем >= порога сбоев, чтобы в non-dry завёлся бы инцидент — проверяем, что dry-run НЕ пишет
    # ни снимок, ни инцидент.
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    before_snap = db_session.query(LiveAutopilotMonitorSnapshot).count()
    before_inc = db_session.query(LiveAutopilotIncident).count()
    result = LiveAutopilotMonitoringService().run_health_check(db_session, project.id, dry_run=True)
    assert result["dry_run"] is True
    assert result["snapshot_created"] is False
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == before_snap
    assert db_session.query(LiveAutopilotIncident).count() == before_inc == 0


def test_single_failure_is_warning_not_degraded(db_session: Session) -> None:
    """Одиночный сбой на крошечной выборке — «warning», а не «degraded» (мин. выборка)."""
    acc, project, _o = _seed(db_session, "lam-single")
    _attempt(db_session, acc, project, "failed")
    result = LiveAutopilotMonitoringService().run_health_check(db_session, project.id, dry_run=True)
    assert result["health_status"] == "warning"


def test_health_check_persists_snapshot(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-persist")
    _attempt(db_session, acc, project, "published")
    result = LiveAutopilotMonitoringService().run_health_check(
        db_session, project.id, dry_run=False
    )
    assert result["snapshot_created"] is True
    assert result["total_attempts"] == 1
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == 1


def test_repeated_failures_open_incident_and_degraded(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-fail")
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    svc = LiveAutopilotMonitoringService()
    result = svc.run_health_check(db_session, project.id, dry_run=False)
    assert result["health_status"] == "degraded"
    assert len(result["incidents_created"]) >= 1
    incidents = db_session.query(LiveAutopilotIncident).all()
    assert any(i.incident_type == "repeated_publish_failures" for i in incidents)
    # Авто-пауза выключена по умолчанию → только preview, без реальной паузы.
    assert (result["auto_pause"] or {}).get("paused") is not True


def test_incident_dedup_increments_occurrences(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-dedup")
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    svc = LiveAutopilotMonitoringService()
    svc.run_health_check(db_session, project.id, dry_run=False)
    svc.run_health_check(db_session, project.id, dry_run=False)
    incidents = [
        i
        for i in db_session.query(LiveAutopilotIncident).all()
        if i.incident_type == "repeated_publish_failures"
    ]
    assert len(incidents) == 1  # не плодит дубли
    assert incidents[0].occurrences >= 2


def test_pause_requires_confirmation(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lam-pauseconf")
    svc = LiveAutopilotMonitoringService()
    with pytest.raises(LiveAutopilotMonitoringError):
        svc.pause_project_autopilot(db_session, project.id, confirmation="wrong")


def test_pause_disables_project_live(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-pause")
    _enable_project_live(db_session, acc, project)
    svc = LiveAutopilotMonitoringService()
    res = svc.pause_project_autopilot(db_session, project.id, confirmation="PAUSE_AUTOPILOT")
    assert res["autopilot_paused"] is True
    assert res["project_live_enabled"] is False
    # Движок увидит выключенный per-project live через gate.
    gate = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert gate["project_live_enabled"] is False
    assert gate["can_publish_live"] is False


def test_resume_does_not_reenable_live(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-resume")
    _enable_project_live(db_session, acc, project)
    svc = LiveAutopilotMonitoringService()
    svc.pause_project_autopilot(db_session, project.id, confirmation="PAUSE_AUTOPILOT")
    res = svc.resume_project_autopilot(db_session, project.id, confirmation="RESUME_AUTOPILOT")
    assert res["live_re_enabled"] is False
    gate = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert gate["project_live_enabled"] is False  # live остаётся выключенным


def test_resume_requires_confirmation(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lam-resconf")
    svc = LiveAutopilotMonitoringService()
    with pytest.raises(LiveAutopilotMonitoringError):
        svc.resume_project_autopilot(db_session, project.id, confirmation="nope")


def test_incident_lifecycle(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-life")
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    svc = LiveAutopilotMonitoringService()
    svc.run_health_check(db_session, project.id, dry_run=False)
    inc = db_session.query(LiveAutopilotIncident).first()
    assert svc.acknowledge_incident(db_session, inc.id)["status"] == "acknowledged"
    assert svc.resolve_incident(db_session, inc.id)["status"] == "resolved"


def test_get_incident_missing_raises(db_session: Session) -> None:
    svc = LiveAutopilotMonitoringService()
    with pytest.raises(LiveAutopilotMonitoringError) as exc:
        svc.get_incident(db_session, 999999)
    assert "не найден" in str(exc.value)


def test_pause_missing_project_raises(db_session: Session) -> None:
    svc = LiveAutopilotMonitoringService()
    with pytest.raises(LiveAutopilotMonitoringError) as exc:
        svc.pause_project_autopilot(db_session, 999999, confirmation="PAUSE_AUTOPILOT")
    assert "не найден" in str(exc.value)


def test_auto_pause_acts_when_enabled(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-autopause")
    _enable_project_live(db_session, acc, project)
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    settings = Settings(
        live_autopilot_auto_pause_enabled=True, live_autopilot_auto_pause_critical_only=False
    )
    svc = LiveAutopilotMonitoringService(settings=settings)
    result = svc.run_health_check(db_session, project.id, dry_run=False)
    assert (result["auto_pause"] or {}).get("paused") is True
    gate = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert gate["project_live_enabled"] is False  # авто-пауза реально остановила live


def test_auto_pause_critical_only_no_pause_below_critical(db_session: Session) -> None:
    """auto_pause включён, critical_only=True (дефолт), доля сбоев ниже критической → НЕ пауза."""
    acc, project, _o = _seed(db_session, "lam-critonly")
    _enable_project_live(db_session, acc, project)
    # 3 сбоя из 100 (порог по числу сбоев достигнут: 3), но доля 0.03 < critical 0.50 → нет паузы.
    for _ in range(97):
        _attempt(db_session, acc, project, "published")
    for _ in range(3):
        _attempt(db_session, acc, project, "failed")
    settings = Settings(
        live_autopilot_auto_pause_enabled=True, live_autopilot_auto_pause_critical_only=True
    )
    svc = LiveAutopilotMonitoringService(settings=settings)
    result = svc.run_health_check(db_session, project.id, dry_run=False)
    assert (result["auto_pause"] or {}).get("paused") is not True
    gate = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert gate["project_live_enabled"] is True  # live НЕ выключен на низкой доле сбоев


def test_analyze_project_health_metrics(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-analyze")
    for _ in range(4):
        _attempt(db_session, acc, project, "published")
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    h = LiveAutopilotMonitoringService().analyze_project_health(db_session, project.id)
    assert h["successful_attempts"] == 4
    assert h["failed_attempts"] == 4
    assert h["failure_rate"] == 0.5
    assert h["health_status"] == "degraded"


def test_preview_pause_never_pauses(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-prevpause")
    _enable_project_live(db_session, acc, project)
    svc = LiveAutopilotMonitoringService()
    before = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    pv = svc.preview_pause(db_session, project.id)
    after = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert pv["allowed"] is False
    assert pv["confirmation_text"] == "PAUSE_AUTOPILOT"
    assert "telegram" in pv["affected_platforms"]
    # Предпросмотр НЕ поставил паузу.
    assert before["project_live_enabled"] == after["project_live_enabled"] is True


def test_create_snapshot_and_detect_incidents_public(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-public")
    for _ in range(4):
        _attempt(db_session, acc, project, "failed")
    svc = LiveAutopilotMonitoringService()
    snap = svc.create_snapshot(db_session, project.id)
    assert db_session.query(LiveAutopilotMonitorSnapshot).count() == 1
    assert snap["health_status"] == "degraded"
    first = svc.detect_incidents(db_session, project.id)
    second = svc.detect_incidents(db_session, project.id)
    assert first["count"] == 1
    assert second["count"] == 0  # дедуп: повтор не плодит инцидент
    assert (
        db_session.query(LiveAutopilotIncident)
        .filter(LiveAutopilotIncident.incident_type == "repeated_publish_failures")
        .count()
        == 1
    )


def test_pause_resume_aliases(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-alias")
    _enable_project_live(db_session, acc, project)
    svc = LiveAutopilotMonitoringService()
    with pytest.raises(LiveAutopilotMonitoringError):
        svc.pause_autopilot(db_session, project.id, confirmation_text="nope")
    res = svc.pause_autopilot(db_session, project.id, confirmation_text="PAUSE_AUTOPILOT")
    assert res["autopilot_paused"] is True
    gate = svc._readiness_service().build_effective_live_gate(db_session, project.id, "telegram")
    assert gate["project_live_enabled"] is False
    resume = svc.resume_autopilot(db_session, project.id, confirmation_text="RESUME_AUTOPILOT")
    assert resume["live_re_enabled"] is False


def test_dashboard_has_spec_keys(db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lam-speckeys")
    dash = LiveAutopilotMonitoringService().build_dashboard(db_session, project.id)
    for key in (
        "monitoring_enabled",
        "dry_run",
        "health_status",
        "publish_attempts",
        "successful_attempts",
        "failed_attempts",
        "failure_rate",
        "incidents_count",
        "active_incidents",
        "autopilot_paused",
        "platforms",
        "blockers",
        "recommendations",
    ):
        assert key in dash, key


def test_no_secrets_in_dashboard(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-secret")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@x"}
    )
    db_session.commit()
    _attempt(db_session, acc, project, "failed")
    svc = LiveAutopilotMonitoringService()
    dash = svc.build_dashboard(db_session, project.id)
    svc.run_health_check(db_session, project.id, dry_run=False)
    snaps = svc.list_snapshots(db_session, project.id)
    assert "123456:SECRETxyz" not in str(dash)
    assert "123456:SECRETxyz" not in str(snaps)


def test_no_global_flags_changed(db_session: Session) -> None:
    acc, project, _o = _seed(db_session, "lam-noglobal")
    _enable_project_live(db_session, acc, project)
    settings = Settings()
    svc = LiveAutopilotMonitoringService(settings=settings)
    svc.pause_project_autopilot(db_session, project.id, confirmation="PAUSE_AUTOPILOT")
    svc.resume_project_autopilot(db_session, project.id, confirmation="RESUME_AUTOPILOT")
    assert settings.telegram_live_publishing_enabled is False
    assert settings.vk_live_publishing_enabled is False
