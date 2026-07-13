"""Тесты REST API автопилота (v0.5.6, offline). Project access; без live-публикаций/publish-due."""

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
    account, project, owner = _seed(db_session, "apa-auth")
    assert client.get(f"/autopilot/projects/{project.id}").status_code == 401


def test_dashboard_works(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-dash")
    r = client.get(f"/autopilot/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    body = r.json()
    assert "status" in body and "setup_progress" in body and "blockers" in body


def test_checklist_works(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-chk")
    r = client.get(f"/autopilot/projects/{project.id}/checklist", headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["total"] == 7


def test_health_check_works(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-hc")
    r = client.post(f"/autopilot/projects/{project.id}/health-check", headers=_h(owner.id))
    assert r.status_code == 200
    assert "blockers" in r.json()


def test_configure_calendar(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-cal")
    r = client.post(
        f"/autopilot/projects/{project.id}/calendar",
        json={"platforms": ["telegram"], "frequency": "weekdays"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["plan_id"]


def test_configure_yandex_disk(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-yd")
    r = client.post(
        f"/autopilot/projects/{project.id}/yandex-disk",
        json={"public_url": "https://disk.yandex.ru/d/x", "root_folder": "SMM"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_configure_content_rules(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-rl")
    r = client.post(
        f"/autopilot/projects/{project.id}/content-rules",
        json={"business_goal": "лиды", "tone": "экспертный"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["content_rules"]["business_goal"] == "лиды"


def test_start_pause(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-sp")
    # Без настройки старт блокируется.
    start = client.post(f"/autopilot/projects/{project.id}/start", headers=_h(owner.id))
    assert start.status_code == 200
    assert start.json()["ok"] is False
    pause = client.post(f"/autopilot/projects/{project.id}/pause", headers=_h(owner.id))
    assert pause.json()["status"] == "paused"


def test_preview_next_no_writes(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-prev")
    r = client.post(f"/autopilot/projects/{project.id}/preview-next", headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["live_calls"] is False


def test_mode_change(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-mode")
    r = client.post(
        f"/autopilot/projects/{project.id}/mode", json={"mode": "semi_auto"}, headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["mode"] == "semi_auto"


def test_client_summary(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-sum")
    r = client.get(f"/autopilot/projects/{project.id}/client-summary", headers=_h(owner.id))
    assert r.status_code == 200
    assert "headline" in r.json()


def test_no_raw_tokens_in_responses(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "apa-tok")
    client.post(
        f"/autopilot/projects/{project.id}/yandex-disk",
        json={"public_url": "https://disk.yandex.ru/d/x"},
        headers=_h(owner.id),
    )
    text = client.get(f"/autopilot/projects/{project.id}", headers=_h(owner.id)).text
    assert "api_key_encrypted" not in text
