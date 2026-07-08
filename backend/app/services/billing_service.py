"""Сервис биллинга: депозит в units, списания за действия, usage-события.

Реальных платежей НЕТ: пополнение — только ручное (fake-провайдер). Идемпотентность
операций — по ``idempotency_key`` (уникальный в журнале). При недостатке баланса
действие НЕ выполняется — возвращается понятная ошибка (генерация/публикация не
запускаются).
"""

from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.billing import BillingAccount, BillingLedgerEntry, UsageEvent
from app.repositories import billing_repository

# Стоимость действий в units (оценка; провайдерских затрат ещё нет).
ACTION_COSTS: dict[str, int] = {
    "ai_generation": 10,
    "media_selection": 2,
    "image_processing": 3,
    "publication_preview": 1,
    "publication_live": 5,
    "analytics": 1,
}
_DEFAULT_ACTION_COST = 1


class BillingError(Exception):
    """Ошибка биллинга (некорректная сумма и т. п.) — API → 400."""


class InsufficientBalanceError(BillingError):
    """Недостаточно средств на балансе — действие не выполняется (API → 402/409)."""

    def __init__(self, required: int, available: int) -> None:
        self.required = required
        self.available = available
        super().__init__(
            f"Недостаточно units: требуется {required}, доступно {available}. "
            "Пополните депозит перед запуском."
        )


