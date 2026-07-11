"""Тесты биллинга движка расписаний: dry-run free, списание, idempotency."""

from sqlalchemy.orm import Session

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
from app.services.schedule_automation_service import ScheduleAutomationService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_MONDAY = "2026-07-13"


def _seed(db: Session, slug: str = "teeon", balance: int = 500):  # noqa: ANN202
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
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@x"}
    )
    if balance:
        BillingService().manual_topup(db, account.id, balance, idempotency_key=f"seed-{slug}")
    return account.id, project.id


def test_dry_run_is_free(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    billing = BillingService()
    before = billing.get_balance(db_session, account_id).balance_units
    ScheduleAutomationService().run_due_dry(db_session, account_id, project_id, date_arg=_MONDAY)
    assert billing.get_balance(db_session, account_id).balance_units == before


def test_run_due_charges_units(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    billing = BillingService()
    before = billing.get_balance(db_session, account_id).balance_units
    result = ScheduleAutomationService().run_due(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    charged = result["entries"][0]["units_charged"]
    assert charged > 0
    assert billing.get_balance(db_session, account_id).balance_units == before - charged


def test_insufficient_balance_no_debit(db_session: Session) -> None:
    account_id, project_id = _seed(db_session, slug="poor", balance=1)
    billing = BillingService()
    result = ScheduleAutomationService().run_due(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    assert result["entries"][0]["status"] == "insufficient_balance"
    assert billing.get_balance(db_session, account_id).balance_units == 1  # без списания


def test_idempotency_no_double_charge(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    billing = BillingService()
    svc = ScheduleAutomationService()
    svc.run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    after_first = billing.get_balance(db_session, account_id).balance_units
    svc.run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    assert billing.get_balance(db_session, account_id).balance_units == after_first
