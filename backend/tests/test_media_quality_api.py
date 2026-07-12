"""Тесты REST API оценки качества медиа (v0.4.6, offline, tenant-изоляция)."""

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

_SECRET_TOKEN = "123456789:mqSECRETtelegramTOKENxyz"


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    ids = []
    for i in range(3):
        asset = media_repo.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project.id,
                file_name="img.jpg",
                yandex_disk_path=f"disk:/{slug}-{i}.jpg",
                source_type="internal",
                license_type=None,
                status="approved",
                tags={"products": ["мерч"], "technologies": ["dtf"]},
            ),
        )
        ids.append(asset.id)
    db.commit()
    return account, project, ids, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_score_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "mqa-prev")
    r = client.post(
        f"/media-quality/projects/{project.id}/score-preview",
        json={"platform_key": "telegram", "limit": 10},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert client.get(f"/media-quality/projects/{project.id}", headers=_h(token)).json() == []


def test_score_writes_snapshots(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "mqa-score")
    r = client.post(
        f"/media-quality/projects/{project.id}/score",
        json={"platform_key": "telegram", "limit": 10},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["snapshots_created"] == 3
    lst = client.get(f"/media-quality/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) == 3


def test_single_asset_score(client: TestClient, db_session: Session) -> None:
    _a, project, ids, token = _seed(db_session, "mqa-one")
    pv = client.post(
        f"/media-quality/projects/{project.id}/media-assets/{ids[0]}/score-preview",
        json={"platform_key": "telegram"},
        headers=_h(token),
    )
    assert pv.status_code == 200
    assert pv.json()["writes"] is False
    sc = client.post(
        f"/media-quality/projects/{project.id}/media-assets/{ids[0]}/score",
        json={"platform_key": "telegram"},
        headers=_h(token),
    )
    assert sc.status_code == 200
    sid = sc.json()["id"]
    assert client.get(f"/media-quality/{sid}", headers=_h(token)).status_code == 200


def test_dashboard(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "mqa-dash")
    client.post(
        f"/media-quality/projects/{project.id}/score",
        json={"platform_key": "telegram", "limit": 10},
        headers=_h(token),
    )
    d = client.get(f"/media-quality/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200
    assert d.json()["total_media"] == 3
    assert d.json()["scored"] >= 1


def test_tenant_isolation_project(client: TestClient, db_session: Session) -> None:
    _a1, p1, _i1, _t1 = _seed(db_session, "mqa-iso1")
    _a2, _p2, _i2, t2 = _seed(db_session, "mqa-iso2")
    assert client.get(f"/media-quality/projects/{p1.id}", headers=_h(t2)).status_code == 404
    assert (
        client.post(
            f"/media-quality/projects/{p1.id}/score-preview",
            json={"platform_key": "telegram"},
            headers=_h(t2),
        ).status_code
        == 404
    )


def test_tenant_isolation_snapshot(client: TestClient, db_session: Session) -> None:
    _a1, p1, _i1, t1 = _seed(db_session, "mqa-isos1")
    _a2, _p2, _i2, t2 = _seed(db_session, "mqa-isos2")
    sid = client.post(
        f"/media-quality/projects/{p1.id}/score",
        json={"platform_key": "telegram", "limit": 1},
        headers=_h(t1),
    ).json()["results"][0]["id"]
    assert client.get(f"/media-quality/{sid}", headers=_h(t2)).status_code == 404


def test_no_secrets_or_paths_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "mqa-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    client.post(
        f"/media-quality/projects/{project.id}/score",
        json={"platform_key": "telegram", "limit": 10},
        headers=_h(token),
    )
    bodies = [
        client.get(f"/media-quality/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/media-quality/projects/{project.id}/dashboard", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
        assert "disk:/" not in body
