"""Тесты API A/B-тестирования и оптимизации (v0.4.2, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    content_experiment_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_recommendations_requires_project_access(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-rec")
    r = client.get(f"/experiments/projects/{project.id}/recommendations", headers=_h(token))
    assert r.status_code == 200
    assert "recommendations" in r.json()


def test_preview_topic_no_writes(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-prev")
    r = client.post(
        f"/experiments/projects/{project.id}/preview-topic",
        json={"platform_key": "telegram", "topic": "Футболки", "variant_count": 2},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["writes"] is False
    assert content_experiment_repository.list_experiments_for_project(db_session, project.id) == []


def test_create_from_topic(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-create")
    r = client.post(
        f"/experiments/projects/{project.id}/create-from-topic",
        json={"platform_key": "vk", "topic": "Худи", "variant_count": 2, "idempotency_key": "a"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["outcome"] == "created"
    lst = client.get(f"/experiments/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) == 1


def test_choose_winner(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-win")
    created = client.post(
        f"/experiments/projects/{project.id}/create-from-topic",
        json={"topic": "Сумки", "variant_count": 2},
        headers=_h(token),
    ).json()
    eid = created["experiment"]["id"]
    vid = created["variants"][0]["id"]
    r = client.post(
        f"/experiments/{eid}/choose-winner",
        json={"method": "manual", "variant_id": vid},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["winner"]["variant_key"] == created["variants"][0]["variant_key"]


def test_variant_feedback_and_metrics(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-fb")
    created = client.post(
        f"/experiments/projects/{project.id}/create-from-topic",
        json={"topic": "Кружки", "variant_count": 2},
        headers=_h(token),
    ).json()
    vid = created["variants"][0]["id"]
    assert (
        client.post(
            f"/experiments/variants/{vid}/feedback",
            json={"event_type": "approved"},
            headers=_h(token),
        ).status_code
        == 200
    )
    r = client.post(
        f"/experiments/variants/{vid}/metrics",
        json={"reach": 1000, "likes": 50, "impressions": 1200, "clicks": 20},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["er_percent"] is not None


def test_user_cannot_access_other_project(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, _ta = _seed(db_session, "ex-o-a")
    _a2, _pb, token_b = _seed(db_session, "ex-o-b")
    r = client.get(f"/experiments/projects/{proj_a.id}", headers=_h(token_b))
    assert r.status_code == 404


def test_user_cannot_access_other_experiment(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, token_a = _seed(db_session, "ex-e-a")
    _a2, _pb, token_b = _seed(db_session, "ex-e-b")
    created = client.post(
        f"/experiments/projects/{proj_a.id}/create-from-topic",
        json={"topic": "T"},
        headers=_h(token_a),
    ).json()
    eid = created["experiment"]["id"]
    assert client.get(f"/experiments/{eid}", headers=_h(token_b)).status_code == 404


def test_no_raw_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "ex-sec")
    from app.services.platform_connection_service import PlatformConnectionService

    secret = "vk-secret-token-1234567890"
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "vk", {"api_key": secret, "external_id": "-1"}
    )
    db_session.commit()
    created = client.post(
        f"/experiments/projects/{project.id}/create-from-topic",
        json={"platform_key": "vk", "topic": "Футболки"},
        headers=_h(token),
    )
    assert secret not in created.text
