"""Тесты сервиса A/B-тестирования (v0.4.2)."""

from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    client_learning_repository,
    content_experiment_repository,
    post_feedback_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.ab_testing_service import ABTestingService
from app.services.billing_service import BillingService


def _seed(db: Session, slug: str, topup: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
    return account, project, user


def test_create_experiment_from_topic(db_session: Session) -> None:
    _acc, project, user = _seed(db_session, "ab-topic")
    result = ABTestingService().create_experiment_from_topic(
        db_session, project.id, "telegram", "Футболки", variant_count=2, current_user_id=user.id
    )
    assert result["outcome"] == "created"
    assert result["experiment"]["status"] == "active"
    assert len(result["variants"]) == 2


def test_variants_create_draft_posts_no_live(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "ab-draft")
    result = ABTestingService().create_experiment_from_topic(
        db_session, project.id, "vk", "Худи", variant_count=2
    )
    variants = content_experiment_repository.list_variants_for_experiment(
        db_session, result["experiment"]["id"]
    )
    for v in variants:
        post = post_repository.get_post_by_id(db_session, v.post_id)
        assert post is not None
        assert post.status == "needs_review"
        assert post.published_at is None  # live-публикации нет


def test_variants_scored(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "ab-score")
    result = ABTestingService().create_experiment_from_topic(db_session, project.id, "vk", "Кружки")
    variants = content_experiment_repository.list_variants_for_experiment(
        db_session, result["experiment"]["id"]
    )
    assert all(v.quality_score is not None for v in variants)


def test_choose_manual_winner(db_session: Session) -> None:
    _acc, project, user = _seed(db_session, "ab-manual")
    result = ABTestingService().create_experiment_from_topic(db_session, project.id, "vk", "Сумки")
    eid = result["experiment"]["id"]
    variants = content_experiment_repository.list_variants_for_experiment(db_session, eid)
    svc = ABTestingService()
    final = svc.choose_winner(db_session, eid, method="manual", variant_id=variants[0].id)
    assert final["winner"]["variant_key"] == variants[0].variant_key
    assert final["experiment"]["status"] == "completed"


def test_choose_auto_winner_with_metrics(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "ab-auto")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Пакеты")
    eid = result["experiment"]["id"]
    variants = content_experiment_repository.list_variants_for_experiment(db_session, eid)
    svc.import_variant_metrics(
        db_session, variants[0].id, {"reach": 1000, "likes": 200, "impressions": 1100, "clicks": 60}
    )
    svc.import_variant_metrics(
        db_session, variants[1].id, {"reach": 1000, "likes": 10, "impressions": 1100, "clicks": 5}
    )
    final = svc.choose_winner(db_session, eid, method="auto")
    assert final["winner"]["variant_key"] == variants[0].variant_key
    assert final["winner"]["winner_reason"] in (
        "higher_er",
        "higher_ctr",
        "better_conversion_signal",
    )


def test_winner_updates_learning_profile(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "ab-learn")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Мерч")
    eid = result["experiment"]["id"]
    variants = content_experiment_repository.list_variants_for_experiment(db_session, eid)
    svc.choose_winner(db_session, eid, method="manual", variant_id=variants[0].id)
    counts = post_feedback_repository.aggregate_by_project(db_session, project.id)
    assert counts.get("approved", 0) >= 1
    assert counts.get("rejected", 0) >= 1  # loser
    assert client_learning_repository.get_profile(db_session, project.id, None) is not None


def test_idempotency_no_duplicate_experiment(db_session: Session) -> None:
    acc, project, _u = _seed(db_session, "ab-idem")
    svc = ABTestingService()
    first = svc.create_experiment_from_topic(
        db_session, project.id, "vk", "Тема", idempotency_key="k1"
    )
    bal1 = BillingService().get_balance(db_session, acc.id).balance_units
    second = svc.create_experiment_from_topic(
        db_session, project.id, "vk", "Тема", idempotency_key="k1"
    )
    bal2 = BillingService().get_balance(db_session, acc.id).balance_units
    assert first["outcome"] == "created"
    assert second["outcome"] == "skipped_duplicate"
    assert bal1 == bal2  # без двойного списания
    assert (
        len(content_experiment_repository.list_experiments_for_project(db_session, project.id)) == 1
    )


def test_record_variant_feedback_free(db_session: Session) -> None:
    acc, project, user = _seed(db_session, "ab-fb")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Тема")
    variants = content_experiment_repository.list_variants_for_experiment(
        db_session, result["experiment"]["id"]
    )
    before = BillingService().get_balance(db_session, acc.id).balance_units
    svc.record_variant_feedback(db_session, variants[0].id, "approved", current_user_id=user.id)
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert before == after
