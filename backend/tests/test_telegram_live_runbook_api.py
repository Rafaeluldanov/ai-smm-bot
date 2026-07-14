"""Тесты REST API Telegram live runbook (v0.6.3, offline).

Project access; проверка/preview/publish-test/pause; happy-path через fake-клиент; tenant isolation.
Без реальных публикаций/сети; глобальные флаги не меняются.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_telegram_live_runbook_service
from app.config import Settings
from app.core.security import make_dev_token
from app.integrations.publishing import FakePublishingClient
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import live_readiness_repository as lrr
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry
from app.services.telegram_live_rollout_service import TelegramLiveRolloutService
from app.services.telegram_live_runbook_service import TelegramLiveRunbookService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": "123456:ABCdef", "external_id": "@chan"}
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id, title="T", status="approved", telegram_text="Привет", hashtags=[]
        ),
    )
    db.commit()
    return account, project, owner


def _enable_readiness(db: Session, account_id: int, project_id: int) -> None:
    pp = lrr.get_or_create_project_profile(db, account_id, project_id)
    lrr.update_project_profile(
        db, pp, {"status": "ready", "project_live_enabled": True, "full_auto_live_enabled": True}
    )
    plat = lrr.get_or_create_platform_profile(db, account_id, project_id, "telegram")
    lrr.update_platform_profile(db, plat, {"status": "ready", "platform_live_enabled": True})
    db.commit()


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _ready_runbook_service() -> TelegramLiveRunbookService:
    settings = Settings(
        media_proxy_public_base_url="https://media.example.com",
        telegram_live_publishing_enabled=True,
        telegram_live_rollout_allow_real_send=True,
    )
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram", live_enabled=True)}
    )
    fake_pub = PostPublicationService(registry=registry, default_targets={"telegram": "@chan"})
    rollout = TelegramLiveRolloutService(publication_service=fake_pub, settings=settings)
    return TelegramLiveRunbookService(rollout_service=rollout, settings=settings)


def test_requires_project_access(client: TestClient, db_session: Session) -> None:
    _a, project, _o = _seed(db_session, "rba-auth")
    assert client.get(f"/projects/{project.id}/telegram-runbook").status_code == 401


def test_dashboard_and_check(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "rba-dash")
    r = client.get(f"/projects/{project.id}/telegram-runbook", headers=_h(owner.id))
    assert r.status_code == 200
    assert "checklist" in r.json() and "status" in r.json()
    c = client.post(f"/projects/{project.id}/telegram-runbook/check", headers=_h(owner.id))
    assert c.status_code == 200 and "ready" in c.json()


def test_preview_does_not_send(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "rba-preview")
    r = client.post(
        f"/projects/{project.id}/telegram-runbook/preview", headers=_h(owner.id), json={}
    )
    assert r.status_code == 200
    assert r.json()["live_calls"] is False
    assert r.json()["attempt"]["status"] == "preview"


def test_publish_test_blocked_without_confirmation(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "rba-noconfirm")
    _enable_readiness(db_session, _a.id, project.id)
    r = client.post(
        f"/projects/{project.id}/telegram-runbook/publish-test",
        headers=_h(owner.id),
        json={"confirmation": ""},
    )
    assert r.status_code == 200
    assert r.json()["published"] is False


def test_publish_test_happy_path(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "rba-go")
    _enable_readiness(db_session, _a.id, project.id)
    client.app.dependency_overrides[get_telegram_live_runbook_service] = _ready_runbook_service
    try:
        r = client.post(
            f"/projects/{project.id}/telegram-runbook/publish-test",
            headers=_h(owner.id),
            json={"confirmation": "ENABLE_TELEGRAM_LIVE"},
        )
        assert r.status_code == 200
        assert r.json()["published"] is True
        assert r.json()["attempt"]["status"] == "published"
    finally:
        client.app.dependency_overrides.pop(get_telegram_live_runbook_service, None)


def test_pause(client: TestClient, db_session: Session) -> None:
    _a, project, owner = _seed(db_session, "rba-pause")
    r = client.post(f"/projects/{project.id}/telegram-runbook/pause", headers=_h(owner.id))
    assert r.status_code == 200 and r.json()["status"] == "paused"


def test_cross_tenant_blocked(client: TestClient, db_session: Session) -> None:
    _a, project_a, _owner_a = _seed(db_session, "rba-ta")
    _b, _project_b, owner_b = _seed(db_session, "rba-tb")
    # Владелец B не имеет доступа к runbook проекта A.
    r = client.get(f"/projects/{project_a.id}/telegram-runbook", headers=_h(owner_b.id))
    assert r.status_code in (403, 404)
