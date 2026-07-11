"""Тесты биллинга A/B-экспериментов (v0.4.2)."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    content_experiment_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.services.ab_testing_service import ABTestingService
from app.services.billing_service import BillingService, InsufficientBalanceError


def _seed(db: Session, slug: str, topup: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
    return account, project


def _balance(db: Session, account_id: int) -> int:
    return BillingService().get_balance(db, account_id).balance_units


def test_preview_is_free(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-prev")
    before = _balance(db_session, acc.id)
    ABTestingService().preview_topic(db_session, project.id, "vk", "Тема", 2)
    assert _balance(db_session, acc.id) == before


def test_create_experiment_charges_units(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-create")
    before = _balance(db_session, acc.id)
    ABTestingService().create_experiment_from_topic(
        db_session, project.id, "vk", "Тема", variant_count=2
    )
    assert _balance(db_session, acc.id) == before - 10


def test_extra_variant_costs_more(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-extra")
    before = _balance(db_session, acc.id)
    ABTestingService().create_experiment_from_topic(
        db_session, project.id, "vk", "Тема", variant_count=3
    )
    # 10 базовых + 5 за третий вариант.
    assert _balance(db_session, acc.id) == before - 15


def test_failed_create_no_debit(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-fail", topup=3)  # < 10 units
    before = _balance(db_session, acc.id)
    with pytest.raises(InsufficientBalanceError):
        ABTestingService().create_experiment_from_topic(db_session, project.id, "vk", "Тема", 2)
    assert _balance(db_session, acc.id) == before  # ничего не списано
    # эксперимент не создан
    assert content_experiment_repository.list_experiments_for_project(db_session, project.id) == []


def test_idempotency_no_double_debit(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-idem")
    svc = ABTestingService()
    svc.create_experiment_from_topic(db_session, project.id, "vk", "Тема", idempotency_key="k")
    bal1 = _balance(db_session, acc.id)
    svc.create_experiment_from_topic(db_session, project.id, "vk", "Тема", idempotency_key="k")
    assert _balance(db_session, acc.id) == bal1


def test_same_topic_no_key_charges_each_time(db_session: Session) -> None:
    """Без idempotency_key два эксперимента по одной теме — оба платные (не бесплатный дубль)."""
    acc, project = _seed(db_session, "eb-nokey")
    svc = ABTestingService()
    before = _balance(db_session, acc.id)
    svc.create_experiment_from_topic(db_session, project.id, "vk", "Летняя распродажа")
    svc.create_experiment_from_topic(db_session, project.id, "vk", "Летняя распродажа")
    # Два эксперимента → списано 20 units (по 10), без «бесплатного» второго.
    assert _balance(db_session, acc.id) == before - 20
    assert (
        len(content_experiment_repository.list_experiments_for_project(db_session, project.id)) == 2
    )


def test_manual_winner_free(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-manual")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Тема")
    eid = result["experiment"]["id"]
    variants = content_experiment_repository.list_variants_for_experiment(db_session, eid)
    before = _balance(db_session, acc.id)
    svc.choose_winner(db_session, eid, method="manual", variant_id=variants[0].id)
    assert _balance(db_session, acc.id) == before  # ручной winner бесплатен


def test_auto_winner_analysis_charges(db_session: Session) -> None:
    acc, project = _seed(db_session, "eb-auto")
    svc = ABTestingService()
    result = svc.create_experiment_from_topic(db_session, project.id, "vk", "Тема")
    eid = result["experiment"]["id"]
    before = _balance(db_session, acc.id)
    svc.choose_winner(db_session, eid, method="auto")
    assert _balance(db_session, acc.id) == before - 5  # анализ 5 units
