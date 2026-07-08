"""Pydantic-схемы биллинга (депозит в units, журнал, usage, тарифы)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BillingBalanceRead(BaseModel):
    """Баланс биллинг-счёта аккаунта."""

    model_config = ConfigDict(from_attributes=True)

    account_id: int
    balance_units: int
    currency: str
    tariff_plan_slug: str | None = None
    status: str


class TopupRequest(BaseModel):
    """Ручное пополнение депозита (fake-провайдер, без реального платежа)."""

    amount_units: int = Field(gt=0)
    idempotency_key: str | None = None
    description: str = "Ручное пополнение"


class LedgerEntryRead(BaseModel):
    """Запись журнала биллинга."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    entry_type: str
    amount_units: int
    balance_after_units: int
    description: str
    idempotency_key: str | None = None
    entry_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class UsageEventRead(BaseModel):
    """Usage-событие потребления ресурсов."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    project_id: int | None = None
    post_id: int | None = None
    event_type: str
    units: int
    event_metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class EstimateRequest(BaseModel):
    """Запрос оценки стоимости действия (в units)."""

    action_type: str
    payload: dict[str, Any] | None = None
    account_id: int | None = None


class EstimateResult(BaseModel):
    """Результат оценки стоимости действия."""

    action_type: str
    estimated_units: int
    balance_units: int | None = None
    affordable: bool | None = None


class TariffPlanRead(BaseModel):
    """Тарифный план."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    included_units: int
    unit_price_rub: int
    markup_percent: int
    status: str
