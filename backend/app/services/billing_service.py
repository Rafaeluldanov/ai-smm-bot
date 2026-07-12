"""Сервис биллинга: депозит в units, списания за действия, usage-события.

Реальных платежей НЕТ: пополнение — только ручное (fake-провайдер). Идемпотентность
операций — по ``idempotency_key`` (уникальный в журнале). При недостатке баланса
действие НЕ выполняется — возвращается понятная ошибка (генерация/публикация не
запускаются).
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.billing import BillingAccount, BillingLedgerEntry, UsageEvent
from app.repositories import billing_repository

if TYPE_CHECKING:
    from app.config import Settings

# Типы usage для review/обучения/автоматизации (v0.4.0). Значения — стабильные
# строковые коды, идущие в UsageEvent.event_type.
USAGE_REVIEW_PUBLISH_NOW = "review_publish_now"
USAGE_LEARNING_PROFILE_REBUILD = "learning_profile_rebuild"
USAGE_CONTENT_SCORING = "content_scoring"
USAGE_AUTO_PUBLISH_ACTION = "auto_publish_action"

# Типы usage для импорта метрик и обратной связи обучения (v0.4.1).
USAGE_METRICS_IMPORT = "metrics_import"
USAGE_LEARNING_REBUILD = "learning_rebuild"
USAGE_MANUAL_METRICS_SAVE = "manual_metrics_save"

# Типы usage для A/B-тестирования и оптимизации тем (v0.4.2).
USAGE_AB_EXPERIMENT_CREATE = "ab_experiment_create"
USAGE_VARIANT_GENERATION = "variant_generation"
USAGE_TOPIC_OPTIMIZATION = "topic_optimization"
USAGE_EXPERIMENT_ANALYSIS = "experiment_analysis"
USAGE_WINNER_SELECTION = "winner_selection"

# Типы usage для предложений экспериментов worker-ом (v0.4.3).
USAGE_EXPERIMENT_SUGGESTION_GENERATE = "experiment_suggestion_generate"
USAGE_EXPERIMENT_SUGGESTION_ACCEPT = "experiment_suggestion_accept"
USAGE_EXPERIMENT_SUGGESTION_CREATE_EXPERIMENT = "experiment_suggestion_create_experiment"
USAGE_EXPERIMENT_SUGGESTION_WORKER_TICK = "experiment_suggestion_worker_tick"

# Типы usage для автовыбора темы (v0.4.4). Все бесплатны: применение решения к драфту
# включено в обычную генерацию draft по расписанию (USAGE_SCHEDULE_GENERATION).
USAGE_TOPIC_DECISION_PREVIEW = "topic_decision_preview"
USAGE_TOPIC_DECISION_CREATE = "topic_decision_create"
USAGE_TOPIC_DECISION_APPLY_TO_DRAFT = "topic_decision_apply_to_draft"

# Типы usage для автовыбора медиа (v0.4.5). Все бесплатны: применение решения к драфту
# включено в обычную генерацию draft по расписанию.
USAGE_MEDIA_DECISION_PREVIEW = "media_decision_preview"
USAGE_MEDIA_DECISION_CREATE = "media_decision_create"
USAGE_MEDIA_DECISION_APPLY_TO_DRAFT = "media_decision_apply_to_draft"

# Типы usage для оценки качества медиа (v0.4.6). Все бесплатны в MVP (без внешнего AI).
USAGE_MEDIA_QUALITY_PREVIEW = "media_quality_preview"
USAGE_MEDIA_QUALITY_SCORE = "media_quality_score"
USAGE_MEDIA_QUALITY_DASHBOARD = "media_quality_dashboard"

# Типы usage для fingerprint/дедупликации медиа (v0.4.7). Все бесплатны в MVP (без внешнего AI).
USAGE_MEDIA_FINGERPRINT_PREVIEW = "media_fingerprint_preview"
USAGE_MEDIA_FINGERPRINT_CALCULATE = "media_fingerprint_calculate"
USAGE_MEDIA_DUPLICATE_PREVIEW = "media_duplicate_preview"
USAGE_MEDIA_DUPLICATE_CALCULATE = "media_duplicate_calculate"

# Типы usage для курирования медиатеки (v0.4.8). Все бесплатны в MVP (без внешнего AI).
USAGE_MEDIA_CURATION_PREVIEW = "media_curation_preview"
USAGE_MEDIA_CURATION_GENERATE = "media_curation_generate"
USAGE_MEDIA_CURATION_APPLY = "media_curation_apply"

# Типы usage для collaborative review медиатеки (v0.4.9). Бесплатны в MVP.
USAGE_MEDIA_CURATION_REVIEW_COMMENT = "media_curation_review_comment"
USAGE_MEDIA_CURATION_REVIEW_APPROVE = "media_curation_review_approve"
USAGE_MEDIA_CURATION_REVIEW_APPLY = "media_curation_review_apply"

# Типы usage для внутренних уведомлений (v0.5.0). Бесплатны в MVP (без внешней доставки).
USAGE_NOTIFICATION_CREATE = "notification_create"
USAGE_NOTIFICATION_OVERDUE_SCAN = "notification_overdue_scan"
USAGE_NOTIFICATION_DIGEST = "notification_digest"

# Типы usage для доставки уведомлений/дайджестов (v0.5.1). Бесплатны в MVP (доставки нет).
USAGE_NOTIFICATION_DELIVERY_PREVIEW = "notification_delivery_preview"
USAGE_NOTIFICATION_DELIVERY_SEND = "notification_delivery_send"
USAGE_NOTIFICATION_DIGEST_GENERATE = "notification_digest_generate"
USAGE_NOTIFICATION_DIGEST_SEND = "notification_digest_send"

# Стоимость действий в units (оценка; провайдерских затрат ещё нет).
ACTION_COSTS: dict[str, int] = {
    "ai_generation": 10,
    "media_selection": 2,
    "image_processing": 3,
    "publication_preview": 1,
    "publication_live": 5,
    "analytics": 1,
    # v0.4.0: сбор фидбэка и превью-скоринг — бесплатны; публикация — как обычная
    # живая публикация; глубокий пересчёт профиля — 5 units.
    USAGE_CONTENT_SCORING: 0,
    USAGE_LEARNING_PROFILE_REBUILD: 5,
    USAGE_REVIEW_PUBLISH_NOW: 5,
    USAGE_AUTO_PUBLISH_ACTION: 5,
    # v0.4.1: manual/preview — бесплатно; стоимость реального импорта считается по
    # глубине в unit_economics; пересчёт обучения — 5 units.
    USAGE_MANUAL_METRICS_SAVE: 0,
    USAGE_METRICS_IMPORT: 0,
    USAGE_LEARNING_REBUILD: 5,
    # v0.4.2: preview/оптимизация/ручной winner — бесплатно; создание A/B — 10 units;
    # доп. вариант — 5; скоринг/авто-winner анализ — 5.
    USAGE_TOPIC_OPTIMIZATION: 0,
    USAGE_WINNER_SELECTION: 0,
    USAGE_AB_EXPERIMENT_CREATE: 10,
    USAGE_VARIANT_GENERATION: 5,
    USAGE_EXPERIMENT_ANALYSIS: 5,
    # v0.4.3: генерация/приём предложений и worker-tick — бесплатно; создание
    # эксперимента из предложения тарифицируется как обычное создание A/B (см. AB-путь).
    USAGE_EXPERIMENT_SUGGESTION_GENERATE: 0,
    USAGE_EXPERIMENT_SUGGESTION_ACCEPT: 0,
    USAGE_EXPERIMENT_SUGGESTION_WORKER_TICK: 0,
    USAGE_EXPERIMENT_SUGGESTION_CREATE_EXPERIMENT: 10,
    # v0.4.4: автовыбор темы — бесплатно (preview/создание решения/применение к драфту).
    # Реальная стоимость — только за создание draft по расписанию (USAGE_SCHEDULE_GENERATION).
    USAGE_TOPIC_DECISION_PREVIEW: 0,
    USAGE_TOPIC_DECISION_CREATE: 0,
    USAGE_TOPIC_DECISION_APPLY_TO_DRAFT: 0,
    # v0.4.5: автовыбор медиа — бесплатно; применение к драфту включено в генерацию draft.
    USAGE_MEDIA_DECISION_PREVIEW: 0,
    USAGE_MEDIA_DECISION_CREATE: 0,
    USAGE_MEDIA_DECISION_APPLY_TO_DRAFT: 0,
    # v0.4.6: оценка качества медиа — бесплатно в MVP (без внешнего AI).
    USAGE_MEDIA_QUALITY_PREVIEW: 0,
    USAGE_MEDIA_QUALITY_SCORE: 0,
    USAGE_MEDIA_QUALITY_DASHBOARD: 0,
    # v0.4.7: fingerprint/дедупликация медиа — бесплатно в MVP (без внешнего AI).
    USAGE_MEDIA_FINGERPRINT_PREVIEW: 0,
    USAGE_MEDIA_FINGERPRINT_CALCULATE: 0,
    USAGE_MEDIA_DUPLICATE_PREVIEW: 0,
    USAGE_MEDIA_DUPLICATE_CALCULATE: 0,
    # v0.4.8: курирование медиатеки — бесплатно в MVP (без внешнего AI).
    USAGE_MEDIA_CURATION_PREVIEW: 0,
    USAGE_MEDIA_CURATION_GENERATE: 0,
    USAGE_MEDIA_CURATION_APPLY: 0,
    # v0.4.9: collaborative review медиатеки — бесплатно в MVP (комментарии/approve/apply).
    USAGE_MEDIA_CURATION_REVIEW_COMMENT: 0,
    USAGE_MEDIA_CURATION_REVIEW_APPROVE: 0,
    USAGE_MEDIA_CURATION_REVIEW_APPLY: 0,
    # v0.5.0: внутренние уведомления — бесплатно в MVP (без внешней доставки).
    USAGE_NOTIFICATION_CREATE: 0,
    USAGE_NOTIFICATION_OVERDUE_SCAN: 0,
    USAGE_NOTIFICATION_DIGEST: 0,
    # v0.5.1: доставка уведомлений/дайджестов (sandbox) — бесплатно в MVP (реальной доставки нет).
    USAGE_NOTIFICATION_DELIVERY_PREVIEW: 0,
    USAGE_NOTIFICATION_DELIVERY_SEND: 0,
    USAGE_NOTIFICATION_DIGEST_GENERATE: 0,
    USAGE_NOTIFICATION_DIGEST_SEND: 0,
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

    def __init__(self, settings: "Settings | None" = None) -> None:
        # Настройки нужны для флага paid_actions_enforced (dev может отключать оплату).
        self._settings = settings

    def _paid_actions_enforced(self) -> bool:
        settings = self._settings
        if settings is None:
            from app.config import get_settings

            settings = get_settings()
        return bool(settings.paid_actions_enforced)

    # --- Единый API платных действий (Part 6 v0.3.1) --------------------- #

    def ensure_balance(self, db: Session, account_id: int, units: int) -> None:
        """Проверить, что на счёте достаточно units. Иначе InsufficientBalanceError."""
        if units <= 0 or not self._paid_actions_enforced():
            return
        billing = self.get_or_create_billing_account(db, account_id)
        if billing.balance_units < units:
            raise InsufficientBalanceError(units, billing.balance_units)

    def debit_for_action(
        self,
        db: Session,
        account_id: int,
        units: int,
        usage_type: str,
        idempotency_key: str | None = None,
        metadata: dict[str, Any] | None = None,
        project_id: int | None = None,
        post_id: int | None = None,
    ) -> "BillingLedgerEntry | None":
        """Списать units за платное действие (идемпотентно, не в минус).

        Единая точка платных действий: проверяет баланс и списывает через
        ``reserve_or_debit``. При ``paid_actions_enforced=false`` (dev) — бесплатно
        (возвращает None, без списания). Успех списывает один раз; повтор с тем же
        ключом не списывает второй раз; недостаток баланса не выполняет действие.
        """
        if units <= 0 or not self._paid_actions_enforced():
            return None
        return self.reserve_or_debit(
            db,
            account_id,
            event_type=usage_type,
            units=units,
            metadata=metadata,
            project_id=project_id,
            post_id=post_id,
            idempotency_key=idempotency_key,
        )

    def credit_payment(
        self,
        db: Session,
        account_id: int,
        units: int,
        provider_payment_id: str | None = None,
        idempotency_key: str | None = None,
        description: str = "Пополнение по оплате",
    ) -> BillingLedgerEntry:
        """Зачислить units после подтверждённой оплаты (идемпотентно, один раз)."""
        key = idempotency_key or (f"payment-{provider_payment_id}" if provider_payment_id else None)
        return self.manual_topup(
            db, account_id, units, idempotency_key=key, description=description
        )

    def refund_or_compensate(
        self,
        db: Session,
        account_id: int,
        units: int,
        reason: str = "Компенсация неуспешного действия",
        idempotency_key: str | None = None,
    ) -> BillingLedgerEntry:
        """Вернуть/компенсировать units (например, если платное действие упало)."""
        return self.refund(
            db, account_id, units, description=reason, idempotency_key=idempotency_key
        )

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
