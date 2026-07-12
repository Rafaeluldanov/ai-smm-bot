"""Движок автоматизации расписаний Botfleet (безопасный, без live-публикации).

Клиент создал расписание (``CrmPublishingPlan``) → Botfleet находит due-слоты и для
каждого создаёт **draft/needs_review** пост + ``PostPublication`` (pending/scheduled),
списывает units и пишет лог (``ScheduleRun`` + audit). **Живой публикации НЕТ**, внешние
API не вызываются.

Правила:
- креды берутся из подключения проекта (:mod:`platform_connection_service`); токен наружу
  не выходит; missing → ``missing_credentials`` (пост не создаётся);
- недостаток баланса → ``insufficient_balance`` (пост не создаётся, списания нет);
- успех создаёт draft и списывает units один раз (идемпотентно);
- повтор того же due-слота (``idempotency_key``) не создаёт дубль и не списывает дважды;
- секретов нет ни в ``run_metadata``, ни в аудите.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.crm_bot_smm import CrmPublishingPlan
from app.models.post import Post
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import (
    media_asset_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    schedule_run_repository,
)
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.services.audit_log_service import (
    ACTION_AUTOMATION_AUTO_PUBLISH_BLOCKED,
    ACTION_AUTOMATION_AUTO_PUBLISH_SUCCEEDED,
    ACTION_SCHEDULE_RUN_DRAFT_CREATED,
    ACTION_SCHEDULE_RUN_FAILED,
    ACTION_SCHEDULE_RUN_INSUFFICIENT_BALANCE,
    ACTION_SCHEDULE_RUN_MISSING_CREDENTIALS,
    ACTION_SCHEDULE_RUN_PREVIEW,
    ACTION_SCHEDULE_RUN_STARTED,
    AuditLogService,
)
from app.services.billing_service import (
    USAGE_AUTO_PUBLISH_ACTION,
    BillingService,
    InsufficientBalanceError,
)
from app.services.platform_connection_service import PlatformConnectionService
from app.services.unit_economics_service import (
    DEFAULT_POST_INPUT_TOKENS,
    DEFAULT_POST_OUTPUT_TOKENS,
    USAGE_SCHEDULE_GENERATION,
    UnitEconomicsService,
)

# Платное действие: генерация draft по due-слоту расписания.
USAGE_SCHEDULE_DRAFT = "schedule_due_draft_generation"
# Режим, при котором авто-публикация запрещена (создаём только draft).
_AUTO_PUBLISH_MODE = "auto_publish"
# Режимы автоматизации (v0.4.0).
AUTOMATION_SEMI_AUTO = "semi_auto"
AUTOMATION_FULL_AUTO = "full_auto"


class ScheduleAutomationError(Exception):
    """Ошибка автоматизации расписаний (проект не найден / чужой аккаунт) — API → 400."""


@dataclass(frozen=True)
class _DueEntry:
    """Один due-слот расписания (план × платформа × дата × время)."""

    plan: CrmPublishingPlan
    platform: str
    run_date: str
    planned_time: str
    idempotency_key: str


class ScheduleAutomationService:
    """Обработка due-задач расписаний: preview / dry-run / реальное создание draft."""

    def __init__(
        self,
        billing_service: BillingService | None = None,
        economics: UnitEconomicsService | None = None,
        audit_service: AuditLogService | None = None,
        connection_service: PlatformConnectionService | None = None,
        learning_service: Any | None = None,
        publication_service: Any | None = None,
        review_service: Any | None = None,
        topic_decision_service: Any | None = None,
        media_decision_service: Any | None = None,
        settings: Any | None = None,
    ) -> None:
        self._billing = billing_service or BillingService()
        self._economics = economics or UnitEconomicsService()
        self._audit = audit_service or AuditLogService()
        self._connections = connection_service or PlatformConnectionService()
        # v0.4.0: обучение/оценка контента и (для full_auto) публикация. Ленивое
        # построение, чтобы не тянуть тяжёлые зависимости и избежать циклов импорта.
        self._learning = learning_service
        self._publication = publication_service
        self._review = review_service
        # v0.4.4: автовыбор темы (learning-driven). Ленивое построение; выключено по умолчанию.
        self._topic_decision = topic_decision_service
        # v0.4.5: автовыбор медиа (learning-driven). Ленивое построение; выключено по умолчанию.
        self._media_decision = media_decision_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Планы / due-логика                                                 #
    # ------------------------------------------------------------------ #

    def _plans(
        self, db: Session, project_id: int, platform_key: str | None
    ) -> list[CrmPublishingPlan]:
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return []
        out: list[CrmPublishingPlan] = []
        for plan in crm_repo.list_plans_by_config(db, config.id):
            if not plan.is_active:
                continue
            platforms = plan.platforms or []
            if platform_key and platform_key not in platforms:
                continue
            out.append(plan)
        return out

    @staticmethod
    def _within_range(plan: CrmPublishingPlan, run_date: str) -> bool:
        if plan.start_date and run_date < plan.start_date:
            return False
        return not (plan.end_date and run_date > plan.end_date)

    @staticmethod
    def _resolve_run_date(date_arg: str | None, now: datetime | None) -> str:
        if date_arg and date_arg not in ("today", "now"):
            return date_arg
        base = now or datetime.now(UTC)
        return base.date().isoformat()

    @staticmethod
    def _time_is_due(planned_time: str, now: datetime | None) -> bool:
        if now is None:
            return True
        return planned_time <= now.strftime("%H:%M")

    def _find_due(
        self,
        db: Session,
        project_id: int,
        run_date: str,
        now: datetime | None,
        platform_key: str | None,
    ) -> list[_DueEntry]:
        weekday = date.fromisoformat(run_date).weekday()  # Пн=0
        due: list[_DueEntry] = []
        for plan in self._plans(db, project_id, platform_key):
            if weekday not in (plan.weekdays or []):
                continue
            if not self._within_range(plan, run_date):
                continue
            times = plan.publish_times or ["12:00"]
            for platform in plan.platforms or []:
                if platform_key and platform != platform_key:
                    continue
                for planned_time in times:
                    if not self._time_is_due(planned_time, now):
                        continue
                    key = f"sched-{project_id}-{plan.id}-{platform}-{run_date}-{planned_time}"
                    due.append(_DueEntry(plan, platform, run_date, planned_time, key))
        return due

    def _next_run_at(self, plan: CrmPublishingPlan, now: datetime | None) -> str | None:
        """Ближайший запуск (best-effort) из weekdays/publish_times."""
        weekdays = sorted(plan.weekdays or [])
        times = sorted(plan.publish_times or [])
        if not weekdays or not times:
            return None
        base = now or datetime.now(UTC)
        for add in range(0, 8):
            day = base.date().fromordinal(base.date().toordinal() + add)
            if day.weekday() not in weekdays:
                continue
            for t in times:
                cand = datetime.fromisoformat(f"{day.isoformat()}T{t}").replace(tzinfo=UTC)
                if cand > base:
                    return cand.isoformat()
        return None

    # ------------------------------------------------------------------ #
    # Оценка стоимости                                                   #
    # ------------------------------------------------------------------ #

    def estimate_schedule_run_units(self, platform: str, media_count: int = 0) -> int:
        """units за создание одного draft по расписанию (генерация текста)."""
        return self._economics.estimate_generation_units(
            DEFAULT_POST_INPUT_TOKENS, DEFAULT_POST_OUTPUT_TOKENS, USAGE_SCHEDULE_GENERATION
        )

    # ------------------------------------------------------------------ #
    # 1. Карточки задач расписания                                       #
    # ------------------------------------------------------------------ #

    def list_schedule_tasks(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> list[dict[str, Any]]:
        """Карточки задач расписания (планы × платформы) с готовностью к запуску."""
        now = datetime.now(UTC)
        cards: list[dict[str, Any]] = []
        for plan in self._plans(db, project_id, platform_key):
            category = crm_repo.get_category_by_id(db, plan.category_id)
            for platform in plan.platforms or []:
                if platform_key and platform != platform_key:
                    continue
                creds = self._connections.resolve_publish_credentials(db, project_id, platform)
                warnings: list[str] = []
                if creds.source == "missing":
                    warnings.append("Подключите платформу — заполните API/ID в разделе платформы.")
                if plan.mode == _AUTO_PUBLISH_MODE:
                    warnings.append(
                        "Режим auto_publish: live выключен — будет создан только draft."
                    )
                cards.append(
                    {
                        "plan_id": plan.id,
                        "platform_key": platform,
                        "title": (category.title if category is not None else None)
                        or "План публикаций",
                        "category_title": category.title if category is not None else None,
                        "weekdays": plan.weekdays or [],
                        "publish_times": plan.publish_times or [],
                        "posts_per_day": plan.posts_per_day,
                        "mode": plan.mode,
                        "timezone": plan.timezone,
                        "start_date": plan.start_date,
                        "end_date": plan.end_date,
                        "status": "active" if plan.is_active else "paused",
                        "next_run_at": self._next_run_at(plan, now),
                        "estimated_units_per_post": self.estimate_schedule_run_units(platform),
                        "connection_status": creds.source,
                        "can_run": creds.source != "missing",
                        "warnings": warnings,
                    }
                )
        return cards

    # ------------------------------------------------------------------ #
    # 2. Preview / dry-run (без записи)                                   #
    # ------------------------------------------------------------------ #

    def preview_due_runs(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        date_arg: str | None = None,
        now: datetime | None = None,
        platform_key: str | None = None,
    ) -> dict[str, Any]:
        """Что было бы сделано по due-задачам (БЕЗ записи в БД)."""
        self._verify_ownership(db, account_id, project_id)
        run_date = self._resolve_run_date(date_arg, now)
        due = self._find_due(db, project_id, run_date, now, platform_key)
        balance = self._billing.get_balance(db, account_id).balance_units
        entries: list[dict[str, Any]] = []
        total_units = 0
        remaining = balance
        for entry in due:
            creds = self._connections.resolve_publish_credentials(db, project_id, entry.platform)
            media_ids = self._select_media(db, project_id, entry.plan)
            units = self.estimate_schedule_run_units(entry.platform, len(media_ids))
            existing = schedule_run_repository.get_by_idempotency_key(db, entry.idempotency_key)
            if existing is not None and existing.status == "draft_created":
                outcome = "already_done"
            elif creds.source == "missing":
                outcome = "missing_credentials"
            elif remaining < units:
                outcome = "insufficient_balance"
            else:
                outcome = "would_create_draft"
                total_units += units
                remaining -= units
            entries.append(
                {
                    "plan_id": entry.plan.id,
                    "platform_key": entry.platform,
                    "run_date": entry.run_date,
                    "planned_time": entry.planned_time,
                    "estimated_units": units,
                    "media_count": len(media_ids),
                    "credentials_source": creds.source,
                    "outcome": outcome,
                    "would_create_draft": outcome == "would_create_draft",
                    "live_publish": False,
                }
            )
        self._audit.record(
            db,
            ACTION_SCHEDULE_RUN_PREVIEW,
            account_id=account_id,
            project_id=project_id,
            entity_type="schedule_preview",
            metadata={"run_date": run_date, "due_count": len(due), "platform": platform_key},
        )
        # v0.4.4: превью решений автовыбора темы (только при включённом worker-флаге; без записи).
        topic_decisions_previewed = self._preview_topic_decisions(db, project_id, due)
        # v0.4.5: превью решений автовыбора медиа (только при включённом worker-флаге; без записи).
        media_decisions_previewed = self._preview_media_decisions(db, project_id, due)
        return {
            "dry_run": True,
            "run_date": run_date,
            "due_count": len(due),
            "total_units": total_units,
            "balance_units": balance,
            "affordable": balance >= total_units,
            "entries": entries,
            "live_calls": False,
            "topic_decisions_previewed": topic_decisions_previewed,
            "media_decisions_previewed": media_decisions_previewed,
        }

    def _preview_topic_decisions(self, db: Session, project_id: int, due: list[_DueEntry]) -> int:
        """Число слотов, для которых worker предпросмотрит тему (без записи). 0 если выключено."""
        if not self._topic_selection_preview_active():
            return 0
        count = 0
        for entry in due:
            try:
                self._topic_decision_svc().preview_decision_for_plan(
                    db, project_id, entry.platform, plan_id=entry.plan.id
                )
                count += 1
            except Exception:  # noqa: BLE001 — превью не должно ронять preview расписания
                with contextlib.suppress(Exception):
                    db.rollback()
        return count

    def run_due_dry(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        date_arg: str | None = None,
        now: datetime | None = None,
        platform_key: str | None = None,
    ) -> dict[str, Any]:
        """Dry-run: то же, что preview_due_runs (без записи, для кнопки «Preview due»)."""
        return self.preview_due_runs(db, account_id, project_id, date_arg, now, platform_key)

    # ------------------------------------------------------------------ #
    # 3. Реальное создание draft (без live-публикации)                   #
    # ------------------------------------------------------------------ #

    def run_due(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        date_arg: str | None = None,
        now: datetime | None = None,
        platform_key: str | None = None,
    ) -> dict[str, Any]:
        """Создать draft/needs_review по каждому due-слоту (идемпотентно). Live НЕТ."""
        self._verify_ownership(db, account_id, project_id)
        run_date = self._resolve_run_date(date_arg, now)
        due = self._find_due(db, project_id, run_date, now, platform_key)
        results: list[dict[str, Any]] = []
        created = skipped = 0
        topic_decisions_created = low_confidence_decisions = 0
        media_decisions_created = low_confidence_media_decisions = no_media_decisions = 0
        for entry in due:
            existing = schedule_run_repository.get_by_idempotency_key(db, entry.idempotency_key)
            if existing is not None and existing.status == "draft_created":
                skipped += 1
                results.append({**self.mask_run(existing), "outcome": "skipped_duplicate"})
                continue
            run = existing or schedule_run_repository.create_run(
                db,
                account_id=account_id,
                project_id=project_id,
                platform_key=entry.platform,
                publishing_plan_id=entry.plan.id,
                schedule_key=entry.idempotency_key,
                run_date=entry.run_date,
                planned_time=entry.planned_time,
                status="planned",
                idempotency_key=entry.idempotency_key,
                run_metadata={"category_id": entry.plan.category_id, "mode": entry.plan.mode},
            )
            self._audit_run(db, ACTION_SCHEDULE_RUN_STARTED, run)
            entry_result = self._process_entry(db, account_id, project_id, entry, run)
            results.append(entry_result)
            if run.status == "draft_created":
                created += 1
            if entry_result.get("topic_decision_created"):
                topic_decisions_created += 1
            if entry_result.get("topic_decision_low_confidence"):
                low_confidence_decisions += 1
            if entry_result.get("media_decision_created"):
                media_decisions_created += 1
            if entry_result.get("media_decision_low_confidence"):
                low_confidence_media_decisions += 1
            if entry_result.get("media_decision_no_media"):
                no_media_decisions += 1
        return {
            "dry_run": False,
            "run_date": run_date,
            "due_count": len(due),
            "created": created,
            "skipped": skipped,
            "entries": results,
            "live_calls": False,
            # v0.4.4: автовыбор темы (worker агрегирует в TickResult).
            "topic_decisions_created": topic_decisions_created,
            "low_confidence_decisions": low_confidence_decisions,
            # v0.4.5: автовыбор медиа (worker агрегирует в TickResult).
            "media_decisions_created": media_decisions_created,
            "low_confidence_media_decisions": low_confidence_media_decisions,
            "no_media_decisions": no_media_decisions,
        }

    def _process_entry(
        self, db: Session, account_id: int, project_id: int, entry: _DueEntry, run: Any
    ) -> dict[str, Any]:
        # 1) Креды подключения (токен наружу не выходит).
        creds = self._connections.resolve_publish_credentials(db, project_id, entry.platform)
        if creds.source == "missing":
            schedule_run_repository.update_run(
                db,
                run,
                status="missing_credentials",
                error_message="Платформа не подключена в проекте. Заполните API/ID.",
            )
            self._audit_run(db, ACTION_SCHEDULE_RUN_MISSING_CREDENTIALS, run)
            return {**self.mask_run(run), "outcome": "missing_credentials"}

        # 2) Баланс.
        media_ids = self._select_media(db, project_id, entry.plan)
        units = self.estimate_schedule_run_units(entry.platform, len(media_ids))
        try:
            self._billing.ensure_balance(db, account_id, units)
        except InsufficientBalanceError:
            schedule_run_repository.update_run(
                db,
                run,
                status="insufficient_balance",
                units_estimated=units,
                error_message="Недостаточно units — пополните баланс.",
            )
            self._audit_run(db, ACTION_SCHEDULE_RUN_INSUFFICIENT_BALANCE, run, units=units)
            return {**self.mask_run(run), "outcome": "insufficient_balance"}

        # 2b) Автовыбор темы (v0.4.4): решение о теме/CTA/формате/медиа. Никогда не роняет
        # прогон и не публикует live; при выключенном флаге — обычный CRM-драфт.
        decision = self._select_topic_decision(db, project_id, entry, run)
        # 2c) Автовыбор медиа (v0.4.5): media strategy + конкретные медиа по теме/тегам/
        # платформе/обучению. Никогда не роняет прогон; при выключенном флаге — обычный подбор.
        media_decision = self._select_media_decision(db, project_id, entry, run, decision)

        # 3) Создание draft + publication (без live-публикации).
        try:
            post = self.build_post_for_schedule(db, entry, media_ids, decision, media_decision)
            pub = post_publication_repository.create_publication(
                db,
                PostPublicationCreate(
                    post_id=post.id,
                    project_id=project_id,
                    platform=entry.platform,
                    target_id=creds.external_id,
                    status="scheduled",
                    scheduled_at=self._due_datetime(entry.run_date, entry.planned_time),
                ),
            )
        except Exception as exc:  # noqa: BLE001 — ошибка создания не должна ронять весь run
            schedule_run_repository.mark_failed(
                db, run, f"draft build failed: {type(exc).__name__}"
            )
            # Не оставляем решение висеть в 'selected' — помечаем failed (без секретов).
            if decision is not None and decision.get("id") is not None:
                with contextlib.suppress(Exception):
                    self._topic_decision_svc().mark_decision_failed(
                        db, decision["id"], f"draft build failed: {type(exc).__name__}"
                    )
            if media_decision is not None and media_decision.get("id") is not None:
                with contextlib.suppress(Exception):
                    self._media_decision_svc().mark_decision_failed(
                        db, media_decision["id"], f"draft build failed: {type(exc).__name__}"
                    )
            self._audit_run(db, ACTION_SCHEDULE_RUN_FAILED, run)
            return {**self.mask_run(run), "outcome": "failed"}

        # 3b) Скоринг контента + снимок обучения (для semi_auto и full_auto).
        automation_mode = getattr(entry.plan, "automation_mode", AUTOMATION_SEMI_AUTO) or (
            AUTOMATION_SEMI_AUTO
        )
        scoring = self._score_and_annotate(db, project_id, entry, run, post)

        # 4) Списание units (идемпотентно, ровно один раз).
        entry_ledger = self._billing.debit_for_action(
            db,
            account_id,
            units=units,
            usage_type=USAGE_SCHEDULE_DRAFT,
            idempotency_key=f"{entry.idempotency_key}-debit",
            project_id=project_id,
            post_id=post.id,
            metadata={"plan_id": entry.plan.id, "platform": entry.platform},
        )
        charged = units if entry_ledger is not None else 0
        schedule_run_repository.update_run(db, run, units_estimated=units)
        schedule_run_repository.mark_draft_created(db, run, post.id, pub.id, charged)
        self._audit_run(db, ACTION_SCHEDULE_RUN_DRAFT_CREATED, run, units=charged)

        outcome: dict[str, Any] = {"outcome": "draft_created", "post_id": post.id}
        # Привязать решение о теме к прогону/посту (+ счётчики для worker/TickResult).
        if decision is not None:
            self._link_topic_decision(db, decision, run, post.id)
            outcome["topic_decision_created"] = True
            outcome["topic_decision_id"] = decision.get("id")
            outcome["topic_decision_low_confidence"] = "low_confidence" in (
                decision.get("risk_flags") or []
            )
        # Привязать решение о медиа к прогону/посту (+ счётчики для worker/TickResult).
        if media_decision is not None:
            self._link_media_decision(db, media_decision, run, post.id)
            outcome["media_decision_created"] = True
            outcome["media_decision_id"] = media_decision.get("id")
            outcome["media_decision_low_confidence"] = "low_confidence" in (
                media_decision.get("risk_flags") or []
            )
            outcome["media_decision_no_media"] = media_decision.get(
                "selected_strategy"
            ) == "no_media_available" or "no_media" in (media_decision.get("risk_flags") or [])
        # 5) Полностью автоматический режим: попытка авто-публикации под safety gates.
        if automation_mode == AUTOMATION_FULL_AUTO and getattr(
            entry.plan, "auto_publish_enabled", False
        ):
            reason = self._attempt_auto_publish(
                db, account_id, project_id, entry, run, post, scoring
            )
            outcome["auto_publish_attempted"] = True
            outcome["auto_publish_blocked_reason"] = reason
            outcome["auto_published"] = reason is None
        return {**self.mask_run(run), **outcome}

    # ------------------------------------------------------------------ #
    # Построение поста и медиа                                            #
    # ------------------------------------------------------------------ #

    def build_post_for_schedule(
        self,
        db: Session,
        entry: _DueEntry,
        media_ids: list[int],
        decision: dict[str, Any] | None = None,
        media_decision: dict[str, Any] | None = None,
    ) -> Post:
        """Создать draft/needs_review пост по due-слоту (без AI/сети, без live).

        При наличии ``decision`` (v0.4.4) тема/CTA/медиа-стратегия берутся из него, иначе —
        из CRM-категории (обратная совместимость). При наличии ``media_decision`` (v0.4.5)
        конкретные медиа/стратегия берутся из него (learning-driven подбор медиа).
        """
        category = crm_repo.get_category_by_id(db, entry.plan.category_id)
        title = (category.title if category is not None else None) or "Публикация по расписанию"
        cta = (category.cta if category is not None else "") or ""
        tag = ""
        if category is not None and category.media_tags:
            tag = str(category.media_tags[0])
        # Автовыбор темы: тема/CTA перекрывают CRM-дефолт (пост остаётся needs_review).
        if decision is not None:
            if str(decision.get("selected_topic") or "").strip():
                title = str(decision["selected_topic"]).strip()
            if decision.get("selected_cta"):
                cta = str(decision["selected_cta"])
        # Автовыбор медиа: конкретные media asset id из решения перекрывают базовый подбор.
        effective_media_ids = media_ids
        if media_decision is not None and media_decision.get("selected_media_asset_ids"):
            effective_media_ids = [
                int(mid) for mid in media_decision["selected_media_asset_ids"] if mid is not None
            ]
        elif media_decision is not None and media_decision.get("selected_strategy") in (
            "text_only",
            "no_media_available",
        ):
            effective_media_ids = []
        text = f"[Черновик расписания] {title}. {cta}".strip()
        notes: dict[str, Any] = {
            "source": "schedule_automation",
            "plan_id": entry.plan.id,
            "category_id": entry.plan.category_id,
            "media_asset_ids": effective_media_ids,
            "primary_tag": tag,
            "live": False,
        }
        if decision is not None:
            notes.update(
                {
                    "schedule_topic_decision_id": decision.get("id"),
                    "selected_topic": decision.get("selected_topic"),
                    "selected_cta": decision.get("selected_cta"),
                    "selected_format": decision.get("selected_format"),
                    "selected_media_strategy": decision.get("selected_media_strategy"),
                    "topic_decision_confidence": decision.get("confidence_score"),
                    "topic_decision_reasons": (decision.get("reasons") or [])[:8],
                    "topic_decision_source_signals": (decision.get("source_signals") or [])[:8],
                    "topic_decision_risk_flags": (decision.get("risk_flags") or [])[:8],
                    "topic_decision_source": decision.get("decision_source"),
                }
            )
        # v0.4.5: media decision перекрывает media-стратегию/медиа темы (реальный подбор).
        if media_decision is not None:
            notes.update(
                {
                    "schedule_media_decision_id": media_decision.get("id"),
                    "selected_media_asset_ids": effective_media_ids,
                    "selected_media_tags": (media_decision.get("selected_media_tags") or [])[:12],
                    "selected_media_strategy": media_decision.get("selected_strategy"),
                    "media_decision_confidence": media_decision.get("confidence_score"),
                    "media_decision_reasons": (media_decision.get("reasons") or [])[:8],
                    "media_decision_source_signals": (media_decision.get("source_signals") or [])[
                        :8
                    ],
                    "media_decision_risk_flags": (media_decision.get("risk_flags") or [])[:8],
                    "media_decision_source": media_decision.get("decision_source"),
                    "media_quality_summary": media_decision.get("media_quality_summary") or {},
                    "media_diversity_summary": media_decision.get("media_diversity_summary") or {},
                    "media_curation_summary": media_decision.get("media_curation_summary") or {},
                }
            )
        if not effective_media_ids:
            notes["warning"] = "no_media_text_only"
        # Instagram требует public image_url при наличии изображений (решение о медиа знает точно).
        if media_decision is not None:
            notes["needs_public_image_url"] = bool(media_decision.get("needs_public_image_url"))
        elif entry.platform == "instagram" and effective_media_ids:
            notes["needs_public_image_url"] = True
        # Текст пишем в поле платформы (по умолчанию — vk_text).
        return post_repository.create_post(
            db,
            PostCreate(
                project_id=entry.plan.project_id,
                title=title,
                status="needs_review",
                hashtags=[tag] if tag else [],
                media_asset_id=effective_media_ids[0] if effective_media_ids else None,
                scheduled_at=self._due_datetime(entry.run_date, entry.planned_time),
                generation_notes=notes,
                telegram_text=text if entry.platform == "telegram" else None,
                instagram_text=text if entry.platform == "instagram" else None,
                vk_text=text if entry.platform not in ("telegram", "instagram") else None,
            ),
        )

    @staticmethod
    def _select_media(db: Session, project_id: int, plan: CrmPublishingPlan) -> list[int]:
        """Подобрать одобренное медиа проекта (по тегам категории, best-effort)."""
        assets = [
            a
            for a in media_asset_repository.list_media_assets_by_project(db, project_id)
            if a.status == "approved"
        ]
        if not assets:
            return []
        category = crm_repo.get_category_by_id(db, plan.category_id)
        tags = set(category.media_tags or []) if category is not None else set()
        if tags:
            for asset in assets:
                values: set[str] = set()
                for value in (asset.tags or {}).values():
                    if isinstance(value, list):
                        values.update(str(v) for v in value)
                if tags & values:
                    return [asset.id]
        return [assets[0].id]

    @staticmethod
    def _due_datetime(run_date: str, planned_time: str) -> datetime:
        try:
            return datetime.fromisoformat(f"{run_date}T{planned_time}").replace(tzinfo=UTC)
        except ValueError:
            return datetime.fromisoformat(f"{run_date}T00:00").replace(tzinfo=UTC)

    # ------------------------------------------------------------------ #
    # История прогонов                                                   #
    # ------------------------------------------------------------------ #

    def list_runs(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """История прогонов проекта (с фильтром платформы/статуса)."""
        if platform_key:
            runs = schedule_run_repository.list_for_platform(db, project_id, platform_key, limit)
        else:
            runs = schedule_run_repository.list_for_project(db, project_id, limit)
        rows = [self.mask_run(r) for r in runs]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    def get_run(self, db: Session, project_id: int, run_id: int) -> dict[str, Any] | None:
        """Один прогон проекта (или None). Чужой проект — None."""
        run = schedule_run_repository.get_by_id(db, run_id)
        if run is None or run.project_id != project_id:
            return None
        return self.mask_run(run)

    @staticmethod
    def mask_run(run: Any) -> dict[str, Any]:
        """Безопасное представление прогона (без секретов)."""
        return {
            "id": run.id,
            "project_id": run.project_id,
            "platform_key": run.platform_key,
            "plan_id": run.publishing_plan_id,
            "run_date": run.run_date,
            "planned_time": run.planned_time,
            "status": run.status,
            "post_id": run.post_id,
            "publication_id": run.publication_id,
            "units_estimated": run.units_estimated,
            "units_charged": run.units_charged,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            # Автоматизация/обучение (v0.4.0).
            "automation_mode": getattr(run, "automation_mode", None),
            "auto_publish_attempted": bool(getattr(run, "auto_publish_attempted", False)),
            "auto_publish_blocked_reason": getattr(run, "auto_publish_blocked_reason", None),
            "quality_score": getattr(run, "quality_score", None),
            "safety_score": getattr(run, "safety_score", None),
            "learning_profile_version": getattr(run, "learning_profile_version", None),
        }

    # ------------------------------------------------------------------ #
    # Скоринг контента и полностью автоматический режим (v0.4.0)          #
    # ------------------------------------------------------------------ #

    def _score_and_annotate(
        self, db: Session, project_id: int, entry: _DueEntry, run: Any, post: Post
    ) -> dict[str, Any]:
        """Оценить пост и сохранить снимок обучения в ScheduleRun + generation_notes.

        Никогда не роняет прогон: при ошибке скоринга возвращает нейтральные значения.
        """
        automation_mode = getattr(entry.plan, "automation_mode", AUTOMATION_SEMI_AUTO) or (
            AUTOMATION_SEMI_AUTO
        )
        try:
            scoring = self._learning_service().score_content_candidate(
                db, project_id, entry.platform, post
            )
        except Exception:  # noqa: BLE001 — скоринг не должен ронять прогон расписания
            with contextlib.suppress(Exception):
                db.rollback()
            scoring = {
                "quality_score": 0,
                "predicted_engagement_score": 0,
                "fit_score": 0,
                "learning_reasons": [],
                "warnings": [],
                "recommended_changes": [],
                "profile_version": 0,
            }
        quality = int(scoring.get("quality_score", 0) or 0)
        warnings = list(scoring.get("warnings", []) or [])
        safety = max(0, 100 - min(100, len(warnings) * 15))
        profile_version = int(scoring.get("profile_version", 0) or 0)

        notes = dict(post.generation_notes or {})
        notes.update(
            {
                "automation_mode": automation_mode,
                "quality_score": quality,
                "predicted_engagement_score": scoring.get("predicted_engagement_score"),
                "learning_reasons": (scoring.get("learning_reasons") or [])[:8],
                "safety_warnings": warnings[:8],
                "learning_profile_version": profile_version,
                "recommended_changes": (scoring.get("recommended_changes") or [])[:8],
            }
        )
        post.generation_notes = notes
        db.commit()
        db.refresh(post)

        schedule_run_repository.update_run(
            db,
            run,
            automation_mode=automation_mode,
            quality_score=quality,
            safety_score=safety,
            learning_profile_version=profile_version,
        )
        return {**scoring, "quality_score": quality, "safety_score": safety}

    def _attempt_auto_publish(
        self,
        db: Session,
        account_id: int,
        project_id: int,
        entry: _DueEntry,
        run: Any,
        post: Post,
        scoring: dict[str, Any],
    ) -> str | None:
        """Попытка авто-публикации под safety gates. Возвращает причину блокировки или None.

        Gates (все обязательны): порог качества → первое ревью → баланс → live-разрешения
        площадки. Live-отправка происходит ТОЛЬКО если все гейты пройдены; иначе draft
        остаётся needs_review и пишется понятная причина.
        """
        from app.repositories import post_feedback_repository

        plan = entry.plan
        quality = int(scoring.get("quality_score", 0) or 0)

        # 1) Порог качества.
        if quality < getattr(plan, "min_quality_score_for_auto", 70):
            return self._block_auto(db, run, post, project_id, "quality_score_below_threshold")
        # 2) Требуется хотя бы одно одобрение клиента до первой авто-публикации.
        if getattr(plan, "require_review_before_first_auto", True):
            approvals = post_feedback_repository.count_for_project(
                db, project_id, ("approved", "auto_published")
            )
            if approvals == 0:
                return self._block_auto(db, run, post, project_id, "needs_first_review")
        # 3) Баланс под платную авто-публикацию.
        autopub_units = self._billing.estimate_action_cost(USAGE_AUTO_PUBLISH_ACTION)
        try:
            self._billing.ensure_balance(db, account_id, autopub_units)
        except InsufficientBalanceError:
            return self._block_auto(db, run, post, project_id, "insufficient_balance")
        # 4) Live-разрешения площадки (live-флаг + креды + таргет). Без сети.
        try:
            preview = self._publication_service().preview_publication(db, post.id)
            sendable = [item for item in preview.items if item.would_send]
        except Exception:  # noqa: BLE001 — сбой превью не должен ронять прогон
            with contextlib.suppress(Exception):
                db.rollback()
            sendable = []
        if not sendable:
            return self._block_auto(db, run, post, project_id, "live_disabled")

        # --- Все гейты пройдены: одобряем и публикуем ---
        from app.schemas.post_publication import PostPublishRequest
        from app.schemas.post_review import PostReviewDecisionRequest

        with contextlib.suppress(Exception):
            self._review_service().approve_post(
                db, post.id, PostReviewDecisionRequest(actor_role="bot")
            )
        send_platforms = [item.platform for item in sendable]
        result = self._publication_service().publish_post(
            db, post.id, PostPublishRequest(platforms=send_platforms)
        )
        published_ok = (
            int(getattr(result, "published_count", 0)) > 0
            and int(getattr(result, "failed_count", 0)) == 0
        )
        if not published_ok:
            return self._block_auto(db, run, post, project_id, "publish_failed")

        ledger = self._billing.debit_for_action(
            db,
            account_id,
            units=autopub_units,
            usage_type=USAGE_AUTO_PUBLISH_ACTION,
            idempotency_key=f"{entry.idempotency_key}-autopub",
            project_id=project_id,
            post_id=post.id,
            metadata={"platforms": send_platforms},
        )
        charged = autopub_units if ledger is not None else 0
        schedule_run_repository.update_run(
            db,
            run,
            auto_publish_attempted=True,
            auto_publish_blocked_reason=None,
            units_charged=(run.units_charged or 0) + charged,
        )
        with contextlib.suppress(Exception):
            self._learning_service().record_review_feedback(
                db, post.id, "auto_published", platform_key=entry.platform
            )
        self._audit_run(db, ACTION_AUTOMATION_AUTO_PUBLISH_SUCCEEDED, run, units=charged)
        return None

    def _block_auto(self, db: Session, run: Any, post: Post, project_id: int, reason: str) -> str:
        """Заблокировать авто-публикацию: draft остаётся needs_review + причина + аудит."""
        schedule_run_repository.update_run(
            db, run, auto_publish_attempted=True, auto_publish_blocked_reason=reason
        )
        with contextlib.suppress(Exception):
            from app.repositories import post_feedback_repository

            post_feedback_repository.create_event(
                db,
                account_id=run.account_id,
                project_id=project_id,
                post_id=post.id,
                platform_key=run.platform_key,
                event_type="auto_blocked",
                reason_tags=[reason],
                event_metadata={"reason": reason},
            )
        self._audit_run(db, ACTION_AUTOMATION_AUTO_PUBLISH_BLOCKED, run)
        return reason

    def _learning_service(self) -> Any:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _publication_service(self) -> Any:
        if self._publication is None:
            from app.api.deps import (
                get_post_publication_service,
                get_publication_platform_registry,
            )

            self._publication = get_post_publication_service(get_publication_platform_registry())
        return self._publication

    def _review_service(self) -> Any:
        if self._review is None:
            from app.services.post_review_service import PostReviewService

            self._review = PostReviewService()
        return self._review

    # ------------------------------------------------------------------ #
    # Автовыбор темы (v0.4.4, без live-публикации)                        #
    # ------------------------------------------------------------------ #

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _topic_selection_active(self) -> bool:
        """Пишет ли решения автовыбор темы (worker включён И НЕ dry-run). По умолчанию false.

        При выключенном флаге или dry-run — обычный CRM-драфт (обратная совместимость).
        """
        s = self._resolve_settings()
        return bool(
            s.auto_topic_selection_worker_enabled_effective and not s.auto_topic_selection_dry_run
        )

    def _topic_selection_preview_active(self) -> bool:
        """Доступен ли read-only preview решения (worker включён; dry-run не важен)."""
        return bool(self._resolve_settings().auto_topic_selection_worker_enabled_effective)

    def _topic_decision_svc(self) -> Any:
        if self._topic_decision is None:
            from app.services.schedule_topic_decision_service import (
                ScheduleTopicDecisionService,
            )

            self._topic_decision = ScheduleTopicDecisionService(settings=self._settings)
        return self._topic_decision

    def _select_topic_decision(
        self, db: Session, project_id: int, entry: _DueEntry, run: Any
    ) -> dict[str, Any] | None:
        """Выбрать тему для слота (запись решения). None — если выключено или ошибка.

        Никогда не роняет прогон: при сбое откатываемся к обычному CRM-драфту.
        """
        if not self._topic_selection_active():
            return None
        automation_mode = getattr(entry.plan, "automation_mode", AUTOMATION_SEMI_AUTO) or (
            AUTOMATION_SEMI_AUTO
        )
        decision_mode = (
            AUTOMATION_FULL_AUTO
            if automation_mode == AUTOMATION_FULL_AUTO
            else AUTOMATION_SEMI_AUTO
        )
        try:
            result: dict[str, Any] = self._topic_decision_svc().create_decision_for_plan(
                db,
                project_id,
                entry.platform,
                plan_id=entry.plan.id,
                decision_mode=decision_mode,
                schedule_run_id=run.id,
            )
        except Exception:  # noqa: BLE001 — автовыбор не должен ронять прогон расписания
            with contextlib.suppress(Exception):
                db.rollback()
            return None
        return result

    def _link_topic_decision(
        self, db: Session, decision: dict[str, Any], run: Any, post_id: int
    ) -> None:
        """Пометить решение как использованное для драфта и записать в run_metadata."""
        decision_id = decision.get("id")
        with contextlib.suppress(Exception):
            if decision_id is not None:
                self._topic_decision_svc().mark_decision_draft_created(
                    db, decision_id, run.id, post_id
                )
            meta = dict(run.run_metadata or {})
            meta["topic_decision"] = {
                "id": decision_id,
                "selected_topic": decision.get("selected_topic"),
                "decision_source": decision.get("decision_source"),
                "confidence_score": decision.get("confidence_score"),
                "risk_flags": (decision.get("risk_flags") or [])[:8],
            }
            schedule_run_repository.update_run(db, run, run_metadata=meta)

    # ------------------------------------------------------------------ #
    # Автовыбор медиа (v0.4.5, без live-публикации)                       #
    # ------------------------------------------------------------------ #

    def _media_selection_active(self) -> bool:
        """Пишет ли решения автовыбор медиа (worker включён И НЕ dry-run). По умолчанию false.

        При выключенном флаге или dry-run — обычный подбор медиа (обратная совместимость).
        """
        s = self._resolve_settings()
        return bool(
            s.auto_media_selection_worker_enabled_effective and not s.auto_media_selection_dry_run
        )

    def _media_selection_preview_active(self) -> bool:
        """Доступен ли read-only preview решения о медиа (worker включён; dry-run не важен)."""
        return bool(self._resolve_settings().auto_media_selection_worker_enabled_effective)

    def _media_decision_svc(self) -> Any:
        if self._media_decision is None:
            from app.services.schedule_media_decision_service import (
                ScheduleMediaDecisionService,
            )

            self._media_decision = ScheduleMediaDecisionService(settings=self._settings)
        return self._media_decision

    def _preview_media_decisions(self, db: Session, project_id: int, due: list[_DueEntry]) -> int:
        """Число слотов, для которых worker предпросмотрит медиа (без записи). 0 если выключено."""
        if not self._media_selection_preview_active():
            return 0
        count = 0
        for entry in due:
            try:
                self._media_decision_svc().preview_media_decision_for_plan(
                    db, project_id, entry.platform, plan_id=entry.plan.id
                )
                count += 1
            except Exception:  # noqa: BLE001 — превью не должно ронять preview расписания
                with contextlib.suppress(Exception):
                    db.rollback()
        return count

    def _select_media_decision(
        self,
        db: Session,
        project_id: int,
        entry: _DueEntry,
        run: Any,
        topic_decision: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Выбрать медиа для слота (запись решения). None — если выключено или ошибка.

        Никогда не роняет прогон: при сбое откатываемся к обычному подбору медиа.
        """
        if not self._media_selection_active():
            return None
        topic_decision_id = topic_decision.get("id") if topic_decision else None
        try:
            result: dict[str, Any] = self._media_decision_svc().create_media_decision_for_plan(
                db,
                project_id,
                entry.platform,
                plan_id=entry.plan.id,
                topic_decision_id=topic_decision_id,
                schedule_run_id=run.id,
            )
        except Exception:  # noqa: BLE001 — автовыбор не должен ронять прогон расписания
            with contextlib.suppress(Exception):
                db.rollback()
            return None
        return result

    def _link_media_decision(
        self, db: Session, decision: dict[str, Any], run: Any, post_id: int
    ) -> None:
        """Пометить решение о медиа как использованное для драфта и записать в run_metadata."""
        decision_id = decision.get("id")
        with contextlib.suppress(Exception):
            if decision_id is not None:
                self._media_decision_svc().mark_decision_applied_to_draft(
                    db, decision_id, run.id, post_id
                )
            meta = dict(run.run_metadata or {})
            meta["media_decision"] = {
                "id": decision_id,
                "selected_strategy": decision.get("selected_strategy"),
                "selected_media_count": decision.get("selected_media_count"),
                "decision_source": decision.get("decision_source"),
                "confidence_score": decision.get("confidence_score"),
                "needs_public_image_url": bool(decision.get("needs_public_image_url")),
                "risk_flags": (decision.get("risk_flags") or [])[:8],
            }
            schedule_run_repository.update_run(db, run, run_metadata=meta)

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _verify_ownership(self, db: Session, account_id: int, project_id: int) -> None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ScheduleAutomationError(f"Проект id={project_id} не найден")
        if project.account_id is not None and project.account_id != account_id:
            raise ScheduleAutomationError(
                f"Проект id={project_id} не принадлежит аккаунту id={account_id}"
            )

    def _audit_run(self, db: Session, action: str, run: Any, units: int = 0) -> None:
        self._audit.record(
            db,
            action,
            account_id=run.account_id,
            project_id=run.project_id,
            entity_type="schedule_run",
            entity_id=run.id,
            metadata={
                "platform_key": run.platform_key,
                "plan_id": run.publishing_plan_id,
                "run_id": run.id,
                "post_id": run.post_id,
                "publication_id": run.publication_id,
                "status": run.status,
                "units": units,
            },
        )


def get_schedule_automation_service() -> ScheduleAutomationService:
    """DI-фабрика движка автоматизации расписаний."""
    return ScheduleAutomationService()
