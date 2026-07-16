"""Тесты безопасности AI Business OS Pilot (v0.9.1, offline).

Инварианты (Part 16): pilot-слой advisory — НЕ меняет бизнес, НЕ выполняет workflow, НЕ трогает CRM,
НЕ создаёт платежей, НЕ ходит во внешние API. Проверяем: tenant; pilot_mode disabled (403);
нет CRM/публикаций/workflow/платежей; секретов нет; billing 0; workspace требует account_id.
"""

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
from app.repositories import pilot_repository as repo
from app.services import billing_service
from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
from app.services.ai_business_pilot_service import AIBusinessPilotService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")

# Сущности, которые pilot-слой НЕ имеет права создавать/менять (Part 16).
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
    "company_name",
    "industry",
    "status",
    "created_by",
    "created_at",
    "updated_at",
}
_PROFILE_KEYS = {
    "id",
    "workspace_id",
    "products",
    "services",
    "team",
    "sales_channels",
    "business_description",
    "current_revenue",
    "target_revenue",
    "kpi",
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
    pilot = AIBusinessPilotService(settings=_SETTINGS)
    ws = pilot.create_pilot_workspace(db, aid, company_name="TEEON Pilot", user_id=uid)
    pilot.create_business_profile(
        db, ws["id"], current_revenue=5_000_000, target_revenue=10_000_000, user_id=uid
    )
    return ws["id"]


def _forbidden_counts(db: Session) -> dict[str, int]:
    return {m.__name__: db.query(m).count() for m in _FORBIDDEN_MODELS}


def test_billing_pilot_is_free() -> None:
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_PILOT_ANALYSIS] == 0
    assert costs[billing_service.USAGE_PILOT_REPORT] == 0


def test_pilot_run_creates_no_forbidden_entities(db_session: Session) -> None:
    """Прогон пилота НЕ создаёт публикаций/CRM/workflow/платежей/списаний."""
    aid, uid = _account(db_session, "plsec1")
    wid = _workspace(db_session, aid, uid)
    before = _forbidden_counts(db_session)
    AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(
        db_session, wid, user_id=uid
    )
    assert _forbidden_counts(db_session) == before  # всё осталось 0


def test_no_secrets_in_views(db_session: Session) -> None:
    aid, uid = _account(db_session, "plsec2")
    wid = _workspace(db_session, aid, uid)
    out = AIBusinessPilotService(settings=_SETTINGS).get_workspace(db_session, wid)
    blob = repr(out).lower()
    for hint in _SECRET_HINTS:
        assert hint not in blob
    workspace = repo.get_workspace(db_session, wid)
    profile = repo.get_profile(db_session, wid)
    assert set(repo.public_workspace_view(workspace)) == _WORKSPACE_KEYS
    assert set(repo.public_profile_view(profile)) == _PROFILE_KEYS


def test_auth_required(client: TestClient, db_session: Session) -> None:
    assert client.post("/pilot/workspaces", json={}).status_code == 401
    assert client.get("/pilot/workspaces?account_id=1").status_code == 401


def test_workspace_requires_account_id(client: TestClient, db_session: Session) -> None:
    _aid, uid = _account(db_session, "plsec3")
    assert client.post("/pilot/workspaces", headers=_h(uid), json={}).status_code == 400


def test_pilot_mode_disabled_403(client: TestClient, db_session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """При pilot_mode=false pilot API-действия → 403."""
    from app.config import get_settings

    aid, uid = _account(db_session, "plsec4")
    settings = get_settings()
    monkeypatch.setattr(settings, "pilot_mode", False)
    resp = client.post(
        "/pilot/workspaces", headers=_h(uid), json={"account_id": aid, "company_name": "X"}
    )
    assert resp.status_code == 403


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Пользователь аккаунта B не видит/не запускает пилот аккаунта A."""
    aid_a, uid_a = _account(db_session, "plsec5a")
    _aid_b, uid_b = _account(db_session, "plsec5b")
    wid = _workspace(db_session, aid_a, uid_a)
    assert client.get(f"/pilot/workspaces/{wid}/dashboard", headers=_h(uid_b)).status_code in (
        403,
        404,
    )
    assert client.post(f"/pilot/workspaces/{wid}/run", headers=_h(uid_b)).status_code in (403, 404)


def test_pilot_project_slug_collision_no_cross_tenant_leak(db_session: Session) -> None:
    """Если pilot-slug занят проектом ЧУЖОГО аккаунта — прогон НЕ пишет туда и health не читает."""
    from app.models.performance_snapshot import PerformanceSnapshot
    from app.repositories import project_repository
    from app.schemas.project import ProjectCreate
    from app.services.ai_business_pilot_scenario_service import AIBusinessPilotScenarioService
    from app.services.ai_business_pilot_service import (
        AIBusinessPilotService,
        pilot_project_slug,
    )

    aid_a, _uid_a = _account(db_session, "plsec6a")  # «атакующий» аккаунт A
    aid_b, uid_b = _account(db_session, "plsec6b")  # аккаунт B (жертва)
    wid = _workspace(db_session, aid_b, uid_b)  # воркспейс аккаунта B
    # Аккаунт A заранее захватил детерминированный slug pilot-проекта воркспейса B.
    foreign = project_repository.create_project(
        db_session, ProjectCreate(name="foreign", slug=pilot_project_slug(wid))
    )
    foreign.account_id = aid_a
    db_session.commit()
    before = db_session.query(PerformanceSnapshot).filter_by(project_id=foreign.id).count()

    run = AIBusinessPilotScenarioService(settings=_SETTINGS).run_growth_pilot(db_session, wid)
    assert run["status"] == "failed"  # отказ, а не запись в чужой проект
    # В чужой проект ничего не записано.
    after = db_session.query(PerformanceSnapshot).filter_by(project_id=foreign.id).count()
    assert after == before
    # health воркспейса B не читает чужой проект.
    health = AIBusinessPilotService(settings=_SETTINGS).get_business_health(db_session, wid)
    assert health["has_data"] is False
