"""Тесты REST API автовыбора медиа (v0.4.5, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:mdSECRETtelegramTOKENxyz"


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
    for i in range(3):
        media_repo.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project.id,
                file_name="img.jpg",
                yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                source_type="internal",
                license_type=None,
                status="approved",
                tags={"products": ["мерч"], "categories": ["мерч"]},
            ),
        )
    db.commit()
    return account, project, cat, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, _cat, token = _seed(db_session, "mda-prev")
    r = client.post(
        f"/media-decisions/projects/{project.id}/preview",
        json={"platform_key": "telegram"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["writes"] is False
    assert client.get(f"/media-decisions/projects/{project.id}", headers=_h(token)).json() == []


def test_create_then_list_get(client: TestClient, db_session: Session) -> None:
    _a, project, _cat, token = _seed(db_session, "mda-create")
    c = client.post(
        f"/media-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram"},
        headers=_h(token),
    )
    assert c.status_code == 200
    did = c.json()["id"]
    lst = client.get(f"/media-decisions/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) == 1
    assert client.get(f"/media-decisions/{did}", headers=_h(token)).status_code == 200


def test_dashboard_and_apply_dry(client: TestClient, db_session: Session) -> None:
    _a, project, _cat, token = _seed(db_session, "mda-dash")
    did = client.post(
        f"/media-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram"},
        headers=_h(token),
    ).json()["id"]
    d = client.get(f"/media-decisions/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200
    assert d.json()["total"] >= 1
    # apply-dry не должен ничего писать: ни постов, ни новых решений, статус не меняется.
    from app.models.post import Post
    from app.models.schedule_media_decision import ScheduleMediaDecision

    posts_before = db_session.query(Post).count()
    decisions_before = db_session.query(ScheduleMediaDecision).count()
    status_before = db_session.get(ScheduleMediaDecision, did).status
    ad = client.post(f"/media-decisions/{did}/apply-dry", json={}, headers=_h(token))
    assert ad.status_code == 200
    assert ad.json()["live"] is False
    assert ad.json()["writes"] is False
    # generation_notes preview содержит id решения и стратегию.
    notes = ad.json()["draft_payload"]["generation_notes"]
    assert notes["schedule_media_decision_id"] == did
    assert db_session.query(Post).count() == posts_before
    assert db_session.query(ScheduleMediaDecision).count() == decisions_before
    assert db_session.get(ScheduleMediaDecision, did).status == status_before


def test_tenant_isolation_project(client: TestClient, db_session: Session) -> None:
    _a1, p1, _c1, _t1 = _seed(db_session, "mda-iso1")
    _a2, _p2, _c2, t2 = _seed(db_session, "mda-iso2")
    assert client.get(f"/media-decisions/projects/{p1.id}", headers=_h(t2)).status_code == 404


def test_tenant_isolation_decision(client: TestClient, db_session: Session) -> None:
    _a1, p1, _c1, t1 = _seed(db_session, "mda-isod1")
    _a2, _p2, _c2, t2 = _seed(db_session, "mda-isod2")
    did = client.post(
        f"/media-decisions/projects/{p1.id}/create",
        json={"platform_key": "telegram"},
        headers=_h(t1),
    ).json()["id"]
    assert client.get(f"/media-decisions/{did}", headers=_h(t2)).status_code == 404
    assert (
        client.post(f"/media-decisions/{did}/apply-dry", json={}, headers=_h(t2)).status_code == 404
    )


def test_shared_idempotency_key_no_cross_tenant_leak(
    client: TestClient, db_session: Session
) -> None:
    _a1, p1, _c1, t1 = _seed(db_session, "mda-idem1")
    _a2, p2, _c2, t2 = _seed(db_session, "mda-idem2")
    r1 = client.post(
        f"/media-decisions/projects/{p1.id}/create",
        json={"platform_key": "telegram", "idempotency_key": "shared"},
        headers=_h(t1),
    ).json()
    r2 = client.post(
        f"/media-decisions/projects/{p2.id}/create",
        json={"platform_key": "telegram", "idempotency_key": "shared"},
        headers=_h(t2),
    ).json()
    assert r1["id"] != r2["id"]
    assert r2["project_id"] == p2.id
    assert r1["project_id"] == p1.id


def test_no_secrets_or_paths_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, _cat, token = _seed(db_session, "mda-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    c = client.post(
        f"/media-decisions/projects/{project.id}/create",
        json={"platform_key": "telegram"},
        headers=_h(token),
    )
    did = c.json()["id"]
    bodies = [
        c.text,
        client.get(f"/media-decisions/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/media-decisions/projects/{project.id}/dashboard", headers=_h(token)).text,
        client.get(f"/media-decisions/{did}", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
        assert "disk:/" not in body