class BillingService:
    """Депозит, списания, возвраты и usage-учёт (без реальных платежей)."""

    def get_or_create_billing_account(
        self, db: Session, account_id: int, tariff_plan_slug: str | None = None
    ) -> BillingAccount:
        """Вернуть биллинг-счёт аккаунта, создав при отсутствии.

        Если задан тариф с включёнными units — начислить их разовым topup.
        """
        existing = billing_repository.get_billing_account_by_account_id(db, account_id)
        if existing is not None:
            return existing

        included = 0
        if tariff_plan_slug:
            tariff = billing_repository.get_tariff_by_slug(db, tariff_plan_slug)
            included = tariff.included_units if tariff is not None else 0
        billing = billing_repository.create_billing_account(
            db, account_id, tariff_plan_slug, balance_units=included
        )
        if included > 0:
            billing_repository.create_ledger_entry(
                db,
                billing.id,
                "topup",
                included,
                included,
                description=f"Включённые units тарифа {tariff_plan_slug}",
                entry_metadata={"kind": "included_units", "tariff": tariff_plan_slug},
            )
        return billing

    def get_balance(self, db: Session, account_id: int) -> BillingAccount:
        """Вернуть биллинг-счёт (баланс) аккаунта (создаёт при отсутствии)."""
        return self.get_or_create_billing_account(db, account_id)

    def manual_topup(
        self,
        db: Session,
        account_id: int,
        amount_units: int,
        idempotency_key: str | None = None,
        description: str = "Ручное пополнение",
    ) -> BillingLedgerEntry:
        """Пополнить депозит вручную (fake-провайдер). Идемпотентно по ключу."""
        if amount_units <= 0:
            raise BillingError("Сумма пополнения должна быть положительной")
        if idempotency_key:
            existing = billing_repository.get_ledger_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing
        billing = self.get_or_create_billing_account(db, account_id)
        new_balance = billing.balance_units + amount_units
        entry, _applied = self._record_entry(
            db,
            billing,
            "topup",
            amount_units,
            new_balance,
            description,
            idempotency_key,
            {"kind": "manual"},
        )
        return entry

    def estimate_action_cost(self, action_type: str, payload: dict[str, Any] | None = None) -> int:
        """Оценить стоимость действия в units (масштабируется по ``count``)."""
        base = ACTION_COSTS.get(action_type, _DEFAULT_ACTION_COST)
        count = 1
        if isinstance(payload, dict):
            try:
                count = max(1, int(payload.get("count", 1)))
            except (TypeError, ValueError):
                count = 1
        return base * count

    def reserve_or_debit(
        self,
        db: Session,
        account_id: int,
        event_type: str,
        units: int,
        metadata: dict[str, Any] | None = None,
        project_id: int | None = None,
        post_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> BillingLedgerEntry:
        """Списать units за действие и записать usage-событие.

        Если баланса не хватает — :class:`InsufficientBalanceError` (действие не
        выполняется). Идемпотентно по ключу: повторный вызов не списывает дважды.
        """
        if units < 0:
            raise BillingError("Списание не может быть отрицательным")
        if idempotency_key:
            existing = billing_repository.get_ledger_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing
        billing = self.get_or_create_billing_account(db, account_id)
        if billing.balance_units < units:
            raise InsufficientBalanceError(units, billing.balance_units)

        new_balance = billing.balance_units - units
        entry, applied = self._record_entry(
            db,
            billing,
            "debit",
            -units,
            new_balance,
            f"Списание за {event_type}",
            idempotency_key,
            metadata or {},
        )
        # usage-событие пишем только при фактическом списании (не на идемпотентном повторе).
        if applied:
            billing_repository.create_usage_event(
                db,
                account_id,
                event_type,
                units,
                project_id=project_id,
                post_id=post_id,
                event_metadata=metadata or {},
            )
        return entry

    def refund(
        self,
        db: Session,
        account_id: int,
        units: int,
        description: str = "Возврат",
        idempotency_key: str | None = None,
    ) -> BillingLedgerEntry:
        """Вернуть units на баланс (идемпотентно по ключу)."""
        if units <= 0:
            raise BillingError("Возврат должен быть положительным")
        if idempotency_key:
            existing = billing_repository.get_ledger_by_idempotency_key(db, idempotency_key)
            if existing is not None:
                return existing
        billing = self.get_or_create_billing_account(db, account_id)
        new_balance = billing.balance_units + units
        entry, _applied = self._record_entry(
            db,
            billing,
            "refund",
            units,
            new_balance,
            description,
            idempotency_key,
            {"kind": "refund"},
        )
        return entry

    @staticmethod
    def _record_entry(
        db: Session,
        billing: BillingAccount,
        entry_type: str,
        amount_units: int,
        new_balance: int,
        description: str,
        idempotency_key: str | None,
        metadata: dict[str, Any],
    ) -> tuple[BillingLedgerEntry, bool]:
        """Записать проводку, затем обновить баланс. Возврат ``(entry, applied)``.

        Проводка вставляется ПЕРВОЙ: уникальный ``idempotency_key`` гарантирует, что
        при гонке повторов баланс не изменится дважды — на конфликте вставки
        откатываемся и возвращаем уже существующую проводку (``applied=False``),
        не трогая баланс. Так операция идемпотентна даже при конкурентных ретраях.
        """
        try:
            entry = billing_repository.create_ledger_entry(
                db,
                billing.id,
                entry_type,
                amount_units,
                new_balance,
                description=description,
                idempotency_key=idempotency_key,
                entry_metadata=metadata,
            )
        except IntegrityError:
            db.rollback()
            existing = (
                billing_repository.get_ledger_by_idempotency_key(db, idempotency_key)
                if idempotency_key
                else None
            )
            if existing is None:
                raise
            return existing, False
        billing_repository.set_balance(db, billing, new_balance)
        return entry, True

    def list_ledger(
        self, db: Session, account_id: int, limit: int = 100
    ) -> list[BillingLedgerEntry]:
        """Журнал операций аккаунта (свежие первыми)."""
        billing = self.get_or_create_billing_account(db, account_id)
        return billing_repository.list_ledger(db, billing.id, limit)

    def list_usage(self, db: Session, account_id: int, limit: int = 100) -> list[UsageEvent]:
        """Usage-события аккаунта (свежие первыми)."""
        return billing_repository.list_usage_events(db, account_id, limit)
