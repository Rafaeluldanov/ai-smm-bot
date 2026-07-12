"""Фоновый scheduler-worker: периодически обрабатывает due-задачи расписаний.

Worker НЕ делает live-публикацию — он переиспользует :class:`ScheduleAutomationService`
(создаёт draft/needs_review, списывает units за успех, пишет `ScheduleRun`). Старый
``publish-due`` и живые вызовы платформ НЕ используются.

Безопасность:
- по умолчанию выключен (`SCHEDULER_WORKER_ENABLED=false`) и в dry-run;
- один активный worker через DB-lease (без дублей);
- секреты/токены не печатаются и не попадают в результат;
- в production запускается ОТДЕЛЬНЫМ процессом (не внутри web).
"""

from __future__ import annotations

import os
import secrets
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.repositories import project_repository, scheduler_worker_repository
from app.services.audit_log_service import (
    ACTION_WORKER_DUPLICATE_CLUSTER_CREATED,
    ACTION_WORKER_DUPLICATE_CLUSTER_PREVIEWED,
    ACTION_WORKER_LEASE_ACQUIRED,
    ACTION_WORKER_LEASE_SKIPPED,
    ACTION_WORKER_MEDIA_DECISION_CREATED,
    ACTION_WORKER_MEDIA_DECISION_FAILED,
    ACTION_WORKER_MEDIA_DECISION_PREVIEWED,
    ACTION_WORKER_MEDIA_DECISION_SKIPPED,
    ACTION_WORKER_MEDIA_FINGERPRINT_CREATED,
    ACTION_WORKER_MEDIA_FINGERPRINT_FAILED,
    ACTION_WORKER_MEDIA_FINGERPRINT_PREVIEWED,
    ACTION_WORKER_MEDIA_QUALITY_FAILED,
    ACTION_WORKER_MEDIA_QUALITY_PREVIEWED,
    ACTION_WORKER_MEDIA_QUALITY_SCORED,
    ACTION_WORKER_TARGET_PROCESSED,
    ACTION_WORKER_TICK_FAILED,
    ACTION_WORKER_TICK_FINISHED,
    ACTION_WORKER_TICK_STARTED,
    ACTION_WORKER_TOPIC_DECISION_CREATED,
    ACTION_WORKER_TOPIC_DECISION_FAILED,
    ACTION_WORKER_TOPIC_DECISION_PREVIEWED,
    ACTION_WORKER_TOPIC_DECISION_SKIPPED,
    AuditLogService,
)
from app.services.schedule_automation_service import ScheduleAutomationService

logger = get_logger("botfleet.scheduler")

LEASE_KEY = "scheduler-worker"


@dataclass(frozen=True)
class ScheduleWorkerTarget:
    """Цель обработки: (account, project, platform) с активной задачей расписания."""

    account_id: int
    project_id: int
    platform_key: str
    reason: str = "active_schedule_task"


