"""Тесты REST API collaborative review курирования (v0.4.9, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    media_curation_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import media_asset_repository as media_repo
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_curation_service import MediaCurationService
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:reviewSECRETtelegramTOKENxyz01234"


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
    _media(db, project.id, f"{slug}-a")
    MediaCurationService().generate_curation_tasks(db, project.id, "telegram", dry_run=False)
    tasks = media_curation_repository.list_tasks_for_project(db, project.id)
    return account, project, user, tasks, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def _retag_task_id(tasks) -> int:  # noqa: ANN001
    return next(t.id for t in tasks if t.task_type in ("retag_suggestion", "missing_tags"))


def test_list_and_dashboard(client: TestClient, db_session: Session) -> None:
    _a, project, _u, _tasks, token = _seed(db_session, "rva-list")
    lst = client.get(f"/media-curation-review/projects/{project.id}", headers=_h(token))
    assert lst.status_code == 200 and len(lst.json()) >= 1
    d = client.get(f"/media-curation-review/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200 and d.json()["proposed"] >= 1


def test_detail_and_comments(client: TestClient, db_session: Session) -> None:
    _a, project, _u, tasks, token = _seed(db_session, "rva-detail")
    tid = _retag_task_id(tasks)
    det = client.get(f"/media-curation-review/tasks/{tid}", headers=_h(token))
    assert det.status_code == 200 and "timeline" in det.json()
    add = client.post(
        f"/media-curation-review/tasks/{tid}/comments",
        json={"comment_text": "Проверить теги"},
        headers=_h(token),
    )
    assert add.status_code == 200
    cs = client.get(f"/media-curation-review/tasks/{tid}/comments", headers=_h(token))
    assert cs.status_code == 200 and any(c["comment_text"] == "Проверить теги" for c in cs.json())


def test_assign_start_approve(client: TestClient, db_session: Session) -> None:
    _a, project, user, tasks, token = _seed(db_session, "rva-flow")
    tid = _retag_task_id(tasks)
    assert (
        client.post(
            f"/media-curation-review/tasks/{tid}/assign",
            json={"assignee_user_id": user.id, "priority": "high"},
            headers=_h(token),
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/media-curation-review/tasks/{tid}/start-review", json={}, headers=_h(token)
        ).status_code
        == 200
    )
    ap = client.post(
        f"/media-curation-review/tasks/{tid}/approve", json={"comment": "ок"}, headers=_h(token)
    )
    assert ap.status_code == 200 and ap.json()["review_status"] == "approved"


def test_apply_requires_approval_then_applies(client: TestClient, db_session: Session) -> None:
    _a, project, user, tasks, token = _seed(db_session, "rva-apply")
    tid = _retag_task_id(tasks)
    blocked = client.post(
        f"/media-curation-review/tasks/{tid}/apply",
        json={"action": "approve_tags"},
        headers=_h(token),
    )
    assert blocked.status_code == 200 and blocked.json()["outcome"] == "requires_approval"
    client.post(f"/media-curation-review/tasks/{tid}/approve", json={}, headers=_h(token))
    applied = client.post(
        f"/media-curation-review/tasks/{tid}/apply",
        json={"action": "approve_tags"},
        headers=_h(token),
    )
    assert applied.status_code == 200 and applied.json()["outcome"] == "applied"


def test_reject_and_ignore(client: TestClient, db_session: Session) -> None:
    _a, project, _u, tasks, token = _seed(db_session, "rva-rej")
    tid = _retag_task_id(tasks)
    rj = client.post(f"/media-curation-review/tasks/{tid}/reject", json={}, headers=_h(token))
    assert rj.status_code == 200 and rj.json()["outcome"] == "rejected"


def test_tenant_isolation(client: TestClient, db_session: Session) -> None:
    _a1, p1, _u1, tasks1, _t1 = _seed(db_session, "rva-iso1")
    _a2, _p2, _u2, _tasks2, t2 = _seed(db_session, "rva-iso2")
    assert client.get(f"/media-curation-review/projects/{p1.id}", headers=_h(t2)).status_code == 404
    tid1 = _retag_task_id(tasks1)
    assert client.get(f"/media-curation-review/tasks/{tid1}", headers=_h(t2)).status_code == 404
    assert (
        client.post(
            f"/media-curation-review/tasks/{tid1}/approve", json={}, headers=_h(t2)
        ).status_code
        == 404
    )


def test_no_delete_endpoint(client: TestClient, db_session: Session) -> None:
    _a, project, _u, tasks, token = _seed(db_session, "rva-nodel")
    tid = _retag_task_id(tasks)
    assert client.delete(f"/media-curation-review/tasks/{tid}", headers=_h(token)).status_code in (
        404,
        405,
    )


def test_no_secrets_or_paths_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, _u, tasks, token = _seed(db_session, "rva-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    tid = _retag_task_id(tasks)
    client.post(
        f"/media-curation-review/tasks/{tid}/comments",
        json={"comment_text": f"secret {_SECRET_TOKEN} disk:/private/x.jpg"},
        headers=_h(token),
    )
    bodies = [
        client.get(f"/media-curation-review/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/media-curation-review/tasks/{tid}", headers=_h(token)).text,
        client.get(f"/media-curation-review/tasks/{tid}/comments", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
        assert "disk:/" not in body
