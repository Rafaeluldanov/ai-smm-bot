"""Тесты движка автоматизации расписаний (offline, без live-публикации)."""

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
_MONDAY = "2026-07-13"  # понедельник (weekday 0)


def _seed(db: Session, slug: str = "teeon", connect: bool = True, balance: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    config = crm.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug)
    )
    category = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id, config_id=config.id, title="Мерч оптом", cta="Пишите в директ"
        ),
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
            mode="semi_auto",
        ),
    )
    if connect:
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@teeon"}
        )
    if balance:
        BillingService().manual_topup(db, account.id, balance, idempotency_key=f"seed-{slug}")
    return account.id, project.id


def test_list_tasks_from_plans(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    tasks = ScheduleAutomationService().list_schedule_tasks(db_session, project_id)
    assert len(tasks) == 1
    task = tasks[0]
    assert task["platform_key"] == "telegram"
    assert task["connection_status"] == "project_connection"
    assert task["can_run"] is True
    assert task["estimated_units_per_post"] > 0


def test_preview_due_no_writes(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.post import Post
    from app.models.schedule_run import ScheduleRun

    result = ScheduleAutomationService().preview_due_runs(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    assert result["dry_run"] is True
    assert result["due_count"] == 1
    assert result["entries"][0]["outcome"] == "would_create_draft"
    # Никаких записей.
    assert db_session.query(ScheduleRun).count() == 0
    assert db_session.query(Post).count() == 0


def test_run_due_creates_run_post_publication(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.post import Post
    from app.models.post_publication import PostPublication
    from app.models.schedule_run import ScheduleRun

    result = ScheduleAutomationService().run_due(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    assert result["created"] == 1
    run = db_session.query(ScheduleRun).one()
    assert run.status == "draft_created"
    post = db_session.query(Post).one()
    assert post.status == "needs_review"  # draft на ревью
    pub = db_session.query(PostPublication).one()
    # Публикация запланирована, но НЕ опубликована (live off).
    assert pub.status == "scheduled"
    assert pub.published_at is None
    assert run.post_id == post.id and run.publication_id == pub.id


def test_missing_connection_blocks(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    account_id, project_id = _seed(db_session, slug="nocon", connect=False)
    from app.config import Settings
    from app.models.post import Post
    from app.services import platform_connection_service as pcs_module

    # Токен-less local: без подключения и без env-fallback → missing_credentials.
    clean = Settings(_env_file=None, app_env="local")
    monkeypatch.setattr(pcs_module, "get_settings", lambda: clean)
    result = ScheduleAutomationService().run_due(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    assert result["entries"][0]["status"] == "missing_credentials"
    assert db_session.query(Post).count() == 0


def test_insufficient_balance_blocks(db_session: Session) -> None:
    account_id, project_id = _seed(db_session, slug="nobal", balance=1)
    from app.models.post import Post

    result = ScheduleAutomationService().run_due(
        db_session, account_id, project_id, date_arg=_MONDAY
    )
    assert result["entries"][0]["status"] == "insufficient_balance"
    assert db_session.query(Post).count() == 0
    assert BillingService().get_balance(db_session, account_id).balance_units == 1


def test_successful_run_debits_once(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    before = BillingService().get_balance(db_session, account_id).balance_units
    ScheduleAutomationService().run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    after = BillingService().get_balance(db_session, account_id).balance_units
    assert after < before  # списание произошло один раз


def test_duplicate_idempotency_no_duplicate(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.post import Post
    from app.models.schedule_run import ScheduleRun

    svc = ScheduleAutomationService()
    svc.run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    balance_after_first = BillingService().get_balance(db_session, account_id).balance_units
    second = svc.run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    assert second["created"] == 0 and second["skipped"] == 1
    # Ни дубля поста/прогона, ни повторного списания.
    assert db_session.query(Post).count() == 1
    assert db_session.query(ScheduleRun).count() == 1
    assert BillingService().get_balance(db_session, account_id).balance_units == balance_after_first


def test_no_live_publish_and_no_secrets(db_session: Session) -> None:
    account_id, project_id = _seed(db_session)
    from app.models.post_publication import PostPublication

    svc = ScheduleAutomationService()
    svc.run_due(db_session, account_id, project_id, date_arg=_MONDAY)
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"
    runs = svc.list_runs(db_session, project_id)
    assert _TOKEN not in str(runs)
    from app.models.schedule_run import ScheduleRun

    for run in db_session.query(ScheduleRun).all():
        assert _TOKEN not in str(run.run_metadata)
