"""Тесты безопасности AI Business OS MVP Testing (v0.9.0, offline).

NB: файл namespaced `_testing_` — `test_business_os_security.py` уже занят слоем Autonomous Business
OS (v0.7.0).

Инварианты (Part 15): DEMO-режим НЕ создаёт реальных сущностей; сценарии НЕ запускают workflow, НЕ
меняют бизнес/CRM, НЕ отправляют сообщений, НЕ создают платежей. Проверяем: DEMO isolation; нет
CRM/публикаций/workflow/платежей; billing 0; секретов нет; tenant isolation; demo_mode gate.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.models.billing import UsageEvent
from app.models.business_workflow import BusinessWorkflow
from app.models.crm_bot_smm import CrmSmmResource
from app.models.payment import PaymentInvoice
from app.models.post_publication import PostPublication
from app.repositories import account_repository, user_repository
from app.repositories import demo_testing_repository as repo
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_business_os_demo_service import (
    AIBusinessOSDemoError,
    AIBusinessOSDemoService,
)
from app.services.ai_business_os_scenario_service import AIBusinessOSScenarioService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")

# Сущности, которые demo-прогон НЕ имеет права создавать/менять (Part 15).
_FORBIDDEN_MODELS = (
    PostPublication,  # публикации/сообщения
    CrmSmmResource,  # CRM
    BusinessWorkflow,  # workflow-исполнение
    PaymentInvoice,  # платежи
    UsageEvent,  # списания billing
)
_WORKSPACE_KEYS = {
    "id",
    "account_id",
    "name",
    "company_name",
    "industry",
    "description",
    "created_at",
    "updated_at",
}
_SCENARIO_KEYS = {
    "id",
    "workspace_id",
    "scenario_type",
    "status",
    "input_data",
    "result_data",
    "score",
    "created_at",
    "updated_at",
}


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _workspace(db: Session, aid: int, uid: int) -> int:
    return AIBusinessOSDemoService(settings=_SETTINGS).create_demo_company(db, aid, user_id=uid)[
        "id"
    ]


def _forbidden_counts(db: Session) -> dict[str, int]:
    return {m.__name__: db.query(m).count() for m in _FORBIDDEN_MODELS}


def test_billing_demo_is_free() -> None:
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_DEMO_SCENARIO] == 0
    assert costs[billing_service.USAGE_DEMO_REPORT] == 0


def test_scenario_creates_no_forbidden_entities(db_session: Session) -> None:
    """Прогон НЕ создаёт публикаций/CRM/workflow/платежей/списаний."""
    aid, uid = _account(db_session, "btsec1")
    wid = _workspace(db_session, aid, uid)
    before = _forbidden_counts(db_session)
    AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(
        db_session, wid, "growth", user_id=uid
    )
    assert _forbidden_counts(db_session) == before  # всё осталось 0


def test_scenario_isolated_in_demo_project(db_session: Session) -> None:
    """Прогон идёт в ОТДЕЛЬНОМ demo-проекте, не в реальном проекте пользователя."""
    from app.repositories import project_repository

    aid, uid = _account(db_session, "btsec2")
    real = project_repository.create_project(
        db_session, ProjectCreate(name="real", slug="realproj")
    )
    real.account_id = aid
    db_session.commit()
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(db_session, wid, "growth")
    demo_pid = sc["result_data"]["project_id"]
    assert demo_pid != real.id
    demo_project = project_repository.get_project_by_id(db_session, demo_pid)
    assert demo_project is not None and demo_project.slug.startswith("demo-")


def test_no_secrets_in_views(db_session: Session) -> None:
    aid, uid = _account(db_session, "btsec3")
    wid = _workspace(db_session, aid, uid)
    sc = AIBusinessOSScenarioService(settings=_SETTINGS).run_scenario(db_session, wid, "growth")
    blob = repr(sc).lower()
    for hint in _SECRET_HINTS:
        assert hint not in blob
    ws = repo.get_workspace(db_session, wid)
    assert set(repo.public_workspace_view(ws)) == _WORKSPACE_KEYS
    assert set(sc) == _SCENARIO_KEYS


def test_demo_mode_gate(db_session: Session) -> None:
    """При demo_mode=false demo-действия запрещены."""
    aid, _uid = _account(db_session, "btsec4")
    off = Settings(media_proxy_public_base_url="https://m.example.com", demo_mode=False)
    with pytest.raises(AIBusinessOSDemoError):
        AIBusinessOSDemoService(settings=off).create_demo_company(db_session, aid)


def test_auth_required(client: TestClient, db_session: Session) -> None:
    assert client.get("/demo/health").status_code == 401
    assert client.post("/demo/workspace/create", json={}).status_code == 401


def test_workspace_create_requires_account_id(client: TestClient, db_session: Session) -> None:
    """Без account_id воркспейс не создаётся (иначе tenant-check fail-open)."""
    _aid, uid = _account(db_session, "btsec_acc")
    resp = client.post("/demo/workspace/create", headers=_h(uid), json={})
    assert resp.status_code == 400


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Пользователь аккаунта B не может прогнать сценарий на воркспейсе аккаунта A."""
    aid_a, uid_a = _account(db_session, "btsec5a")
    _aid_b, uid_b = _account(db_session, "btsec5b")
    wid = _workspace(db_session, aid_a, uid_a)
    resp = client.post("/demo/scenario/growth/run", headers=_h(uid_b), json={"workspace_id": wid})
    assert resp.status_code in (403, 404)
    assert client.get(f"/demo/scenarios?workspace_id={wid}", headers=_h(uid_b)).status_code in (
        403,
        404,
    )
