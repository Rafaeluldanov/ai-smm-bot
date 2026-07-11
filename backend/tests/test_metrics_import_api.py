"""Тесты API импорта метрик (v0.4.1, offline, tenant-изоляция)."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService

_VK_SECRET = "vk1234567890secrettoken"


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="Пост",
            status="scheduled",
            vk_text="Заказать мерч #мерч",
            hashtags=["мерч"],
        ),
    )
    post.scheduled_at = datetime(2026, 7, 13, 18, 0, tzinfo=UTC)
    pub = post_publication_repository.create_publication(
        db,
        PostPublicationCreate(
            post_id=post.id,
            project_id=project.id,
            platform="vk",
            target_id="-1",
            status="scheduled",
        ),
    )
    db.commit()
    return account, project, pub, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_requires_project_access(client: TestClient, db_session: Session) -> None:
    _acc, project, _pub, token = _seed(db_session, "mia-prev")
    r = client.post(
        f"/metrics/projects/{project.id}/preview", json={"source": "demo"}, headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["publications_found"] == 1


def test_run_dry_no_writes(client: TestClient, db_session: Session) -> None:
    _acc, project, _pub, token = _seed(db_session, "mia-dry")
    r = client.post(
        f"/metrics/projects/{project.id}/run-dry", json={"source": "demo"}, headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    runs = client.get(f"/metrics/projects/{project.id}/imports", headers=_h(token)).json()
    assert runs == []  # dry-run не создаёт прогон


def test_run_creates_import_run(client: TestClient, db_session: Session) -> None:
    _acc, project, _pub, token = _seed(db_session, "mia-run")
    r = client.post(
        f"/metrics/projects/{project.id}/run",
        json={"source": "demo", "idempotency_key": "api-run"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "imported"
    runs = client.get(f"/metrics/projects/{project.id}/imports", headers=_h(token)).json()
    assert len(runs) == 1
    assert runs[0]["snapshots_created"] == 1


def test_manual_metrics_saves(client: TestClient, db_session: Session) -> None:
    _acc, project, pub, token = _seed(db_session, "mia-man")
    r = client.post(
        f"/metrics/publications/{pub.id}/manual",
        json={"views": 2000, "reach": 1500, "likes": 100, "impressions": 1800, "clicks": 40},
        headers=_h(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "manual"
    assert body["units_charged"] == 0
    assert body["er_percent"] is not None


def test_dashboard_returns_summary(client: TestClient, db_session: Session) -> None:
    _acc, project, _pub, token = _seed(db_session, "mia-dash")
    client.post(
        f"/metrics/projects/{project.id}/run",
        json={"source": "demo", "idempotency_key": "d"},
        headers=_h(token),
    )
    r = client.get(f"/metrics/projects/{project.id}/dashboard", headers=_h(token))
    assert r.status_code == 200
    assert r.json()["with_metrics_count"] == 1


def test_user_cannot_access_other_project(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, _pa, _ta = _seed(db_session, "mia-o-a")
    _a2, _pb, _pub_b, token_b = _seed(db_session, "mia-o-b")
    r = client.post(
        f"/metrics/projects/{proj_a.id}/preview", json={"source": "demo"}, headers=_h(token_b)
    )
    assert r.status_code == 404


def test_user_cannot_manual_other_publication(client: TestClient, db_session: Session) -> None:
    _a1, _proj_a, pub_a, _ta = _seed(db_session, "mia-m-a")
    _a2, _pb, _pub_b, token_b = _seed(db_session, "mia-m-b")
    r = client.post(
        f"/metrics/publications/{pub_a.id}/manual", json={"views": 1}, headers=_h(token_b)
    )
    assert r.status_code == 404


def test_no_raw_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    _acc, project, pub, token = _seed(db_session, "mia-sec")
    # Подключим VK с секретом — он не должен утечь в ответы метрик.
    from app.services.platform_connection_service import PlatformConnectionService

    PlatformConnectionService().upsert_connection(
        db_session, project.id, "vk", {"api_key": _VK_SECRET, "external_id": "-1"}
    )
    db_session.commit()
    client.post(
        f"/metrics/projects/{project.id}/run",
        json={"source": "demo", "idempotency_key": "s"},
        headers=_h(token),
    )
    for path in (
        f"/metrics/projects/{project.id}/dashboard",
        f"/metrics/projects/{project.id}/imports",
        f"/metrics/projects/{project.id}/preview",
    ):
        if path.endswith("preview"):
            resp = client.post(
                path, json={"source": "api", "platform_key": "vk"}, headers=_h(token)
            )
        else:
            resp = client.get(path, headers=_h(token))
        assert _VK_SECRET not in resp.text


def test_api_source_disabled_skipped(client: TestClient, db_session: Session) -> None:
    _acc, project, _pub, token = _seed(db_session, "mia-api")
    r = client.post(
        f"/metrics/projects/{project.id}/run",
        json={"source": "api", "platform_key": "vk", "idempotency_key": "api"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "skipped"
