"""Тесты REST API авто-синхронизации Яндекс Диска (v0.5.7, offline). Без сети/удаления/live."""

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
    account, project, owner = _seed(db_session, "ysa-auth")
    assert client.get(f"/yandex-sync/projects/{project.id}").status_code == 401


def test_dashboard_works(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-dash")
    r = client.get(f"/yandex-sync/projects/{project.id}", headers=_h(owner.id))
    assert r.status_code == 200
    assert "status" in r.json() and "media_count" in r.json()


def test_profile_get_post(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-prof")
    assert (
        client.get(f"/yandex-sync/projects/{project.id}/profile", headers=_h(owner.id)).status_code
        == 200
    )
    r = client.post(
        f"/yandex-sync/projects/{project.id}/profile",
        json={"public_url": "https://disk.yandex.ru/d/x", "root_folder": "SMM"},
        headers=_h(owner.id),
    )
    assert r.status_code == 200
    assert r.json()["has_public_url"] is True


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-prev")
    r = client.post(f"/yandex-sync/projects/{project.id}/preview", json={}, headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["writes"] is False


def test_run_dry(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-dry")
    r = client.post(f"/yandex-sync/projects/{project.id}/run-dry", headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["status"] == "preview"


def test_run_non_dry_network_off_blocked(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-net")
    r = client.post(
        f"/yandex-sync/projects/{project.id}/run", json={"dry_run": False}, headers=_h(owner.id)
    )
    assert r.status_code == 200
    assert r.json()["status"] == "blocked"


def test_pause_resume(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-pr")
    assert (
        client.post(f"/yandex-sync/projects/{project.id}/pause", headers=_h(owner.id)).json()[
            "status"
        ]
        == "paused"
    )
    assert (
        client.post(f"/yandex-sync/projects/{project.id}/resume", headers=_h(owner.id)).json()[
            "status"
        ]
        == "ready"
    )


def test_runs_list(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-runs")
    client.post(f"/yandex-sync/projects/{project.id}/run-dry", headers=_h(owner.id))
    r = client.get(f"/yandex-sync/projects/{project.id}/runs", headers=_h(owner.id))
    assert r.status_code == 200
    assert len(r.json()) >= 1


def test_user_cannot_access_another_project(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-own")
    other = user_repository.create_user(db_session, email="other@e.com", password_hash="x")
    db_session.commit()
    assert (
        client.get(f"/yandex-sync/projects/{project.id}", headers=_h(other.id)).status_code == 404
    )


def test_no_delete_endpoint(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-del")
    # Эндпоинта удаления нет → 405 Method Not Allowed.
    assert (
        client.delete(f"/yandex-sync/projects/{project.id}", headers=_h(owner.id)).status_code
        == 405
    )


def test_no_secrets_or_internal_paths(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-safe")
    client.post(
        f"/yandex-sync/projects/{project.id}/profile",
        json={"public_url": "https://disk.yandex.ru/d/SECRET123"},
        headers=_h(owner.id),
    )
    text = client.get(f"/yandex-sync/projects/{project.id}", headers=_h(owner.id)).text
    assert "/d/SECRET123" not in text
    assert "public_url" not in text or "public_url_masked" in text


def test_worker_tick_dry(client: TestClient, db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysa-wt")
    r = client.post("/yandex-sync/worker/tick-dry", headers=_h(owner.id))
    assert r.status_code == 200
    assert r.json()["enabled"] is False
