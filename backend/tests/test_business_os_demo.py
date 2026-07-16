"""Тесты demo-данных AI Business OS MVP Testing (v0.9.0, offline).

Инварианты:
- demo-воркспейс/компания создаются; цель формируется; сценарии заводятся; результаты сохраняются.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.repositories import demo_testing_repository as repo
from app.services.ai_business_os_demo_service import AIBusinessOSDemoService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> AIBusinessOSDemoService:
    return AIBusinessOSDemoService(settings=_SETTINGS)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def test_create_demo_company(db_session: Session) -> None:
    aid, uid = _account(db_session, "dm1")
    ws = _svc().create_demo_company(db_session, aid, user_id=uid)
    assert ws["company_name"] == "TEEON Demo" and ws["industry"] == "apparel"
    assert ws["account_id"] == aid


def test_create_demo_goal() -> None:
    goal = _svc().create_demo_goal()
    assert goal["current_value"] == 5_000_000 and goal["target_value"] == 10_000_000
    assert goal["horizon_months"] == 12


def test_create_demo_scenario(db_session: Session) -> None:
    aid, uid = _account(db_session, "dm2")
    svc = _svc()
    ws = svc.create_demo_company(db_session, aid, user_id=uid)
    sc = svc.create_demo_scenario(db_session, ws["id"], "growth", user_id=uid)
    assert sc["scenario_type"] == "growth" and sc["status"] == "draft"


def test_unknown_scenario_type_rejected(db_session: Session) -> None:
    import pytest

    from app.services.ai_business_os_demo_service import AIBusinessOSDemoError

    aid, uid = _account(db_session, "dm3")
    svc = _svc()
    ws = svc.create_demo_company(db_session, aid, user_id=uid)
    with pytest.raises(AIBusinessOSDemoError):
        svc.create_demo_scenario(db_session, ws["id"], "bogus", user_id=uid)


def test_result_saved(db_session: Session) -> None:
    aid, uid = _account(db_session, "dm4")
    svc = _svc()
    ws = svc.create_demo_company(db_session, aid, user_id=uid)
    scenario = repo.create_scenario(
        db_session, workspace_id=ws["id"], scenario_type="growth", status="running"
    )
    saved = repo.save_result(
        db_session, scenario, status="completed", result_data={"score": 88.0}, score=88.0
    )
    assert saved.status == "completed" and saved.score == 88.0


def test_audit_workspace_created(db_session: Session) -> None:
    from app.models.audit_log import AuditLogEntry

    aid, uid = _account(db_session, "dm5")
    _svc().create_demo_company(db_session, aid, user_id=uid)
    actions = {e.action for e in db_session.query(AuditLogEntry).all()}
    assert "demo.workspace_created" in actions
