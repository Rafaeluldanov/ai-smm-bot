"""Тесты REST API мониторинга live-автопилота (v0.6.1, offline).

Project/incident access; подтверждения стоп-крана; кросс-тенант 404; без секретов/публикаций.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    live_publish_attempt_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
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


def _failures(db: Session, account, project, n: int) -> None:
    for _ in range(n):
        live_publish_attempt_repository.create_attempt(
            db,
            account_id=account.id,
            project_id=project.id,
            platform_key="telegram",
            status="failed",
            mode="live",
            trigger="auto_schedule",
        )


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_project_access(client: TestClient, db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lama-auth")
    assert client.get(f"/live-autopilot-monitoring/projects/{project.id}").status_code == 401


def test_dashboard_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lama-dash")
    r = client.get(f"/live-autopilot-monitoring/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert "health_status" in body and "kill_switch" in body


def test_health_check_endpoint(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lama-hc")
    _failures(db_session, acc, project, 4)
    r = client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/health-check",
        headers=_h(owner.id),
        json={"dry_run": False},
    )
    assert r.status_code == 200
    assert r.json()["health_status"] == "degraded"


def test_incidents_and_transitions(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lama-inc")
    _failures(db_session, acc, project, 4)
    client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/health-check",
        headers=_h(owner.id),
        json={"dry_run": False},
    )
    listing = client.get(
        f"/live-autopilot-monitoring/projects/{project.id}/incidents", headers=_h(owner.id)
    )
    assert listing.status_code == 200
    incidents = listing.json()["incidents"]
    assert incidents
    incident_id = incidents[0]["id"]
    ack = client.post(
        f"/live-autopilot-monitoring/incidents/{incident_id}/acknowledge", headers=_h(owner.id)
    )
    assert ack.status_code == 200 and ack.json()["status"] == "acknowledged"


def test_incident_missing_404(client: TestClient, db_session: Session) -> None:
    _a, _project, owner = _seed(db_session, "lama-404")
    r = client.get("/live-autopilot-monitoring/incidents/999999", headers=_h(owner.id))
    assert r.status_code == 404


def test_pause_requires_confirmation(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lama-pc")
    r = client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/pause",
        headers=_h(owner.id),
        json={"confirmation": "wrong"},
    )
    assert r.status_code == 400


def test_pause_preview_never_pauses(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lama-prev")
    r = client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/pause-preview", headers=_h(owner.id)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["allowed"] is False
    assert body["confirmation_text"] == "PAUSE_AUTOPILOT"


def test_resume_platform_wrong_confirmation_400_not_500(
    client: TestClient, db_session: Session
) -> None:
    """resume площадки делегирует в readiness; неверное подтверждение → 400, не 500."""
    _a, project, owner = _seed(db_session, "lama-resplat")
    r = client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/platforms/telegram/resume",
        headers=_h(owner.id),
        json={"confirmation": "totally-wrong"},
    )
    assert r.status_code == 400


def test_pause_happy_path(client: TestClient, db_session: Session) -> None:
    from app.repositories import live_readiness_repository as lrr

    acc, project, owner = _seed(db_session, "lama-pause")
    # Включаем per-project live, чтобы было что реально выключать.
    pp = lrr.get_or_create_project_profile(db_session, acc.id, project.id)
    lrr.update_project_profile(
        db_session,
        pp,
        {"status": "ready", "project_live_enabled": True, "full_auto_live_enabled": True},
    )
    db_session.commit()
    r = client.post(
        f"/live-autopilot-monitoring/projects/{project.id}/pause",
        headers=_h(owner.id),
        json={"confirmation": "PAUSE_AUTOPILOT"},
    )
    assert r.status_code == 200
    assert r.json()["autopilot_paused"] is True
    assert r.json()["project_live_enabled"] is False
    # Реальный эффект: дашборд показывает выключенный per-project live (не только константы ответа).
    dash = client.get(
        f"/live-autopilot-monitoring/projects/{project.id}", headers=_h(owner.id)
    ).json()
    assert dash["kill_switch"]["project_live_enabled"] is False
    assert dash["kill_switch"]["can_publish_live"] is False


def test_cross_tenant_incident_blocked(client: TestClient, db_session: Session) -> None:
    acc_a, project_a, _owner_a = _seed(db_session, "lama-ta")
    _b, _project_b, owner_b = _seed(db_session, "lama-tb")
    _failures(db_session, acc_a, project_a, 4)
    client.post(
        f"/live-autopilot-monitoring/projects/{project_a.id}/health-check",
        headers=_h(_owner_a.id),
        json={"dry_run": False},
    )
    incident_id = client.get(
        f"/live-autopilot-monitoring/projects/{project_a.id}/incidents",
        headers=_h(_owner_a.id),
    ).json()["incidents"][0]["id"]
    # Владелец B не должен видеть инцидент проекта A.
    r = client.get(f"/live-autopilot-monitoring/incidents/{incident_id}", headers=_h(owner_b.id))
    assert r.status_code == 404


def test_no_secrets_in_response(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lama-secret")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@x"}
    )
    db_session.commit()
    _failures(db_session, acc, project, 2)
    r = client.get(f"/live-autopilot-monitoring/projects/{project.id}", headers=_h(owner.id))
    assert "123456:SECRETxyz" not in r.text
