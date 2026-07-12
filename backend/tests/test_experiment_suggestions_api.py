"""Тесты REST API предложений экспериментов (v0.4.3, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    content_experiment_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz-SECRET"

_TOPICS = [
    "Футболки с логотипом",
    "Худи осень",
    "Акция мерч",
    "Кружки промо",
    "Стикеры бренд",
    "Кепки лето",
]


def _seed(db: Session, slug: str, topup: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
    learn = ClientLearningService()
    for title in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=title,
                status="needs_review",
                vk_text="Текст про " + title,
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return account, project, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-prev")
    r = client.post(
        f"/experiment-suggestions/projects/{project.id}/preview", json={}, headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["writes"] is False
    lst = client.get(f"/experiment-suggestions/projects/{project.id}", headers=_h(token))
    assert lst.json() == []


def test_generate_then_list(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-gen")
    gen = client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    )
    assert gen.status_code == 200
    assert gen.json()["created"] > 0
    lst = client.get(f"/experiment-suggestions/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) > 0
    assert all(s["status"] == "proposed" for s in lst)


def test_accept_reject_dismiss(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-decide")
    gen = client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    ).json()
    ids = [s["id"] for s in gen["suggestions"]]
    a = client.post(f"/experiment-suggestions/{ids[0]}/accept", json={}, headers=_h(token))
    assert a.json()["status"] == "accepted"
    r = client.post(
        f"/experiment-suggestions/{ids[1]}/reject", json={"reason": "нет"}, headers=_h(token)
    )
    assert r.json()["status"] == "rejected"
    d = client.post(f"/experiment-suggestions/{ids[2]}/dismiss", json={}, headers=_h(token))
    assert d.json()["status"] == "dismissed"


def test_create_experiment_from_suggestion(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-create")
    gen = client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    ).json()
    sid = gen["suggestions"][0]["id"]
    r = client.post(f"/experiment-suggestions/{sid}/create-experiment", json={}, headers=_h(token))
    assert r.status_code == 200
    assert r.json()["experiment_id"] is not None
    # Варианты — needs_review, без live-публикации.
    variants = content_experiment_repository.list_variants_for_experiment(
        db_session, r.json()["experiment_id"]
    )
    assert variants  # иначе проверка «нет live» была бы вакуумной
    for v in variants:
        post = post_repository.get_post_by_id(db_session, v.post_id)
        assert post.status == "needs_review"
        assert post.published_at is None


def test_create_experiment_insufficient_balance_402(
    client: TestClient, db_session: Session
) -> None:
    _acc, project, token = _seed(db_session, "sa-poor", topup=0)
    gen = client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    ).json()
    sid = gen["suggestions"][0]["id"]
    r = client.post(f"/experiment-suggestions/{sid}/create-experiment", json={}, headers=_h(token))
    assert r.status_code == 402


def test_worker_preview_readonly(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-wprev")
    r = client.post(
        f"/experiment-suggestions/projects/{project.id}/worker-preview", json={}, headers=_h(token)
    )
    assert r.status_code == 200
    body = r.json()
    # По умолчанию worker выключен → enabled False, ничего не создано.
    assert body["enabled"] is False
    assert body["created"] == 0
    lst = client.get(f"/experiment-suggestions/projects/{project.id}", headers=_h(token)).json()
    assert lst == []


def test_dashboard(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-dash")
    client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    )
    r = client.get(f"/experiment-suggestions/projects/{project.id}/dashboard", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["active_count"] > 0
    assert body["worker_enabled"] is False


def test_tenant_isolation_project(client: TestClient, db_session: Session) -> None:
    _a1, p1, _t1 = _seed(db_session, "sa-iso1")
    _a2, _p2, t2 = _seed(db_session, "sa-iso2")
    # Пользователь 2 не видит проект 1.
    r = client.get(f"/experiment-suggestions/projects/{p1.id}", headers=_h(t2))
    assert r.status_code == 404


def test_tenant_isolation_suggestion(client: TestClient, db_session: Session) -> None:
    _a1, p1, t1 = _seed(db_session, "sa-isos1")
    _a2, _p2, t2 = _seed(db_session, "sa-isos2")
    gen = client.post(
        f"/experiment-suggestions/projects/{p1.id}/generate", json={}, headers=_h(t1)
    ).json()
    sid = gen["suggestions"][0]["id"]
    # Чужое предложение → 404 для пользователя 2.
    assert client.get(f"/experiment-suggestions/{sid}", headers=_h(t2)).status_code == 404
    assert (
        client.post(f"/experiment-suggestions/{sid}/accept", json={}, headers=_h(t2)).status_code
        == 404
    )


def test_no_secrets_in_api_responses(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "sa-nosec")
    # Проект с подключённой платформой, у которой ЕСТЬ секретный токен.
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    gen = client.post(
        f"/experiment-suggestions/projects/{project.id}/generate", json={}, headers=_h(token)
    )
    sid = gen.json()["suggestions"][0]["id"]
    bodies = [
        gen.text,
        client.get(f"/experiment-suggestions/projects/{project.id}", headers=_h(token)).text,
        client.get(
            f"/experiment-suggestions/projects/{project.id}/dashboard", headers=_h(token)
        ).text,
        client.get(f"/experiment-suggestions/{sid}", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
