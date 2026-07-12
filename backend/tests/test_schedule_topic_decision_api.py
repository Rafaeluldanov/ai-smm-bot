"""Тесты REST API автовыбора темы (v0.4.4, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо"]
_SECRET_TOKEN = "123456789:tdSECRETtelegramTOKENxyz"


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    cat = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    learn = ClientLearningService()
    for t in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=t,
                status="needs_review",
                vk_text="T",
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return account, project, cat, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, cat, token = _seed(db_session, "tda-prev")
    r = client.post(
        f"/topic-decisions/projects/{project.id}/preview",
        json={"platform_key": "telegram", "category_id": cat.id},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["writes"] is False
    assert client.get(f"/topic-decisions/projects/{project.id}", headers=_h(token)).json() == []


def test_create_then_list_get(client: TestClient, db_session: Session) -> None:
    _a, project, cat, token = _seed(db_session, "tda-create")
    c = client.post(
        f"/topic-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram", "category_id": cat.id},
        headers=_h(token),
    )
    assert c.status_code == 200
    did = c.json()["id"]
    lst = client.get(f"/topic-decisions/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) == 1
    assert client.get(f"/topic-decisions/{did}", headers=_h(token)).status_code == 200


def test_dashboard_and_apply_dry(client: TestClient, db_session: Session) -> None:
    _a, project, cat, token = _seed(db_session, "tda-dash")
    did = client.post(
        f"/topic-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram", "category_id": cat.id},
        headers=_h(token),
    ).json()["id"]
    d = client.get(f"/topic-decisions/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200
    assert d.json()["total"] >= 1
    # apply-dry не должен ничего писать: ни постов, ни новых решений, статус решения не меняется.
    from app.models.post import Post
    from app.models.schedule_topic_decision import ScheduleTopicDecision

    posts_before = db_session.query(Post).count()
    decisions_before = db_session.query(ScheduleTopicDecision).count()
    status_before = db_session.get(ScheduleTopicDecision, did).status
    ad = client.post(f"/topic-decisions/{did}/apply-dry", json={}, headers=_h(token))
    assert ad.status_code == 200
    assert ad.json()["live"] is False
    assert ad.json()["writes"] is False
    assert db_session.query(Post).count() == posts_before
    assert db_session.query(ScheduleTopicDecision).count() == decisions_before
    assert db_session.get(ScheduleTopicDecision, did).status == status_before


def test_tenant_isolation_project(client: TestClient, db_session: Session) -> None:
    _a1, p1, _c1, _t1 = _seed(db_session, "tda-iso1")
    _a2, _p2, _c2, t2 = _seed(db_session, "tda-iso2")
    assert client.get(f"/topic-decisions/projects/{p1.id}", headers=_h(t2)).status_code == 404


def test_tenant_isolation_decision(client: TestClient, db_session: Session) -> None:
    _a1, p1, c1, t1 = _seed(db_session, "tda-isod1")
    _a2, _p2, _c2, t2 = _seed(db_session, "tda-isod2")
    did = client.post(
        f"/topic-decisions/projects/{p1.id}/create",
        json={"platform_key": "telegram", "category_id": c1.id},
        headers=_h(t1),
    ).json()["id"]
    assert client.get(f"/topic-decisions/{did}", headers=_h(t2)).status_code == 404
    assert (
        client.post(f"/topic-decisions/{did}/apply-dry", json={}, headers=_h(t2)).status_code == 404
    )


def test_shared_idempotency_key_no_cross_tenant_leak(
    client: TestClient, db_session: Session
) -> None:
    _a1, p1, c1, t1 = _seed(db_session, "tda-idem1")
    _a2, p2, c2, t2 = _seed(db_session, "tda-idem2")
    # Оба тенанта используют ОДИН и тот же клиентский idempotency_key.
    r1 = client.post(
        f"/topic-decisions/projects/{p1.id}/create",
        json={"platform_key": "telegram", "category_id": c1.id, "idempotency_key": "shared"},
        headers=_h(t1),
    ).json()
    r2 = client.post(
        f"/topic-decisions/projects/{p2.id}/create",
        json={"platform_key": "telegram", "category_id": c2.id, "idempotency_key": "shared"},
        headers=_h(t2),
    ).json()
    # Тенант B получает СВОЁ решение (свой проект), а не решение тенанта A.
    assert r1["id"] != r2["id"]
    assert r2["project_id"] == p2.id
    assert r1["project_id"] == p1.id


def test_no_secrets_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, cat, token = _seed(db_session, "tda-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    c = client.post(
        f"/topic-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram", "category_id": cat.id},
        headers=_h(token),
    )
    did = c.json()["id"]
    bodies = [
        c.text,
        client.get(f"/topic-decisions/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/topic-decisions/projects/{project.id}/dashboard", headers=_h(token)).text,
        client.get(f"/topic-decisions/{did}", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