@dataclass
class SchedulerWorkerTickResult:
    """Итог одного тика worker-а (без секретов)."""

    owner_id: str
    enabled: bool
    dry_run: bool
    lease_acquired: bool
    targets_scanned: int = 0
    targets_processed: int = 0
    drafts_created: int = 0
    skipped: int = 0
    failed: int = 0
    insufficient_balance: int = 0
    missing_credentials: int = 0
    schedule_runs_created: int = 0
    # Предложения экспериментов (v0.4.3). Worker может предлагать эксперименты/темы,
    # но НЕ публикует live.
    experiment_suggestions_enabled: bool = False
    experiment_suggestions_dry_run: bool = False
    experiment_suggestions_scanned: int = 0
    experiment_suggestions_created: int = 0
    experiment_suggestions_skipped: int = 0
    experiments_created: int = 0
    experiment_suggestion_errors: list[str] = field(default_factory=list)
    # Автовыбор темы (v0.4.4). Worker сам выбирает тему для слота, но НЕ публикует live.
    auto_topic_selection_enabled: bool = False
    auto_topic_selection_dry_run: bool = False
    topic_decisions_previewed: int = 0
    topic_decisions_created: int = 0
    low_confidence_decisions: int = 0
    topic_decision_errors: list[str] = field(default_factory=list)
    # Автовыбор медиа (v0.4.5). Worker сам выбирает media strategy/медиа, но НЕ публикует live.
    auto_media_selection_enabled: bool = False
    auto_media_selection_dry_run: bool = False
    media_decisions_previewed: int = 0
    media_decisions_created: int = 0
    low_confidence_media_decisions: int = 0
    no_media_decisions: int = 0
    media_decision_errors: list[str] = field(default_factory=list)
    # Оценка качества медиа (v0.4.6). Worker оценивает медиатеку, но НЕ публикует live.
    media_quality_scoring_enabled: bool = False
    media_quality_scoring_dry_run: bool = False
    media_quality_assets_scanned: int = 0
    media_quality_snapshots_created: int = 0
    media_quality_weak_count: int = 0
    media_quality_duplicate_count: int = 0
    media_quality_errors: list[str] = field(default_factory=list)
    # Fingerprint и дедупликация медиа (v0.4.7). Worker считает хэши/кластеры, но НЕ публикует live.
    media_fingerprinting_enabled: bool = False
    media_fingerprinting_dry_run: bool = False
    media_fingerprints_previewed: int = 0
    media_fingerprints_created: int = 0
    duplicate_clusters_previewed: int = 0
    duplicate_clusters_created: int = 0
    duplicate_cluster_errors: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SchedulerWorkerService:
    """Фоновый обработчик due-задач расписаний (safe, без live-публикации)."""

    def __init__(
        self,
        settings: Settings | None = None,
        automation_service: ScheduleAutomationService | None = None,
        audit_service: AuditLogService | None = None,
        suggestion_service: Any | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        # Пробрасываем settings в движок автоматизации, чтобы автовыбор темы (v0.4.4)
        # управлялся теми же флагами, что и worker.
        self._automation = automation_service or ScheduleAutomationService(settings=self._settings)
        self._audit = audit_service or AuditLogService(self._settings)
        # v0.4.3: сервис предложений экспериментов (ленивое построение; без live).
        self._suggestions = suggestion_service
        # v0.4.6: сервис оценки качества медиа (ленивое построение; без внешнего AI/live).
        self._quality: Any | None = None
        # v0.4.7: сервисы fingerprint/дедупликации медиа (ленивые; без внешнего AI/сети/live).
        self._fingerprint: Any | None = None
        self._similarity: Any | None = None

    # ------------------------------------------------------------------ #
    # Идентификация                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_owner_id() -> str:
        """Идентификатор владельца lease: host:pid:suffix (без секретов)."""
        try:
            host = socket.gethostname()
        except OSError:
            host = "host"
        return f"{host}:{os.getpid()}:{secrets.token_hex(3)}"

    def _effective_dry_run(self, dry_run: bool | None) -> bool:
        """dry-run по умолчанию из настроек; create_drafts=false форсит dry-run."""
        base = self._settings.scheduler_worker_dry_run if dry_run is None else dry_run
        if not self._settings.scheduler_worker_create_drafts:
            return True
        return bool(base)

    # ------------------------------------------------------------------ #
    # Обнаружение целей                                                  #
    # ------------------------------------------------------------------ #

    def discover_due_targets(
        self,
        db: Session,
        platform_key: str | None = None,
        account_id: int | None = None,
        project_id: int | None = None,
    ) -> list[ScheduleWorkerTarget]:
        """Найти цели (account, project, platform) c активными задачами расписаний."""
        s = self._settings
        platform_allow = set(s.scheduler_worker_platform_allowlist_list)
        account_allow = set(s.scheduler_worker_account_allowlist_list)
        targets: list[ScheduleWorkerTarget] = []
        seen: set[tuple[int, str]] = set()
        max_projects = max(1, s.scheduler_worker_max_projects_per_tick)
        batch = max(1, s.scheduler_worker_batch_size)
        projects = project_repository.list_projects(db, active_only=True)[:max_projects]
        for project in projects:
            if project.account_id is None:
                continue  # без аккаунта нельзя проверить владение/биллинг
            if project_id is not None and project.id != project_id:
                continue
            if account_id is not None and project.account_id != account_id:
                continue
            if account_allow and project.account_id not in account_allow:
                continue
            for task in self._automation.list_schedule_tasks(db, project.id):
                platform = task["platform_key"]
                if platform_key and platform != platform_key:
                    continue
                if platform_allow and platform not in platform_allow:
                    continue
                key = (project.id, platform)
                if key in seen:
                    continue
                seen.add(key)
                targets.append(
                    ScheduleWorkerTarget(
                        account_id=project.account_id, project_id=project.id, platform_key=platform
                    )
                )
                if len(targets) >= batch:
                    return targets
        return targets

    # ------------------------------------------------------------------ #
    # Обработка одной цели                                               #
    # ------------------------------------------------------------------ #

    def process_target(
        self,
        db: Session,
        target: ScheduleWorkerTarget,
        now: datetime,
        dry_run: bool,
    ) -> dict[str, int]:
        """Обработать одну цель через ScheduleAutomationService (без live-публикации)."""
        deltas = {
            "drafts_created": 0,
            "skipped": 0,
            "failed": 0,
            "insufficient_balance": 0,
            "missing_credentials": 0,
            "schedule_runs_created": 0,
            "topic_decisions_previewed": 0,
            "topic_decisions_created": 0,
            "low_confidence_decisions": 0,
            "media_decisions_previewed": 0,
            "media_decisions_created": 0,
            "low_confidence_media_decisions": 0,
            "no_media_decisions": 0,
        }
        if dry_run:
            result = self._automation.run_due_dry(
                db, target.account_id, target.project_id, now=now, platform_key=target.platform_key
            )
            deltas["topic_decisions_previewed"] = int(result.get("topic_decisions_previewed", 0))
            deltas["media_decisions_previewed"] = int(result.get("media_decisions_previewed", 0))
            for entry in result.get("entries", []):
                outcome = entry.get("outcome")
                if outcome == "missing_credentials":
                    deltas["missing_credentials"] += 1
                elif outcome == "insufficient_balance":
                    deltas["insufficient_balance"] += 1
                elif outcome == "already_done":
                    deltas["skipped"] += 1
            return deltas

        result = self._automation.run_due(
            db, target.account_id, target.project_id, now=now, platform_key=target.platform_key
        )
        deltas["drafts_created"] = int(result.get("created", 0))
        deltas["skipped"] = int(result.get("skipped", 0))
        deltas["topic_decisions_created"] = int(result.get("topic_decisions_created", 0))
        deltas["low_confidence_decisions"] = int(result.get("low_confidence_decisions", 0))
        deltas["media_decisions_created"] = int(result.get("media_decisions_created", 0))
        deltas["low_confidence_media_decisions"] = int(
            result.get("low_confidence_media_decisions", 0)
        )
        deltas["no_media_decisions"] = int(result.get("no_media_decisions", 0))
        for entry in result.get("entries", []):
            outcome = entry.get("outcome") or entry.get("status")
            if outcome == "missing_credentials":
                deltas["missing_credentials"] += 1
                deltas["schedule_runs_created"] += 1
            elif outcome == "insufficient_balance":
                deltas["insufficient_balance"] += 1
                deltas["schedule_runs_created"] += 1
            elif outcome == "failed":
                deltas["failed"] += 1
                deltas["schedule_runs_created"] += 1
            elif outcome == "draft_created":
                deltas["schedule_runs_created"] += 1
        self._audit.record(
            db,
            ACTION_WORKER_TARGET_PROCESSED,
            account_id=target.account_id,
            project_id=target.project_id,
            entity_type="scheduler_target",
            metadata={"platform_key": target.platform_key, "dry_run": False, **deltas},
        )
        return deltas

    # ------------------------------------------------------------------ #
    # Один тик                                                           #
    # ------------------------------------------------------------------ #

    def tick(
        self,
        db: Session,
        owner_id: str | None = None,
        now: datetime | None = None,
        dry_run: bool | None = None,
        force: bool = False,
        platform_key: str | None = None,
        account_id: int | None = None,
        project_id: int | None = None,
    ) -> SchedulerWorkerTickResult:
        """Один цикл: lease → обнаружение целей → обработка → release. Без live."""
        owner_id = owner_id or self.build_owner_id()
        now = now or datetime.now(UTC)
        effective_dry = self._effective_dry_run(dry_run)
        enabled = self._settings.scheduler_worker_enabled_effective
        result = SchedulerWorkerTickResult(
            owner_id=owner_id,
            enabled=enabled,
            dry_run=effective_dry,
            lease_acquired=False,
            started_at=now.isoformat(),
        )
        if not enabled and not force:
            result.finished_at = now.isoformat()
            result.errors.append("worker disabled (SCHEDULER_WORKER_ENABLED=false); use force")
            return result

        acquired = scheduler_worker_repository.acquire_lease(
            db,
            LEASE_KEY,
            owner_id,
            self._settings.scheduler_worker_lock_ttl_seconds,
            now=now,
            metadata={"host": _safe_host(), "pid": os.getpid()},
        )
        result.lease_acquired = acquired
        if not acquired:
            self._audit.record(
                db,
                ACTION_WORKER_LEASE_SKIPPED,
                entity_type="scheduler_worker",
                metadata={"owner_id": owner_id, "reason": "lease_held_by_other"},
            )
            result.finished_at = datetime.now(UTC).isoformat()
            result.errors.append("lease held by another worker")
            return result

        self._audit.record(
            db,
            ACTION_WORKER_LEASE_ACQUIRED,
            entity_type="scheduler_worker",
            metadata={"owner_id": owner_id, "dry_run": effective_dry},
        )
        self._audit.record(
            db,
            ACTION_WORKER_TICK_STARTED,
            entity_type="scheduler_worker",
            metadata={"owner_id": owner_id, "dry_run": effective_dry},
        )
        try:
            targets = self.discover_due_targets(
                db, platform_key=platform_key, account_id=account_id, project_id=project_id
            )
            result.targets_scanned = len(targets)
            for target in targets:
                scheduler_worker_repository.heartbeat_lease(
                    db,
                    LEASE_KEY,
                    owner_id,
                    self._settings.scheduler_worker_lock_ttl_seconds,
                    now=now,
                )
                try:
                    deltas = self.process_target(db, target, now, effective_dry)
                except Exception as exc:  # noqa: BLE001 — одна цель не роняет весь тик
                    result.failed += 1
                    result.errors.append(
                        f"target p{target.project_id}/{target.platform_key}: {type(exc).__name__}"
                    )
                    continue
                result.targets_processed += 1
                result.drafts_created += deltas["drafts_created"]
                result.skipped += deltas["skipped"]
                result.failed += deltas["failed"]
                result.insufficient_balance += deltas["insufficient_balance"]
                result.missing_credentials += deltas["missing_credentials"]
                result.schedule_runs_created += deltas["schedule_runs_created"]
                result.topic_decisions_previewed += deltas.get("topic_decisions_previewed", 0)
                result.topic_decisions_created += deltas.get("topic_decisions_created", 0)
                result.low_confidence_decisions += deltas.get("low_confidence_decisions", 0)
                result.media_decisions_previewed += deltas.get("media_decisions_previewed", 0)
                result.media_decisions_created += deltas.get("media_decisions_created", 0)
                result.low_confidence_media_decisions += deltas.get(
                    "low_confidence_media_decisions", 0
                )
                result.no_media_decisions += deltas.get("no_media_decisions", 0)
            # v0.4.3: предложения экспериментов по проектам (без live-публикации).
            self._process_experiment_suggestions(db, targets, owner_id, effective_dry, result)
            # v0.4.4: сводка автовыбора темы (решения создаются внутри run_due).
            self._annotate_topic_selection(db, owner_id, effective_dry, result)
            # v0.4.5: сводка автовыбора медиа (решения создаются внутри run_due).
            self._annotate_media_selection(db, owner_id, effective_dry, result)
            # v0.4.6: оценка качества медиатеки проектов (без внешнего AI/live).
            self._process_media_quality(db, targets, owner_id, effective_dry, result)
            # v0.4.7: fingerprint + кластеры дублей медиатеки (локально, без AI/сети/live).
            self._process_media_fingerprints(db, targets, owner_id, effective_dry, result)
        except Exception as exc:  # noqa: BLE001 — тик не роняет процесс
            result.errors.append(f"tick error: {type(exc).__name__}")
            self._audit.record(
                db,
                ACTION_WORKER_TICK_FAILED,
                entity_type="scheduler_worker",
                metadata={"owner_id": owner_id, "error": type(exc).__name__},
            )
        finally:
            scheduler_worker_repository.release_lease(db, LEASE_KEY, owner_id, now=now)
            result.finished_at = datetime.now(UTC).isoformat()
            self._audit.record(
                db,
                ACTION_WORKER_TICK_FINISHED,
                entity_type="scheduler_worker",
                metadata={
                    "owner_id": owner_id,
                    "dry_run": effective_dry,
                    "targets_scanned": result.targets_scanned,
                    "drafts_created": result.drafts_created,
                    "schedule_runs_created": result.schedule_runs_created,
                },
            )
        return result

    # ------------------------------------------------------------------ #
    # Автовыбор темы (v0.4.4, без live-публикации)                        #
    # ------------------------------------------------------------------ #

    def _annotate_topic_selection(
        self,
        db: Session,
        owner_id: str,
        schedule_dry_run: bool,
        result: SchedulerWorkerTickResult,
    ) -> None:
        """Проставить флаги автовыбора темы + аудит. Решения создаются внутри run_due.

        Управляется флагом AUTO_TOPIC_SELECTION_WORKER_ENABLED (выключен по умолчанию);
        dry-run = worker dry-run ИЛИ AUTO_TOPIC_SELECTION_DRY_RUN. Live-публикаций нет.
        """
        s = self._settings
        enabled = s.auto_topic_selection_worker_enabled_effective
        result.auto_topic_selection_enabled = enabled
        result.auto_topic_selection_dry_run = bool(
            schedule_dry_run or s.auto_topic_selection_dry_run
        )
        if not enabled:
            return
        action = (
            ACTION_WORKER_TOPIC_DECISION_PREVIEWED
            if result.auto_topic_selection_dry_run
            else ACTION_WORKER_TOPIC_DECISION_CREATED
        )
        base_meta = {
            "owner_id": owner_id,
            "dry_run": result.auto_topic_selection_dry_run,
            "topic_decisions_previewed": result.topic_decisions_previewed,
            "topic_decisions_created": result.topic_decisions_created,
            "low_confidence_decisions": result.low_confidence_decisions,
            "live_publish": False,
        }
        self._audit.record(db, action, entity_type="scheduler_worker", metadata=base_meta)
        # Отдельные события: ничего не создано (не dry) → skipped; были ошибки → failed.
        if not result.auto_topic_selection_dry_run and result.topic_decisions_created == 0:
            self._audit.record(
                db,
                ACTION_WORKER_TOPIC_DECISION_SKIPPED,
                entity_type="scheduler_worker",
                metadata=base_meta,
            )
        if result.topic_decision_errors:
            self._audit.record(
                db,
                ACTION_WORKER_TOPIC_DECISION_FAILED,
                entity_type="scheduler_worker",
                metadata={**base_meta, "errors": len(result.topic_decision_errors)},
            )

    # ------------------------------------------------------------------ #
    # Автовыбор медиа (v0.4.5, без live-публикации)                        #
    # ------------------------------------------------------------------ #

    def _annotate_media_selection(
        self,
        db: Session,
        owner_id: str,
        schedule_dry_run: bool,
        result: SchedulerWorkerTickResult,
    ) -> None:
        """Проставить флаги автовыбора медиа + аудит. Решения создаются внутри run_due.

        Управляется флагом AUTO_MEDIA_SELECTION_WORKER_ENABLED (выключен по умолчанию);
        dry-run = worker dry-run ИЛИ AUTO_MEDIA_SELECTION_DRY_RUN. Live-публикаций нет;
        публичные ссылки автоматически не создаются.
        """
        s = self._settings
        enabled = s.auto_media_selection_worker_enabled_effective
        result.auto_media_selection_enabled = enabled
        result.auto_media_selection_dry_run = bool(
            schedule_dry_run or s.auto_media_selection_dry_run
        )
        if not enabled:
            return
        action = (
            ACTION_WORKER_MEDIA_DECISION_PREVIEWED
            if result.auto_media_selection_dry_run
            else ACTION_WORKER_MEDIA_DECISION_CREATED
        )
        base_meta = {
            "owner_id": owner_id,
            "dry_run": result.auto_media_selection_dry_run,
            "media_decisions_previewed": result.media_decisions_previewed,
            "media_decisions_created": result.media_decisions_created,
            "low_confidence_media_decisions": result.low_confidence_media_decisions,
            "no_media_decisions": result.no_media_decisions,
            "live_publish": False,
        }
        self._audit.record(db, action, entity_type="scheduler_worker", metadata=base_meta)
        # Отдельные события: ничего не создано (не dry) → skipped; были ошибки → failed.
        if not result.auto_media_selection_dry_run and result.media_decisions_created == 0:
            self._audit.record(
                db,
                ACTION_WORKER_MEDIA_DECISION_SKIPPED,
                entity_type="scheduler_worker",
                metadata=base_meta,
            )
        if result.media_decision_errors:
            self._audit.record(
                db,
                ACTION_WORKER_MEDIA_DECISION_FAILED,
                entity_type="scheduler_worker",
                metadata={**base_meta, "errors": len(result.media_decision_errors)},
            )

    # ------------------------------------------------------------------ #
    # Оценка качества медиа (v0.4.6, без внешнего AI/live-публикации)      #
    # ------------------------------------------------------------------ #

    def _quality_svc(self) -> Any:
        if self._quality is None:
            from app.services.media_quality_service import MediaQualityService

            self._quality = MediaQualityService(settings=self._settings)
        return self._quality

    def _process_media_quality(
        self,
        db: Session,
        targets: list[ScheduleWorkerTarget],
        owner_id: str,
        schedule_dry_run: bool,
        result: SchedulerWorkerTickResult,
    ) -> None:
        """Оценить качество медиатеки проектов из targets. Правило-ориентированно, без AI/live.

        Управляется MEDIA_QUALITY_SCORING_WORKER_ENABLED (выключено по умолчанию); dry-run =
        worker dry-run ИЛИ MEDIA_QUALITY_SCORING_DRY_RUN.
        """
        s = self._settings
        enabled = s.media_quality_scoring_worker_enabled_effective
        result.media_quality_scoring_enabled = enabled
        dry_run = bool(schedule_dry_run or s.media_quality_scoring_dry_run)
        result.media_quality_scoring_dry_run = dry_run
        if not enabled:
            return
        seen: set[int] = set()
        for target in targets:
            if target.project_id in seen:
                continue
            seen.add(target.project_id)
            try:
                summary = self._quality_svc().score_project_media(
                    db,
                    target.project_id,
                    platform_key=target.platform_key,
                    limit=200,
                    dry_run=dry_run,
                )
            except Exception as exc:  # noqa: BLE001 — оценка не роняет тик
                result.media_quality_errors.append(f"p{target.project_id}: {type(exc).__name__}")
                continue
            result.media_quality_assets_scanned += int(summary.get("scanned", 0))
            result.media_quality_snapshots_created += int(summary.get("snapshots_created", 0))
            result.media_quality_weak_count += int(summary.get("weak", 0))
            result.media_quality_duplicate_count += int(summary.get("duplicates", 0))
        action = (
            ACTION_WORKER_MEDIA_QUALITY_PREVIEWED if dry_run else ACTION_WORKER_MEDIA_QUALITY_SCORED
        )
        base_meta = {
            "owner_id": owner_id,
            "dry_run": dry_run,
            "assets_scanned": result.media_quality_assets_scanned,
            "snapshots_created": result.media_quality_snapshots_created,
            "weak": result.media_quality_weak_count,
            "duplicates": result.media_quality_duplicate_count,
            "external_ai": False,
            "live_publish": False,
        }
        self._audit.record(db, action, entity_type="scheduler_worker", metadata=base_meta)
        if result.media_quality_errors:
            self._audit.record(
                db,
                ACTION_WORKER_MEDIA_QUALITY_FAILED,
                entity_type="scheduler_worker",
                metadata={**base_meta, "errors": len(result.media_quality_errors)},
            )

    # ------------------------------------------------------------------ #
    # Fingerprint и дедупликация медиа (v0.4.7, без внешнего AI/сети/live) #
    # ------------------------------------------------------------------ #

    def _fingerprint_svc(self) -> Any:
        if self._fingerprint is None:
            from app.services.media_fingerprint_service import MediaFingerprintService

            self._fingerprint = MediaFingerprintService(settings=self._settings)
        return self._fingerprint

    def _similarity_svc(self) -> Any:
        if self._similarity is None:
            from app.services.media_similarity_service import MediaSimilarityService

            self._similarity = MediaSimilarityService(settings=self._settings)
        return self._similarity

    def _process_media_fingerprints(
        self,
        db: Session,
        targets: list[ScheduleWorkerTarget],
        owner_id: str,
        schedule_dry_run: bool,
        result: SchedulerWorkerTickResult,
    ) -> None:
        """Считать fingerprint + кластеры дублей медиатеки проектов. Локально, без AI/сети/live.

        Управляется MEDIA_FINGERPRINTING_WORKER_ENABLED (выключено по умолчанию); dry-run =
        worker dry-run ИЛИ MEDIA_FINGERPRINTING_DRY_RUN.
        """
        s = self._settings
        enabled = s.media_fingerprinting_worker_enabled_effective
        result.media_fingerprinting_enabled = enabled
        dry_run = bool(schedule_dry_run or s.media_fingerprinting_dry_run)
        result.media_fingerprinting_dry_run = dry_run
        if not enabled:
            return
        seen: set[int] = set()
        for target in targets:
            if target.project_id in seen:
                continue
            seen.add(target.project_id)
            try:
                fp_summary = self._fingerprint_svc().calculate_project_fingerprints(
                    db, target.project_id, dry_run=dry_run
                )
                dup_summary = self._similarity_svc().find_duplicate_clusters(
                    db, target.project_id, dry_run=dry_run
                )
            except Exception as exc:  # noqa: BLE001 — расчёт не роняет тик
                result.duplicate_cluster_errors.append(
                    f"p{target.project_id}: {type(exc).__name__}"
                )
                continue
            if dry_run:
                result.media_fingerprints_previewed += int(fp_summary.get("scanned", 0))
                result.duplicate_clusters_previewed += int(dup_summary.get("clusters_found", 0))
            else:
                result.media_fingerprints_created += int(fp_summary.get("created", 0))
                result.duplicate_clusters_created += int(dup_summary.get("clusters_created", 0))
        fp_action = (
            ACTION_WORKER_MEDIA_FINGERPRINT_PREVIEWED
            if dry_run
            else ACTION_WORKER_MEDIA_FINGERPRINT_CREATED
        )
        dup_action = (
            ACTION_WORKER_DUPLICATE_CLUSTER_PREVIEWED
            if dry_run
            else ACTION_WORKER_DUPLICATE_CLUSTER_CREATED
        )
        base_meta = {
            "owner_id": owner_id,
            "dry_run": dry_run,
            "fingerprints_previewed": result.media_fingerprints_previewed,
            "fingerprints_created": result.media_fingerprints_created,
            "clusters_previewed": result.duplicate_clusters_previewed,
            "clusters_created": result.duplicate_clusters_created,
            "external_ai": False,
            "live_publish": False,
        }
        self._audit.record(db, fp_action, entity_type="scheduler_worker", metadata=base_meta)
        self._audit.record(db, dup_action, entity_type="scheduler_worker", metadata=base_meta)
        if result.duplicate_cluster_errors:
            self._audit.record(
                db,
                ACTION_WORKER_MEDIA_FINGERPRINT_FAILED,
                entity_type="scheduler_worker",
                metadata={**base_meta, "errors": len(result.duplicate_cluster_errors)},
            )

    # ------------------------------------------------------------------ #
    # Предложения экспериментов (v0.4.3, без live-публикации)             #
    # ------------------------------------------------------------------ #

    def _process_experiment_suggestions(
        self,
        db: Session,
        targets: list[ScheduleWorkerTarget],
        owner_id: str,
        schedule_dry_run: bool,
        result: SchedulerWorkerTickResult,
    ) -> None:
        """По проектам из целей предложить эксперименты/темы. Никаких live-публикаций.

        Управляется флагами: выключено по умолчанию; suggestions dry-run = worker dry-run
        ИЛИ EXPERIMENT_SUGGESTIONS_DRY_RUN. Ошибки одного проекта не роняют тик.
        """
        s = self._settings
        enabled = s.experiment_suggestions_worker_enabled_effective
        result.experiment_suggestions_enabled = enabled
        suggestions_dry = bool(schedule_dry_run or s.experiment_suggestions_dry_run)
        result.experiment_suggestions_dry_run = suggestions_dry
        if not enabled:
            return
        seen: set[int] = set()
        for target in targets:
            if target.project_id in seen:
                continue
            seen.add(target.project_id)
            try:
                out = self._suggestion_svc().run_worker_suggestions_for_project(
                    db,
                    target.project_id,
                    platform_key=None,
                    worker_owner_id=owner_id,
                    dry_run=suggestions_dry,
                )
            except Exception as exc:  # noqa: BLE001 — один проект не роняет тик
                result.experiment_suggestion_errors.append(
                    f"suggestions p{target.project_id}: {type(exc).__name__}"
                )
                continue
            result.experiment_suggestions_scanned += int(out.get("scanned", 0))
            result.experiment_suggestions_created += int(out.get("created", 0))
            result.experiment_suggestions_skipped += int(out.get("skipped", 0))
            result.experiments_created += int(out.get("experiments_created", 0))
            for err in out.get("errors", []):
                result.experiment_suggestion_errors.append(str(err))

    def _suggestion_svc(self) -> Any:
        if self._suggestions is None:
            from app.services.experiment_suggestion_service import ExperimentSuggestionService

            self._suggestions = ExperimentSuggestionService(settings=self._settings)
        return self._suggestions

    # ------------------------------------------------------------------ #
    # Цикл                                                               #
    # ------------------------------------------------------------------ #

    def run_loop(
        self,
        stop_event: threading.Event | None = None,
        once: bool = False,
        dry_run: bool | None = None,
        force: bool = False,
        owner_id: str | None = None,
        session_factory: Callable[[], Session] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> dict[str, Any]:
        """Бесконечный цикл тиков (Ctrl+C — graceful). Отказывается, если выключен без force."""
        if not self._settings.scheduler_worker_enabled_effective and not force:
            logger.info("scheduler worker disabled; refusing loop (use --force для local)")
            return {
                "enabled": False,
                "ran": False,
                "ticks": 0,
                "message": "SCHEDULER_WORKER_ENABLED=false; use force",
            }
        owner_id = owner_id or self.build_owner_id()
        stop_event = stop_event or threading.Event()
        interval = self._settings.scheduler_worker_interval_seconds_safe
        factory = session_factory or _default_session_factory
        ticks = 0
        last: SchedulerWorkerTickResult | None = None
        try:
            while not stop_event.is_set():
                with _session_scope(factory) as db:
                    last = self.tick(db, owner_id=owner_id, dry_run=dry_run, force=force)
                ticks += 1
                logger.info(
                    "scheduler tick #%s dry_run=%s drafts=%s scanned=%s",
                    ticks,
                    last.dry_run,
                    last.drafts_created,
                    last.targets_scanned,
                )
                if once:
                    break
                if (
                    stop_event.wait(interval)
                    if sleep_fn is None
                    else _sleep(sleep_fn, interval, stop_event)
                ):
                    break
        except KeyboardInterrupt:
            logger.info("scheduler worker: получен Ctrl+C — останавливаюсь")
        finally:
            with _session_scope(factory) as db:
                scheduler_worker_repository.release_lease(db, LEASE_KEY, owner_id)
        return {
            "enabled": self._settings.scheduler_worker_enabled_effective or force,
            "ran": ticks > 0,
            "ticks": ticks,
            "last": last.as_dict() if last is not None else None,
        }

    # ------------------------------------------------------------------ #
    # Статус                                                             #
    # ------------------------------------------------------------------ #

    def status(self, db: Session) -> dict[str, Any]:
        """Состояние worker-а для UI/API (без секретов)."""
        s = self._settings
        lease = scheduler_worker_repository.get_lease(db, LEASE_KEY)
        return {
            "enabled": s.scheduler_worker_enabled_effective,
            "dry_run": s.scheduler_worker_dry_run,
            "create_drafts": s.scheduler_worker_create_drafts,
            "interval_seconds": s.scheduler_worker_interval_seconds_safe,
            "batch_size": s.scheduler_worker_batch_size,
            "platform_allowlist": s.scheduler_worker_platform_allowlist_list,
            "account_allowlist": s.scheduler_worker_account_allowlist_list,
            "live_publish": False,
            "experiment_suggestions": {
                "enabled": s.experiment_suggestions_enabled_effective,
                "worker_enabled": s.experiment_suggestions_worker_enabled_effective,
                "dry_run": s.experiment_suggestions_dry_run,
                "auto_create": s.experiment_suggestions_auto_create_effective,
                "schedule_experiments_enabled": s.schedule_experiments_enabled,
                "max_per_tick": s.experiment_suggestions_max_per_tick,
                "live_publish": False,
            },
            "auto_topic_selection": {
                "enabled": s.auto_topic_selection_enabled_effective,
                "worker_enabled": s.auto_topic_selection_worker_enabled_effective,
                "dry_run": s.auto_topic_selection_dry_run,
                "min_confidence": s.auto_topic_selection_min_confidence_safe,
                "live_publish": False,
            },
            "auto_media_selection": {
                "enabled": s.auto_media_selection_enabled_effective,
                "worker_enabled": s.auto_media_selection_worker_enabled_effective,
                "dry_run": s.auto_media_selection_dry_run,
                "min_confidence": s.auto_media_selection_min_confidence_safe,
                "create_public_links": s.auto_media_selection_create_public_links,
                "live_publish": False,
            },
            "media_quality_scoring": {
                "enabled": s.media_quality_scoring_enabled_effective,
                "worker_enabled": s.media_quality_scoring_worker_enabled_effective,
                "dry_run": s.media_quality_scoring_dry_run,
                "min_good_score": s.media_quality_min_good_score_safe,
                "external_ai": s.media_quality_external_ai_enabled,
                "live_publish": False,
            },
            "media_fingerprinting": {
                "enabled": s.media_fingerprinting_enabled_effective,
                "worker_enabled": s.media_fingerprinting_worker_enabled_effective,
                "dry_run": s.media_fingerprinting_dry_run,
                "external_ai": s.media_fingerprinting_external_ai_enabled,
                "yandex_download": s.media_fingerprinting_use_yandex_download,
                "auto_delete": s.media_duplicate_auto_delete_enabled,
                "live_publish": False,
            },
            "lease": self._mask_lease(lease),
            "warnings": self._status_warnings(),
        }

    @staticmethod
    def _mask_lease(lease: Any) -> dict[str, Any] | None:
        if lease is None:
            return None
        return {
            "lease_key": lease.lease_key,
            "owner_id": lease.owner_id,
            "status": lease.status,
            "acquired_at": lease.acquired_at.isoformat() if lease.acquired_at else None,
            "expires_at": lease.expires_at.isoformat() if lease.expires_at else None,
            "heartbeat_at": lease.heartbeat_at.isoformat() if lease.heartbeat_at else None,
        }

    def _status_warnings(self) -> list[str]:
        warnings = ["Live-публикации выключены — worker создаёт только draft/needs_review."]
        if not self._settings.scheduler_worker_enabled_effective:
            warnings.append("Worker выключен (SCHEDULER_WORKER_ENABLED=false).")
        if self._settings.is_production:
            warnings.append("В production запускайте worker отдельным процессом/контейнером.")
        return warnings


def _safe_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return "host"


def _default_session_factory() -> Session:
    from app.db.session import get_sessionmaker

    return get_sessionmaker()()


@contextmanager
def _session_scope(factory: Callable[[], Session]) -> Iterator[Session]:
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _sleep(sleep_fn: Callable[[float], None], interval: int, stop_event: threading.Event) -> bool:
    """Прерываемый сон через переданную функцию (для тестов). True — если stop."""
    sleep_fn(min(interval, 1))
    return stop_event.is_set()


def get_scheduler_worker_service() -> SchedulerWorkerService:
    """DI-фабрика фонового scheduler-worker."""
    return SchedulerWorkerService()
