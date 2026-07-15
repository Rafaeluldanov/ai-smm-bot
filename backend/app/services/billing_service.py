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

# Типы usage для safety-слоя уведомлений (v0.5.2). Бесплатны в MVP.
USAGE_NOTIFICATION_SAFETY_CHECK = "notification_safety_check"
USAGE_WEBHOOK_SUBSCRIPTION_CREATE = "webhook_subscription_create"
USAGE_WEBHOOK_DELIVERY_PREVIEW = "webhook_delivery_preview"

# Типы usage для email-шаблонов/SMTP-sandbox (v0.5.3). Бесплатны в MVP (реальной доставки нет).
USAGE_EMAIL_TEMPLATE_PREVIEW = "email_template_preview"
USAGE_EMAIL_TEST_SEND = "email_test_send"
USAGE_EMAIL_DIGEST_RENDER = "email_digest_render"

# Типы usage для Telegram-уведомлений (v0.5.4). Бесплатны в MVP (реальной доставки нет).
USAGE_TELEGRAM_BINDING_CREATE = "telegram_binding_create"
USAGE_TELEGRAM_NOTIFICATION_PREVIEW = "telegram_notification_preview"
USAGE_TELEGRAM_TEST_SEND = "telegram_test_send"
USAGE_TELEGRAM_DIGEST_RENDER = "telegram_digest_render"

# Типы usage для Telegram webhook/polling sandbox (v0.5.5). Бесплатны в MVP (реальных вызовов нет).
USAGE_TELEGRAM_UPDATE_SIMULATE = "telegram_update_simulate"
USAGE_TELEGRAM_WEBHOOK_PREVIEW = "telegram_webhook_preview"
USAGE_TELEGRAM_POLLING_PREVIEW = "telegram_polling_preview"

# Типы usage для авто-синхронизации Яндекс Диска (v0.5.7). Бесплатны в MVP.
USAGE_YANDEX_SYNC_PREVIEW = "yandex_sync_preview"
USAGE_YANDEX_SYNC_RUN = "yandex_sync_run"
USAGE_YANDEX_SYNC_WORKER_TICK = "yandex_sync_worker_tick"

# Типы usage для Calendar Assistant (v0.5.8). Бесплатны в MVP (реальная публикация — прежний поток).
USAGE_AUTOPILOT_CALENDAR_PREVIEW = "autopilot_calendar_preview"
USAGE_AUTOPILOT_CALENDAR_CREATE = "autopilot_calendar_create"
USAGE_AUTOPILOT_CALENDAR_APPLY = "autopilot_calendar_apply"

# Типы usage для live-readiness audit (v0.5.9). Бесплатны в MVP; заблокированная публикация — 0.
USAGE_LIVE_READINESS_CHECK = "live_readiness_check"
USAGE_LIVE_READINESS_PLATFORM_CHECK = "live_readiness_platform_check"
USAGE_LIVE_READINESS_ENABLE = "live_readiness_enable"

# Типы usage для AI Learning Loop (v0.6.5). Обучение — бесплатно (0 units).
USAGE_AI_LEARNING_ANALYZE = "ai_learning_analyze"
USAGE_AI_LEARNING_RECOMMEND = "ai_learning_recommend"
USAGE_AI_LEARNING_FEEDBACK = "ai_learning_feedback"
USAGE_AI_LEARNING_RESET = "ai_learning_reset"

# Типы usage для Autonomous Content Strategist (v0.6.6). Стратегия — бесплатно (0 units).
USAGE_CONTENT_STRATEGY_ANALYSIS = "content_strategy_analysis"
USAGE_CONTENT_STRATEGY_RECOMMENDATION = "content_strategy_recommendation"
USAGE_CONTENT_STRATEGY_APPLY = "content_strategy_apply"

# Типы usage для AI Campaign Manager (v0.6.7). Кампании — бесплатно (0 units).
USAGE_AI_CAMPAIGN_CREATE = "ai_campaign_create"
USAGE_AI_CAMPAIGN_PLAN = "ai_campaign_plan"
USAGE_AI_CAMPAIGN_APPLY = "ai_campaign_apply"

