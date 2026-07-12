"""Тесты REST API курирования медиатеки (v0.4.8, offline, tenant-изоляция)."""

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

_SECRET_TOKEN = "123456789:curSECRETtelegramTOKENxyz"


def _media(db: Session, project_id: int, key: str) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="hoodie_dtf.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={},
        ),
    )
    db.commit()
    return asset.id


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
    ids = [_media(db, project.id, f"{slug}-{i}") for i in range(2)]
    return account, project, ids, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-prev")
    r = client.post(
        f"/media-curation/projects/{project.id}/preview", json={"limit": 10}, headers=_h(token)
    )
    assert r.status_code == 200 and r.json()["dry_run"] is True
    assert client.get(f"/media-curation/projects/{project.id}", headers=_h(token)).json() == []


def test_generate_and_list(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-gen")
    g = client.post(
        f"/media-curation/projects/{project.id}/generate",
        json={"dry_run": False},
        headers=_h(token),
    )
    assert g.status_code == 200 and g.json()["tasks_created"] >= 1
    lst = client.get(f"/media-curation/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) >= 1


def test_apply_reject_ignore(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-apply")
    client.post(
        f"/media-curation/projects/{project.id}/generate",
        json={"dry_run": False},
        headers=_h(token),
    )
    tasks = client.get(f"/media-curation/projects/{project.id}", headers=_h(token)).json()
    tid = tasks[0]["id"]
    ap = client.post(
        f"/media-curation/tasks/{tid}/apply", json={"action": "approve_tags"}, headers=_h(token)
    )
    assert ap.status_code == 200
    if len(tasks) > 1:
        rj = client.post(
            f"/media-curation/tasks/{tasks[1]['id']}/reject", json={}, headers=_h(token)
        )
        assert rj.status_code == 200 and rj.json()["outcome"] == "rejected"


def test_restore_media(client: TestClient, db_session: Session) -> None:
    _a, project, ids, token = _seed(db_session, "cua-restore")
    from app.repositories import media_curation_repository

    media_curation_repository.set_media_visibility(db_session, ids[0], "hidden_manual")
    r = client.post(
        f"/media-curation/projects/{project.id}/media-assets/{ids[0]}/restore", headers=_h(token)
    )
    assert r.status_code == 200 and r.json()["selection_visibility"] == "selectable"


def test_dashboard(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-dash")
    d = client.get(f"/media-curation/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200
    assert "selectable_media_count" in d.json()


def test_tenant_isolation(client: TestClient, db_session: Session) -> None:
    _a1, p1, _i1, _t1 = _seed(db_session, "cua-iso1")
    _a2, _p2, _i2, t2 = _seed(db_session, "cua-iso2")
    assert client.get(f"/media-curation/projects/{p1.id}", headers=_h(t2)).status_code == 404
    assert (
        client.post(
            f"/media-curation/projects/{p1.id}/preview", json={}, headers=_h(t2)
        ).status_code
        == 404
    )


def test_no_delete_endpoint(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-nodel")
    client.post(
        f"/media-curation/projects/{project.id}/generate",
        json={"dry_run": False},
        headers=_h(token),
    )
    tid = client.get(f"/media-curation/projects/{project.id}", headers=_h(token)).json()[0]["id"]
    # DELETE на задачу не поддерживается (нет удаления медиа/файлов).
    assert client.delete(f"/media-curation/tasks/{tid}", headers=_h(token)).status_code in (
        404,
        405,
    )


def test_no_secrets_or_paths_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "cua-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    client.post(
        f"/media-curation/projects/{project.id}/generate",
        json={"dry_run": False},
        headers=_h(token),
    )
    bodies = [
        client.get(f"/media-curation/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/media-curation/projects/{project.id}/dashboard", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
        assert "disk:/" not in body
