"""Тесты биллинга предложений экспериментов (v0.4.3).

Preview/генерация/приём/отклонение/скрытие — бесплатно. Создание A/B из предложения
тарифицируется как обычное создание A/B (10 units), идемпотентно, с проверкой баланса.
"""

from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services import billing_service as billing_consts
from app.services.billing_service import BillingService, InsufficientBalanceError
from app.services.client_learning_service import ClientLearningService
from app.services.experiment_suggestion_service import (
    ExperimentSuggestionError,
    ExperimentSuggestionService,
)

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры бренд"]


def _seed(db: Session, slug: str, topup: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
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
    return account, project


def _balance(db: Session, account_id: int) -> int:
    return BillingService().get_balance(db, account_id).balance_units


def test_free_action_costs() -> None:
    costs = billing_consts.ACTION_COSTS
    assert costs[billing_consts.USAGE_EXPERIMENT_SUGGESTION_GENERATE] == 0
    assert costs[billing_consts.USAGE_EXPERIMENT_SUGGESTION_ACCEPT] == 0
    assert costs[billing_consts.USAGE_EXPERIMENT_SUGGESTION_WORKER_TICK] == 0
    # Создание A/B из предложения = цена создания A/B.
    assert (
        costs[billing_consts.USAGE_EXPERIMENT_SUGGESTION_CREATE_EXPERIMENT]
        == costs[billing_consts.USAGE_AB_EXPERIMENT_CREATE]
    )


def test_preview_is_free(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-prev")
    before = _balance(db_session, acc.id)
    ExperimentSuggestionService().preview_suggestions(db_session, project.id)
    assert _balance(db_session, acc.id) == before


def test_generate_is_free(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-gen")
    before = _balance(db_session, acc.id)
    ExperimentSuggestionService().generate_suggestions(db_session, project.id)
    assert _balance(db_session, acc.id) == before


def test_accept_reject_dismiss_free(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-decide")
    svc = ExperimentSuggestionService()
    gen = svc.generate_suggestions(db_session, project.id)
    ids = [s["id"] for s in gen["suggestions"]]
    before = _balance(db_session, acc.id)
    svc.accept_suggestion(db_session, ids[0])
    svc.reject_suggestion(db_session, ids[1])
    svc.dismiss_suggestion(db_session, ids[2])
    assert _balance(db_session, acc.id) == before


def test_create_experiment_charges_ab_price(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-create")
    svc = ExperimentSuggestionService()
    gen = svc.generate_suggestions(db_session, project.id)
    before = _balance(db_session, acc.id)
    svc.create_experiment_from_suggestion(db_session, gen["suggestions"][0]["id"])
    after = _balance(db_session, acc.id)
    assert before - after == billing_consts.ACTION_COSTS[billing_consts.USAGE_AB_EXPERIMENT_CREATE]


def test_create_experiment_idempotent_single_charge(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-idem")
    svc = ExperimentSuggestionService()
    gen = svc.generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    svc.create_experiment_from_suggestion(db_session, sid)
    mid = _balance(db_session, acc.id)
    svc.create_experiment_from_suggestion(db_session, sid)
    assert _balance(db_session, acc.id) == mid  # второе списание не происходит


def test_insufficient_balance_blocks_and_no_debit(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-poor", topup=0)  # баланс 0 < 10
    svc = ExperimentSuggestionService()
    gen = svc.generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    before = _balance(db_session, acc.id)
    try:
        svc.create_experiment_from_suggestion(db_session, sid)
        raise AssertionError("ожидали InsufficientBalanceError")
    except InsufficientBalanceError:
        pass
    # Баланс не изменился и предложение не помечено как experiment_created.
    assert _balance(db_session, acc.id) == before


def test_failed_create_no_debit(db_session: Session) -> None:
    acc, project = _seed(db_session, "sb-fail")
    svc = ExperimentSuggestionService()
    gen = svc.generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    svc.reject_suggestion(db_session, sid)  # делает предложение не-actionable
    before = _balance(db_session, acc.id)
    # Заблокированное создание (статус rejected) — без списания units.
    try:
        svc.create_experiment_from_suggestion(db_session, sid)
        raise AssertionError("ожидали ExperimentSuggestionError")
    except ExperimentSuggestionError:
        pass
    assert _balance(db_session, acc.id) == before
