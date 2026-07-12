"""Тесты интеграции предложений экспериментов в фоновый worker (v0.4.3).

Offline; никаких live-публикаций и внешних API. Проверяют безопасные дефолты
(выключено), dry-run, генерацию, авто-создание и отсутствие импорта publish_due.
"""

import inspect
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    experiment_suggestion_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import scheduler_worker_repository as lease_repo
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services import scheduler_worker_service as worker_module
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.scheduler_worker_service import LEASE_KEY, SchedulerWorkerService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"
_NOW = datetime(2026, 7, 13, 13, 0, tzinfo=UTC)  # понедельник 13:00
_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры бренд"]


def _seed(db: Session, slug: str = "wsug", balance: int = 500) -> int:
    """Проект: due-цель расписания (CRM-план) + обученный профиль (для рекомендаций)."""
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
            project_id=project.id, config_id=config.id, title="C", cta="CTA"
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
        ),
    )
    PlatformConnectionService().upsert_connection(
        db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@t"}
    )
    if balance:
        BillingService().manual_topup(db, account.id, balance, idempotency_key=f"seed-{slug}")
    learn = ClientLearningService()
    for title in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=title,
                status="needs_review",
                vk_text="Текст про " + title,
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return project.id


def _worker(**flags: object) -> SchedulerWorkerService:
    # Базовый worker включён (force всё равно нужен), плюс флаги предложений.
    return SchedulerWorkerService(settings=Settings(**flags))


def test_suggestions_disabled_by_default(db_session: Session) -> None:
    _seed(db_session)
    result = _worker().tick(db_session, owner_id="o1", now=_NOW, dry_run=True, force=True)
    assert result.experiment_suggestions_enabled is False
    assert result.experiment_suggestions_scanned == 0
    assert result.experiment_suggestions_created == 0


def test_suggestions_enabled_dry_run(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(experiment_suggestions_worker_enabled=True)
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=True, force=True)
    assert result.experiment_suggestions_enabled is True
    assert result.experiment_suggestions_dry_run is True
    assert result.experiment_suggestions_scanned > 0
    # Dry-run → ничего не записано (проверяем именно засеянный проект).
    assert result.experiment_suggestions_created == 0
    assert experiment_suggestion_repository.count_active_for_project(db_session, pid) == 0


def test_suggestions_enabled_generate(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(
        experiment_suggestions_worker_enabled=True, experiment_suggestions_dry_run=False
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert result.experiment_suggestions_enabled is True
    assert result.experiment_suggestions_dry_run is False
    assert result.experiment_suggestions_created > 0
    # auto_create ВЫКЛЮЧЕН (чистый случай): предложения есть, экспериментов — нет.
    assert result.experiments_created == 0
    assert experiment_suggestion_repository.count_active_for_project(db_session, pid) > 0


def test_worker_idempotent_double_tick_no_duplicates(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(
        experiment_suggestions_worker_enabled=True, experiment_suggestions_dry_run=False
    )
    first = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    active_after_first = experiment_suggestion_repository.count_active_for_project(db_session, pid)
    # Повторный тик (тот же worker/owner/окно) — дедуп по cooldown + idempotency-key.
    second = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert first.experiment_suggestions_created > 0
    assert second.experiment_suggestions_created == 0
    assert second.experiment_suggestions_skipped > 0
    # Число активных предложений не выросло — дублей нет.
    assert (
        experiment_suggestion_repository.count_active_for_project(db_session, pid)
        == active_after_first
    )


def test_worker_auto_create_experiment(db_session: Session) -> None:
    pid = _seed(db_session)
    worker = _worker(
        experiment_suggestions_worker_enabled=True,
        experiment_suggestions_dry_run=False,
        experiment_suggestions_auto_create=True,
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert result.experiments_created > 0
    rows = experiment_suggestion_repository.list_for_project(db_session, pid)
    assert any(r.status == "experiment_created" and r.experiment_id for r in rows)


def test_worker_no_live_publish(db_session: Session) -> None:
    pid = _seed(db_session)
    from app.models.post import Post
    from app.models.post_publication import PostPublication

    worker = _worker(
        experiment_suggestions_worker_enabled=True,
        experiment_suggestions_dry_run=False,
        experiment_suggestions_auto_create=True,
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    # Авто-создание действительно произошло (иначе проверка «нет live» вакуумна).
    assert result.experiments_created > 0
    # Все посты проекта (в т.ч. варианты авто-A/B) — не опубликованы live.
    posts = db_session.query(Post).filter(Post.project_id == pid).all()
    variant_posts = [p for p in posts if (p.status or "") == "needs_review"]
    assert variant_posts  # варианты A/B действительно созданы как черновики ревью
    for p in posts:
        assert p.status != "published"
        assert p.published_at is None
    for pub in db_session.query(PostPublication).all():
        assert pub.status != "published"
    assert _TOKEN not in str(result.as_dict())


def test_worker_result_no_secrets(db_session: Session) -> None:
    _seed(db_session)
    worker = _worker(
        experiment_suggestions_worker_enabled=True, experiment_suggestions_dry_run=False
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert _TOKEN not in str(result.as_dict())


def test_lease_held_by_other_no_suggestions(db_session: Session) -> None:
    pid = _seed(db_session)
    # Другой worker держит активную lease → тик не выполняется, предложений нет.
    lease_repo.acquire_lease(db_session, LEASE_KEY, "other:1:aa", 300, now=_NOW)
    worker = _worker(
        experiment_suggestions_worker_enabled=True, experiment_suggestions_dry_run=False
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert result.lease_acquired is False
    assert result.experiment_suggestions_created == 0
    assert experiment_suggestion_repository.count_active_for_project(db_session, pid) == 0


def test_auto_create_gated_by_worker_flag(db_session: Session) -> None:
    pid = _seed(db_session)
    # auto_create=True, но worker выключен → фича не активна, экспериментов нет.
    worker = _worker(
        experiment_suggestions_worker_enabled=False,
        experiment_suggestions_dry_run=False,
        experiment_suggestions_auto_create=True,
    )
    result = worker.tick(db_session, owner_id="o1", now=_NOW, dry_run=False, force=True)
    assert result.experiment_suggestions_enabled is False
    assert result.experiments_created == 0
    assert experiment_suggestion_repository.count_active_for_project(db_session, pid) == 0


def test_worker_module_does_not_import_publish_due() -> None:
    # Статическая проверка безопасности: worker не тянет live-публикацию.
    source = inspect.getsource(worker_module)
    assert "publish_due" not in source
    assert "publish_post_live" not in source
