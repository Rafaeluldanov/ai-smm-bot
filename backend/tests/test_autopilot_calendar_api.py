"""Тесты REST API Calendar Assistant (v0.5.8, offline). Project access; без live-публикаций."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_project_access(client: TestClient, db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "aca-auth")
    assert client.get(f"/autopilot-calendar/projects/{project.id}").status_code == 401


def test_dashboard(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-dash")
    r = client.get(f"/autopilot-calendar/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert "has_active_plan" in body and "presets" in body


def test_presets(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-pre")
    r = client.get(f"/autopilot-calendar/projects/{project.id}/presets", headers=_h(owner.id))
    assert r.status_code == 200
    assert len(r.json()["presets"]) == 8


def test_recommend(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-rec")
    r = client.post(f"/autopilot-calendar/projects/{project.id}/recommend", headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["recommended_preset"]


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-prev")
    r = client.post(
        f"/autopilot-calendar/projects/{project.id}/preview",
        json={"preset": "three_per_week", "goal": "mixed"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["writes"] is False
    assert body["weekdays"] == [0, 2, 4]


def test_create_dry_run(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-dry")
    r = client.post(
        f"/autopilot-calendar/projects/{project.id}/create-dry-run",
        json={"preset": "two_per_week"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is True


def test_create_and_apply(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-apply")
    created = client.post(
        f"/autopilot-calendar/projects/{project.id}/create",
        json={"preset": "two_per_week", "goal": "leads"},
        headers=_h(owner.id),
    )
    assert created.status_code == 200
    plan_id = created.json()["id"]
    applied = client.post(
        f"/autopilot-calendar/projects/{project.id}/plans/{plan_id}/apply",
        headers=_h(owner.id),
    )
    assert applied.status_code == 200
    body = applied.json()
    assert body["ok"] is True
    assert body["live_publish"] is False
    assert body["publishing_plan_id"]


def test_pause_resume(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-pr")
    created = client.post(
        f"/autopilot-calendar/projects/{project.id}/create",
        json={"preset": "daily"},
        headers=_h(owner.id),
    ).json()
    client.post(
        f"/autopilot-calendar/projects/{project.id}/plans/{created['id']}/apply",
        headers=_h(owner.id),
    )
    paused = client.post(f"/autopilot-calendar/projects/{project.id}/pause", headers=_h(owner.id))
    assert paused.json()["status"] == "paused"
    resumed = client.post(f"/autopilot-calendar/projects/{project.id}/resume", headers=_h(owner.id))
    assert resumed.json()["status"] == "active"


def test_no_raw_tokens_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "aca-tok")
    text = client.get(f"/autopilot-calendar/projects/{project.id}", headers=_h(owner.id)).text
    assert "api_key_encrypted" not in text
    assert "password_hash" not in text
