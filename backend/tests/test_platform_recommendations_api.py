"""Тесты read-only API базы SMM-рекомендаций Botfleet (v1.0.1).

Инварианты: global-роуты 200; per-platform + алиасы; неизвестная платформа → 404; project-scoped
роут с tenant-гардом (владелец 200, чужой аккаунт 404); битый ресурс → контролируемый 500 без
stack trace/файловых путей в ответе.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _project(db: Session, account_id: int, slug: str) -> int:
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account_id
    db.commit()
    return project.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def test_list_platforms(client: TestClient) -> None:
    r = client.get("/platform-recommendations")
    assert r.status_code == 200
    body = r.json()
    assert len(body["platforms"]) == 10
    assert {p["slug"] for p in body["platforms"]} >= {"telegram", "instagram", "vk"}


def test_universal(client: TestClient) -> None:
    r = client.get("/platform-recommendations/universal")
    assert r.status_code == 200
    body = r.json()
    assert len(body["universal_principles"]) == 8
    assert len(body["pre_publish_checklist"]) == 8


@pytest.mark.parametrize(
    "slug",
    ["instagram", "telegram", "vk", "youtube", "rutube", "dzen", "ok", "website", "2gis", "email"],
)
def test_each_platform(client: TestClient, slug: str) -> None:
    r = client.get(f"/platform-recommendations/{slug}")
    assert r.status_code == 200
    assert r.json()["platform"] == slug


def test_alias_routes(client: TestClient) -> None:
    assert client.get("/platform-recommendations/odnoklassniki").json()["platform"] == "ok"
    assert client.get("/platform-recommendations/two_gis").json()["platform"] == "2gis"
    assert client.get("/platform-recommendations/zen").json()["platform"] == "dzen"


def test_unknown_platform_404(client: TestClient) -> None:
    assert client.get("/platform-recommendations/facebook").status_code == 404


def test_project_scoped_owner_ok(client: TestClient, db_session: Session) -> None:
    aid, uid = _account(db_session, "prec1")
    pid = _project(db_session, aid, "prec1proj")
    r = client.get(f"/projects/{pid}/platforms/telegram/recommendations", headers=_h(uid))
    assert r.status_code == 200
    assert r.json()["platform"] == "telegram"


def test_project_scoped_cross_account_404(client: TestClient, db_session: Session) -> None:
    aid_a, _uid_a = _account(db_session, "prec2a")
    _aid_b, uid_b = _account(db_session, "prec2b")
    pid = _project(db_session, aid_a, "prec2proj")
    r = client.get(f"/projects/{pid}/platforms/telegram/recommendations", headers=_h(uid_b))
    assert r.status_code == 404


def test_project_scoped_unknown_platform_404(client: TestClient, db_session: Session) -> None:
    aid, uid = _account(db_session, "prec3")
    pid = _project(db_session, aid, "prec3proj")
    r = client.get(f"/projects/{pid}/platforms/facebook/recommendations", headers=_h(uid))
    assert r.status_code == 404


def test_broken_resource_controlled_500(client: TestClient, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Битый ресурс → 500 без stack trace/файловых путей в теле ответа."""
    from app.services.platform_recommendations_service import (
        PlatformRecommendationsError,
        PlatformRecommendationsService,
    )

    def _boom(self: PlatformRecommendationsService) -> dict:
        raise PlatformRecommendationsError("resource /secret/path.json broken")

    monkeypatch.setattr(PlatformRecommendationsService, "list_platforms", _boom)
    r = client.get("/platform-recommendations")
    assert r.status_code == 500
    body = r.text
    assert "Traceback" not in body
    assert "/secret/path.json" not in body
    assert ".json" not in body
