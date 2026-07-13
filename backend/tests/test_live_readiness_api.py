"""Тесты REST API live-readiness (v0.5.9, offline). Project access; подтверждения; без live."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
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
from app.services.platform_connection_service import PlatformConnectionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _make_ready(db: Session, account, project) -> None:
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


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_project_access(client: TestClient, db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "lra-auth")
    assert client.get(f"/live-readiness/projects/{project.id}").status_code == 401


def test_dashboard_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lra-dash")
    r = client.get(f"/live-readiness/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    assert "status_label" in r.json() and "checklist" in r.json()


def test_check_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lra-check")
    r = client.post(f"/live-readiness/projects/{project.id}/check", headers=_h(owner.id))
    assert r.status_code == 200
    assert "readiness_score" in r.json()


def test_platform_check_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lra-pchk")
    r = client.post(
        f"/live-readiness/projects/{project.id}/platforms/telegram/check", headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["platform_key"] == "telegram"


def test_enable_project_with_confirmation(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lra-en")
    _make_ready(db_session, acc, project)
    r = client.post(
        f"/live-readiness/projects/{project.id}/enable",
        json={"confirmation": "ENABLE_LIVE_AUTOPILOT"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["project_live_enabled"] is True
    assert r.json()["global_flags_changed"] is False


def test_enable_platform_with_confirmation(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lra-pen")
    _make_ready(db_session, acc, project)
    r = client.post(
        f"/live-readiness/projects/{project.id}/platforms/telegram/enable",
        json={"confirmation": "ENABLE_PLATFORM_LIVE"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["platform_live_enabled"] is True


def test_wrong_confirmation_rejected(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lra-wrong")
    _make_ready(db_session, acc, project)
    r = client.post(
        f"/live-readiness/projects/{project.id}/enable",
        json={"confirmation": "nope"},
        headers=_h(owner.id),
    )
    assert r.status_code == 400


def test_effective_gate_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "lra-gate")
    r = client.get(
        f"/live-readiness/projects/{project.id}/effective/telegram", headers=_h(owner.id)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["can_publish_live"] is False
    assert "global_live_flag_disabled" in body["blocked_reasons"]


def test_cannot_access_another_project(client: TestClient, db_session: Session) -> None:
    _a1, project1, _o1 = _seed(db_session, "lra-t1")
    _a2, _project2, owner2 = _seed(db_session, "lra-t2")
    r = client.get(f"/live-readiness/projects/{project1.id}", headers=_h(owner2.id))
    assert r.status_code in (403, 404)


def test_no_raw_tokens_in_responses(client: TestClient, db_session: Session) -> None:
    acc, project, owner = _seed(db_session, "lra-tok")
    _make_ready(db_session, acc, project)
    text = client.get(f"/live-readiness/projects/{project.id}", headers=_h(owner.id)).text
    assert "123456:ABCdef" not in text
    assert "api_key_encrypted" not in text
