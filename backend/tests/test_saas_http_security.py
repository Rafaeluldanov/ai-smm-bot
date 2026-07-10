"""HTTP-тесты tenant-изоляции (v0.3.1): чужие ресурсы недоступны аутентифицированному.

Двухуровневая модель: аутентифицированный пользователь строго изолирован; анонимный
запрос в local допускается (back-compat), в production — 401. Секреты не раскрываются.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.config import Settings, get_settings
from app.core.security import make_dev_token
from app.main import app
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate


def _user(db: Session, email: str):  # noqa: ANN202 - тестовый помощник
    return user_repository.create_user(db, email=email, password_hash="x")


def _account_with_project(db: Session, owner, name: str, slug: str):  # noqa: ANN001,ANN202
    account = account_repository.create_account(db, name=name, slug=slug, owner_user_id=owner.id)
    account_repository.create_membership(db, account.id, owner.id, role="owner")
    project = project_repository.create_project(db, ProjectCreate(name=name, slug=slug + "-proj"))
    project.account_id = account.id
    db.commit()
    db.refresh(project)
    return account, project


@pytest.fixture
def tenants(db_session: Session):  # noqa: ANN201
    """Два независимых tenant'а: (user, account, project, token) для A и B."""
    ua = _user(db_session, "a@example.com")
    ub = _user(db_session, "b@example.com")
    acc_a, proj_a = _account_with_project(db_session, ua, "AccA", "acc-a")
    acc_b, proj_b = _account_with_project(db_session, ub, "AccB", "acc-b")
    return {
        "a": {"user": ua, "account": acc_a, "project": proj_a, "token": make_dev_token(ua.id)},
        "b": {"user": ub, "account": acc_b, "project": proj_b, "token": make_dev_token(ub.id)},
    }


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_own_account_projects_ok(client: TestClient, tenants) -> None:  # noqa: ANN001
    a = tenants["a"]
    r = client.get(f"/saas/accounts/{a['account'].id}/projects", headers=_h(a["token"]))
    assert r.status_code == 200


def test_cannot_open_other_account_projects(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.get(f"/saas/accounts/{b['account'].id}/projects", headers=_h(a["token"]))
    assert r.status_code == 404


def test_own_dashboard_ok(client: TestClient, tenants) -> None:  # noqa: ANN001
    a = tenants["a"]
    r = client.get(f"/saas/projects/{a['project'].id}/dashboard", headers=_h(a["token"]))
    assert r.status_code == 200


def test_cannot_open_other_dashboard(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.get(f"/saas/projects/{b['project'].id}/dashboard", headers=_h(a["token"]))
    assert r.status_code == 404


def test_cannot_open_other_billing_balance(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.get(f"/billing/account/{b['account'].id}/balance", headers=_h(a["token"]))
    assert r.status_code == 404


def test_cannot_create_invoice_for_other_account(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.post(
        f"/billing/account/{b['account'].id}/invoices",
        headers=_h(a["token"]),
        json={"amount_units": 100},
    )
    assert r.status_code == 404


def test_cannot_run_analytics_for_other_account(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.post(
        f"/analytics/accounts/{b['account'].id}/run",
        headers=_h(a["token"]),
        json={"project_id": b["project"].id, "depth": "light"},
    )
    assert r.status_code == 404


def test_cannot_read_other_audit(client: TestClient, tenants) -> None:  # noqa: ANN001
    a, b = tenants["a"], tenants["b"]
    r = client.get(f"/audit/account/{b['account'].id}", headers=_h(a["token"]))
    assert r.status_code == 404


def test_anonymous_allowed_in_local(client: TestClient, tenants) -> None:  # noqa: ANN001
    # local back-compat: анонимный запрос не блокируется (существующие тесты/дев).
    a = tenants["a"]
    r = client.get(f"/saas/accounts/{a['account'].id}/projects")
    assert r.status_code == 200


def _prod_client(session_factory) -> Iterator[TestClient]:  # noqa: ANN001
    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, app_env="production")
    try:
        with TestClient(app) as tc:
            yield tc
    finally:
        app.dependency_overrides.clear()


def test_anonymous_blocked_in_production(session_factory, db_session, tenants) -> None:  # noqa: ANN001
    a = tenants["a"]
    for tc in _prod_client(session_factory):
        r = tc.get(f"/saas/accounts/{a['account'].id}/projects")
        assert r.status_code == 401


def test_legacy_project_hidden_in_production(session_factory, db_session, tenants) -> None:  # noqa: ANN001
    a = tenants["a"]
    legacy = project_repository.create_project(
        db_session, ProjectCreate(name="Legacy", slug="legacy")
    )
    db_session.commit()
    for tc in _prod_client(session_factory):
        # Аутентифицированный владелец, но legacy-проект скрыт в production.
        r = tc.get(f"/saas/projects/{legacy.id}/dashboard", headers=_h(a["token"]))
        assert r.status_code == 404
