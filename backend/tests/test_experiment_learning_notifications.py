"""Тесты интеграции уведомлений в эксперименты/предложения/обучение (v0.5.0). Offline."""

from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    content_experiment_repository,
    notification_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ab_testing_service import ABTestingService
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.experiment_suggestion_service import ExperimentSuggestionService

_TOPICS = ["Футболки промо", "Худи осень", "Кружки бренд", "Стикеры акция"]


def _seed(db: Session, slug: str, with_profile: bool = False):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    if with_profile:
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
    return account, project, user


def test_suggestion_created_notification(db_session: Session) -> None:
    _account, project, owner = _seed(db_session, "eln-sug", with_profile=True)
    result = ExperimentSuggestionService().generate_suggestions(db_session, project.id)
    assert result["created"] > 0
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "experiment_suggestion_created" for n in notes)


def test_winner_selected_notification(db_session: Session) -> None:
    _account, project, owner = _seed(db_session, "eln-win")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Сумки")
    eid = result["experiment"]["id"]
    variants = content_experiment_repository.list_variants_for_experiment(db_session, eid)
    svc.choose_winner(db_session, eid, method="manual", variant_id=variants[0].id)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "experiment_winner_selected" for n in notes)


def test_learning_profile_updated_notification(db_session: Session) -> None:
    _account, project, owner = _seed(db_session, "eln-learn", with_profile=True)
    ClientLearningService().rebuild_learning_profile(db_session, project.id)
    notes = notification_repository.list_for_user(db_session, owner.id)
    assert any(n.notification_type == "learning_profile_updated" for n in notes)


def test_no_recipient_skip_safe(db_session: Session) -> None:
    # Проект без аккаунта → получателя нет → пропуск без ошибки.
    project = project_repository.create_project(
        db_session, ProjectCreate(name="eln-norec", slug="eln-norec")
    )
    db_session.commit()
    # rebuild не должен падать даже без владельца.
    ClientLearningService().rebuild_learning_profile(db_session, project.id)