# Типы usage для AI Sales & Lead Intelligence (v0.6.8). Аналитика — бесплатно (0 units).
USAGE_SALES_INTELLIGENCE_ANALYSIS = "sales_intelligence_analysis"
USAGE_SALES_INTELLIGENCE_REPORT = "sales_intelligence_report"
USAGE_SALES_INTELLIGENCE_LEAD = "sales_intelligence_lead"

# Типы usage для AI Business Growth Agent (v0.6.9). Advisory — бесплатно (0 units).
USAGE_BUSINESS_GROWTH_ANALYSIS = "business_growth_analysis"
USAGE_BUSINESS_GROWTH_REPORT = "business_growth_report"
USAGE_BUSINESS_GROWTH_APPLY = "business_growth_apply"

# Типы usage для Autonomous Business OS (v0.7.0). Advisory + planning — бесплатно (0 units).
USAGE_BUSINESS_OS_ANALYSIS = "business_os_analysis"
USAGE_BUSINESS_OS_PLAN = "business_os_plan"
USAGE_BUSINESS_OS_APPLY = "business_os_apply"

# Типы usage для AI Chief of Staff (v0.7.1). Advisory + assistant — бесплатно (0 units).
USAGE_CHIEF_BRIEFING = "chief_briefing"
USAGE_CHIEF_TASKS = "chief_tasks"

# Типы usage для AI Workflow Manager (v0.7.2). Workflow management — бесплатно (0 units).
USAGE_WORKFLOW_CREATE = "workflow_create"
USAGE_WORKFLOW_ANALYSIS = "workflow_analysis"

# Типы usage для AI Operations Control Center (v0.7.3). Аналитика/советы — бесплатно (0 units).
USAGE_OPERATIONS_ANALYSIS = "operations_analysis"
USAGE_OPERATIONS_REPORT = "operations_report"

# Типы usage для AI Decision Engine (v0.7.4). Аналитика/рекомендации — бесплатно (0 units).
USAGE_DECISION_ANALYSIS = "decision_analysis"
USAGE_DECISION_REPORT = "decision_report"

# Типы usage для Telegram live rollout (v0.6.0). Preview/dry-run/blocked — бесплатны; реальная
# публикация списывает существующие publication-units (USAGE_AUTO_PUBLISH_ACTION).
USAGE_TELEGRAM_LIVE_ROLLOUT_PREVIEW = "telegram_live_rollout_preview"
USAGE_TELEGRAM_LIVE_ROLLOUT_RUN_DRY = "telegram_live_rollout_run_dry"
USAGE_TELEGRAM_LIVE_ROLLOUT_PUBLISH_ATTEMPT = "telegram_live_rollout_publish_attempt"

