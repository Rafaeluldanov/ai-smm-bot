"""Тесты REST API Telegram live rollout (v0.6.0, offline). Project access; без реальной отправки."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@chan"}
    )
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="T",
            status="approved",
            telegram_text="Hi #x",
            hashtags=["x"],
        ),
    )
    db.commit()
    return account, project, owner, post


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_requires_project_access(client: TestClient, db_session: Session) -> None:
    _a, project, _o, _p = _seed(db_session, "tga-auth")
    assert client.get(f"/telegram-live-rollout/projects/{project.id}").status_code == 401


def test_dashboard_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner, _p = _seed(db_session, "tga-dash")
    r = client.get(f"/telegram-live-rollout/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    assert "status" in r.json() and "telegram_platform_status" in r.json()


def test_effective_status_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner, _p = _seed(db_session, "tga-eff")
    r = client.get(
        f"/telegram-live-rollout/projects/{project.id}/effective-status", headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["can_send_real"] is False


def test_attempts_list_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner, post = _seed(db_session, "tga-list")
    client.post(
        f"/telegram-live-rollout/projects/{project.id}/run-dry",
        json={"post_id": post.id},
        headers=_h(owner.id),
    )
    r = client.get(f"/telegram-live-rollout/projects/{project.id}/attempts", headers=_h(owner.id))
    assert r.status_code == 200
    assert len(r.json()["attempts"]) >= 1


def test_preview_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner, post = _seed(db_session, "tga-prev")
    r = client.post(
        f"/telegram-live-rollout/projects/{project.id}/preview",
        json={"post_id": post.id},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["writes"] is False


def test_run_dry_works(client: TestClient, db_session: Session) -> None:
    _a, project, owner, post = _seed(db_session, "tga-dry")
    r = client.post(
        f"/telegram-live-rollout/projects/{project.id}/run-dry",
        json={"post_id": post.id},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["live_calls"] is False


def test_publish_once_blocked_by_default(client: TestClient, db_session: Session) -> None:
    _a, project, owner, post = _seed(db_session, "tga-pub")
    r = client.post(
        f"/telegram-live-rollout/projects/{project.id}/publish-once-if-allowed",
        json={"post_id": post.id, "confirmation": "ENABLE_TELEGRAM_LIVE"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"
    assert r.json()["live_attempted"] is False


def test_cannot_access_another_project(client: TestClient, db_session: Session) -> None:
    _a1, project1, _o1, _p1 = _seed(db_session, "tga-t1")
    _a2, _project2, owner2, _p2 = _seed(db_session, "tga-t2")
    r = client.get(f"/telegram-live-rollout/projects/{project1.id}", headers=_h(owner2.id))
    assert r.status_code in (403, 404)


def test_no_raw_tokens_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, owner, post = _seed(db_session, "tga-tok")
    client.post(
        f"/telegram-live-rollout/projects/{project.id}/run-dry",
        json={"post_id": post.id},
        headers=_h(owner.id),
    )
    text = client.get(f"/telegram-live-rollout/projects/{project.id}", headers=_h(owner.id)).text
    assert "123456:ABCdef" not in text
    assert "api_key_encrypted" not in text
