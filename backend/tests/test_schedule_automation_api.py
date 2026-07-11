"""Тесты API движка автоматизации расписаний (offline, tenant-изоляция)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_MONDAY = "2026-07-13"


def _seed(db: Session, slug: str, connect: bool = True):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    config = crm.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug)
    )
    category = crm.create_category(
        db, CrmPromotionCategoryCreate(project_id=project.id, config_id=config.id, title="C")
    )
    crm.create_plan(
        db,
        CrmPublishingPlanCreate(
            project_id=project.id,
            config_id=config.id,
            category_id=category.id,
            weekdays=[0],
            publish_times=["12:00"],
            platforms=["telegram"],
        ),
    )
    if connect:
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@x"}
        )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_tasks_requires_project_access(client: TestClient, db_session: Session) -> None:
    account, project, token = _seed(db_session, "teeon")
    r = client.get(f"/schedule/projects/{project.id}/tasks", headers=_h(token))
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_user_cannot_access_other_project(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, _ta = _seed(db_session, "acc-a")
    _a2, _pb, token_b = _seed(db_session, "acc-b")
    # Пользователь B под своим токеном не видит проект A → 404.
    r = client.get(f"/schedule/projects/{proj_a.id}/tasks", headers=_h(token_b))
    assert r.status_code == 404


def test_preview_due_returns_due(client: TestClient, db_session: Session) -> None:
    account, project, token = _seed(db_session, "teeon")
    r = client.post(
        f"/schedule/projects/{project.id}/preview-due",
        json={"account_id": account.id, "date": _MONDAY},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["due_count"] == 1


def test_run_due_creates_drafts_only(client: TestClient, db_session: Session) -> None:
    account, project, token = _seed(db_session, "teeon")
    r = client.post(
        f"/schedule/projects/{project.id}/run-due",
        json={"account_id": account.id, "date": _MONDAY},
        headers=_h(token),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["created"] == 1
    assert body["live_calls"] is False
    runs = client.get(f"/schedule/projects/{project.id}/runs", headers=_h(token)).json()
    assert runs[0]["status"] == "draft_created"


def test_no_raw_token_in_responses(client: TestClient, db_session: Session) -> None:
    account, project, token = _seed(db_session, "teeon")
    client.post(
        f"/schedule/projects/{project.id}/run-due",
        json={"account_id": account.id, "date": _MONDAY},
        headers=_h(token),
    )
    for path in ("/tasks", "/runs"):
        assert (
            _TOKEN
            not in client.get(f"/schedule/projects/{project.id}{path}", headers=_h(token)).text
        )


def test_wrong_account_id_rejected(client: TestClient, db_session: Session) -> None:
    account, project, token = _seed(db_session, "teeon")
    r = client.post(
        f"/schedule/projects/{project.id}/preview-due",
        json={"account_id": account.id + 999, "date": _MONDAY},
        headers=_h(token),
    )
    assert r.status_code == 400


@pytest.mark.parametrize("path", ["tasks", "runs"])
def test_endpoints_no_publish_due(client: TestClient, db_session: Session, path: str) -> None:
    account, project, token = _seed(db_session, "teeon")
    text = client.get(f"/schedule/projects/{project.id}/{path}", headers=_h(token)).text
    assert "publish-due" not in text.lower()
