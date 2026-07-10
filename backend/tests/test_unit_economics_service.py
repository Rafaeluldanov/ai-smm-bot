"""Тесты юнит-экономики и правил списания (offline, без сети/секретов).

Проверяют формулу генерации, наценку ×2, минимальные пороги, цены публикации и
аналитики, а также поведение биллинга: успешная публикация списывает один раз,
неуспешная не списывает, идемпотентность защищает от двойного списания.
"""

import math

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, user_repository
from app.services.billing_service import BillingService, InsufficientBalanceError
from app.services.unit_economics_service import (
    USAGE_POST_PUBLICATION,
    USAGE_TYPES,
    UnitEconomicsService,
)


def _svc(**over: object) -> UnitEconomicsService:
    params: dict[str, object] = {
        "ai_pricing_model": "gpt-5.4-mini",
        "ai_input_usd_per_1m": 0.75,
        "ai_output_usd_per_1m": 4.50,
        "billing_markup_multiplier": 2.0,
        "billing_usd_to_unit_rate": 100.0,
        "billing_min_post_units": 5,
        "billing_min_analytics_units": 3,
    }
    params.update(over)
    settings = Settings(_env_file=None, **params)
    return UnitEconomicsService(settings)


# --------------------------------------------------------------------------- #
# Формула генерации                                                           #
# --------------------------------------------------------------------------- #


def test_generation_units_matches_task_example() -> None:
    # 2000/500 токенов → 0.00375 USD × 2 = 0.0075 USD × 100 = 0.75 → floor 5 units.
    assert _svc().estimate_generation_units(2000, 500) == 5


def test_generation_breakdown_costs() -> None:
    br = _svc().estimate_generation_breakdown(1_000_000, 1_000_000)
    assert br.provider_cost_usd == pytest.approx(5.25)
    assert br.client_price_usd == pytest.approx(10.5)
    assert br.units == math.ceil(10.5 * 100)  # 1050
    assert br.markup_percent == 100


def test_markup_multiplier_scales_price() -> None:
    # Выше порога наценка ×2 ровно удваивает units против ×1.
    base = _svc(billing_markup_multiplier=1.0).estimate_generation_units(1_000_000, 1_000_000)
    doubled = _svc(billing_markup_multiplier=2.0).estimate_generation_units(1_000_000, 1_000_000)
    assert base == 525
    assert doubled == 1050 == base * 2


def test_min_post_units_floor_applied() -> None:
    # Крошечные затраты токенов → срабатывает минимальный порог.
    assert _svc().estimate_generation_units(1, 1) == 5
    assert _svc(billing_min_post_units=9).estimate_generation_units(1, 1) == 9


# --------------------------------------------------------------------------- #
# Публикация и аналитика                                                       #
# --------------------------------------------------------------------------- #


def test_publication_prices() -> None:
    svc = _svc()
    assert svc.estimate_publication_units("telegram", media_count=0) == 2
    assert svc.estimate_publication_units("vk", media_count=0) == 2
    assert svc.estimate_publication_units("telegram", media_count=3) == 3
    assert svc.estimate_publication_units("instagram", media_count=1) == 4
    # С генерацией текста добавляется стоимость генерации (5).
    assert svc.estimate_publication_units("telegram", media_count=1, has_ai_generation=True) == 8


def test_analytics_prices_by_depth() -> None:
    # v0.2.13: фиксированные цены light/standard/deep = 10/20/40 units за пост.
    svc = _svc()
    assert svc.estimate_analytics_units("light", 1) == 10
    assert svc.estimate_analytics_units("standard", 1) == 20
    assert svc.estimate_analytics_units("deep", 1) == 40
    # Линейно по числу постов.
    assert svc.estimate_analytics_units("deep", 3) == 120
    # Неизвестная глубина → ValueError.
    with pytest.raises(ValueError):
        svc.estimate_analytics_units("bogus")


def test_pricing_table_and_usage_types() -> None:
    rows = _svc().build_pricing_table()
    assert len(rows) == 9
    assert all({"key", "title", "units", "note"} <= set(r) for r in rows)
    assert set(USAGE_TYPES) == {
        "post_generation",
        "post_publication",
        "post_analytics",
        "schedule_generation",
        "media_processing",
    }


# --------------------------------------------------------------------------- #
# Правила списания в биллинге                                                  #
# --------------------------------------------------------------------------- #


def _account(db: Session) -> int:
    user = user_repository.create_user(db, email="econ@example.com", password_hash="x")
    account = account_repository.create_account(db, name="Econ", slug="econ", owner_user_id=user.id)
    return account.id


def test_successful_publication_debits_once(db_session: Session) -> None:
    billing = BillingService()
    account_id = _account(db_session)
    billing.get_or_create_billing_account(db_session, account_id)
    billing.manual_topup(db_session, account_id, 100, idempotency_key="topup-1")

    units = _svc().estimate_publication_units("telegram", media_count=1)  # 3
    billing.reserve_or_debit(
        db_session,
        account_id,
        event_type=USAGE_POST_PUBLICATION,
        units=units,
        idempotency_key="pub-post-42",
    )
    assert billing.get_balance(db_session, account_id).balance_units == 100 - units
    usage = billing.list_usage(db_session, account_id)
    assert any(u.event_type == USAGE_POST_PUBLICATION and u.units == units for u in usage)


def test_idempotency_prevents_double_debit(db_session: Session) -> None:
    billing = BillingService()
    account_id = _account(db_session)
    billing.get_or_create_billing_account(db_session, account_id)
    billing.manual_topup(db_session, account_id, 100, idempotency_key="topup-2")

    for _ in range(2):
        billing.reserve_or_debit(
            db_session,
            account_id,
            event_type=USAGE_POST_PUBLICATION,
            units=7,
            idempotency_key="pub-post-99",  # тот же ключ → списание один раз
        )
    assert billing.get_balance(db_session, account_id).balance_units == 93


def test_failed_publication_does_not_debit_and_refund_compensates(db_session: Session) -> None:
    billing = BillingService()
    account_id = _account(db_session)
    billing.get_or_create_billing_account(db_session, account_id)
    billing.manual_topup(db_session, account_id, 50, idempotency_key="topup-3")

    # Неуспешная публикация: списание просто не вызывается — баланс не меняется.
    assert billing.get_balance(db_session, account_id).balance_units == 50

    # Если списали, а публикация упала — компенсирующий refund возвращает units.
    billing.reserve_or_debit(
        db_session,
        account_id,
        event_type=USAGE_POST_PUBLICATION,
        units=5,
        idempotency_key="pub-fail-1",
    )
    assert billing.get_balance(db_session, account_id).balance_units == 45
    billing.refund(
        db_session,
        account_id,
        5,
        description="Публикация не удалась",
        idempotency_key="refund-fail-1",
    )
    assert billing.get_balance(db_session, account_id).balance_units == 50


def test_debit_blocked_when_insufficient_balance(db_session: Session) -> None:
    billing = BillingService()
    account_id = _account(db_session)
    billing.get_or_create_billing_account(db_session, account_id)
    billing.manual_topup(db_session, account_id, 2, idempotency_key="topup-4")
    with pytest.raises(InsufficientBalanceError):
        billing.reserve_or_debit(
            db_session,
            account_id,
            event_type=USAGE_POST_PUBLICATION,
            units=10,
            idempotency_key="pub-poor-1",
        )
    # Баланс не ушёл в минус.
    assert billing.get_balance(db_session, account_id).balance_units == 2