# Типы usage для мониторинга live-автопилота (v0.6.1). Бесплатны в MVP; без списаний.
USAGE_LIVE_MONITORING_SNAPSHOT = "live_monitoring_snapshot"
USAGE_LIVE_MONITORING_INCIDENT_ACTION = "live_monitoring_incident_action"
USAGE_LIVE_AUTOPILOT_PAUSE = "live_autopilot_pause"
USAGE_LIVE_AUTOPILOT_RESUME = "live_autopilot_resume"

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
    # v0.5.2: safety-слой уведомлений — бесплатно в MVP (реальной доставки нет).
    USAGE_NOTIFICATION_SAFETY_CHECK: 0,
    USAGE_WEBHOOK_SUBSCRIPTION_CREATE: 0,
    USAGE_WEBHOOK_DELIVERY_PREVIEW: 0,
    # v0.5.3: email-шаблоны/SMTP-sandbox — бесплатно в MVP (реальной email-доставки нет).
    USAGE_EMAIL_TEMPLATE_PREVIEW: 0,
    USAGE_EMAIL_TEST_SEND: 0,
    USAGE_EMAIL_DIGEST_RENDER: 0,
    # v0.5.4: Telegram-уведомления — бесплатно в MVP (реальной Telegram-доставки нет).
    USAGE_TELEGRAM_BINDING_CREATE: 0,
    USAGE_TELEGRAM_NOTIFICATION_PREVIEW: 0,
    USAGE_TELEGRAM_TEST_SEND: 0,
    USAGE_TELEGRAM_DIGEST_RENDER: 0,
    # v0.5.5: Telegram webhook/polling sandbox — бесплатно в MVP (реальных Telegram-вызовов нет).
    USAGE_TELEGRAM_UPDATE_SIMULATE: 0,
    USAGE_TELEGRAM_WEBHOOK_PREVIEW: 0,
    USAGE_TELEGRAM_POLLING_PREVIEW: 0,
    # v0.5.7: авто-синхронизация Яндекс Диска — бесплатно в MVP (реальной сети нет по умолчанию).
    USAGE_YANDEX_SYNC_PREVIEW: 0,
    USAGE_YANDEX_SYNC_RUN: 0,
    USAGE_YANDEX_SYNC_WORKER_TICK: 0,
    # v0.5.8: Calendar Assistant — бесплатно в MVP (публикация — прежний платный поток).
    USAGE_AUTOPILOT_CALENDAR_PREVIEW: 0,
    USAGE_AUTOPILOT_CALENDAR_CREATE: 0,
    USAGE_AUTOPILOT_CALENDAR_APPLY: 0,
    USAGE_LIVE_READINESS_CHECK: 0,
    USAGE_LIVE_READINESS_PLATFORM_CHECK: 0,
    USAGE_LIVE_READINESS_ENABLE: 0,
    USAGE_TELEGRAM_LIVE_ROLLOUT_PREVIEW: 0,
    USAGE_TELEGRAM_LIVE_ROLLOUT_RUN_DRY: 0,
    USAGE_TELEGRAM_LIVE_ROLLOUT_PUBLISH_ATTEMPT: 0,
    USAGE_LIVE_MONITORING_SNAPSHOT: 0,
    USAGE_LIVE_MONITORING_INCIDENT_ACTION: 0,
    USAGE_LIVE_AUTOPILOT_PAUSE: 0,
    USAGE_LIVE_AUTOPILOT_RESUME: 0,
    USAGE_AI_LEARNING_ANALYZE: 0,
    USAGE_AI_LEARNING_RECOMMEND: 0,
    USAGE_AI_LEARNING_FEEDBACK: 0,
    USAGE_AI_LEARNING_RESET: 0,
    USAGE_CONTENT_STRATEGY_ANALYSIS: 0,
    USAGE_CONTENT_STRATEGY_RECOMMENDATION: 0,
    USAGE_CONTENT_STRATEGY_APPLY: 0,
    USAGE_AI_CAMPAIGN_CREATE: 0,
    USAGE_AI_CAMPAIGN_PLAN: 0,
    USAGE_AI_CAMPAIGN_APPLY: 0,
    USAGE_SALES_INTELLIGENCE_ANALYSIS: 0,
    USAGE_SALES_INTELLIGENCE_REPORT: 0,
    USAGE_SALES_INTELLIGENCE_LEAD: 0,
    USAGE_BUSINESS_GROWTH_ANALYSIS: 0,
    USAGE_BUSINESS_GROWTH_REPORT: 0,
    USAGE_BUSINESS_GROWTH_APPLY: 0,
    USAGE_BUSINESS_OS_ANALYSIS: 0,
    USAGE_BUSINESS_OS_PLAN: 0,
    USAGE_BUSINESS_OS_APPLY: 0,
    USAGE_CHIEF_BRIEFING: 0,
    USAGE_CHIEF_TASKS: 0,
    USAGE_WORKFLOW_CREATE: 0,
    USAGE_WORKFLOW_ANALYSIS: 0,
    USAGE_OPERATIONS_ANALYSIS: 0,
    USAGE_OPERATIONS_REPORT: 0,
    USAGE_DECISION_ANALYSIS: 0,
    USAGE_DECISION_REPORT: 0,
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
