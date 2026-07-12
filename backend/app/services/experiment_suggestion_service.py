"""Предложения экспериментов worker-ом (v0.4.3).

Анализирует проект (через :class:`TopicOptimizationService`) и предлагает эксперименты/темы.
Предложения показываются клиенту; он принимает/отклоняет/скрывает или создаёт A/B через
:class:`ABTestingService`. Worker может генерировать предложения (и опционально авто-создавать
эксперименты), но **никогда** не публикует live.

БЕЗОПАСНОСТЬ:
- никаких live-публикаций и внешних API-вызовов;
- worker-генерация и авто-создание ВЫКЛЮЧЕНЫ по умолчанию (config);
- дедуп по cooldown + idempotency; строгая project/account-изоляция; без секретов.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.experiment_suggestion import SUGGESTION_TYPES
from app.repositories import (
    content_experiment_repository,
    experiment_suggestion_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions
from app.services.billing_service import BillingService, InsufficientBalanceError

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.ab_testing_service import ABTestingService
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService
    from app.services.topic_optimization_service import TopicOptimizationService

logger = get_logger(__name__)

# Категории рекомендаций → типы предложений (совпадают по значению). Единый источник —
# перечисление терминов в модели (Part 1).
_SUGGESTION_TYPES = SUGGESTION_TYPES
# Категории, из которых имеет смысл создавать A/B-эксперимент.
_EXPERIMENTABLE = ("publish_more", "explore", "fill_gap", "retest", "weak_topic_fix")


class ExperimentSuggestionError(Exception):
    """Ошибка предложений (нет предложения/проекта, режим выключен) — API → 400/409."""


class ExperimentSuggestionService:
    """Генерация/приём предложений экспериментов + создание A/B из предложения."""

    def __init__(
        self,
        topic_service: TopicOptimizationService | None = None,
        ab_service: ABTestingService | None = None,
        learning_service: ClientLearningService | None = None,
        billing_service: BillingService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._topic = topic_service
        self._ab = ab_service
        self._learning = learning_service
        self._billing = billing_service or BillingService()
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview (без записи, без биллинга)                               #
    # ------------------------------------------------------------------ #

    def preview_suggestions(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Предложения-кандидаты (без записи и без списания)."""
        min_conf = self._min_confidence()
        if not self._feature_enabled():
            return {
                "project_id": project_id,
                "platform_key": platform_key,
                "min_confidence": min_conf,
                "suggestions": [],
                "writes": False,
                "disabled": True,
            }
        limit = limit or self._max_per_tick()
        recs = self._topic_svc().recommend_next_topics(db, project_id, platform_key, limit)
        previews = [
            {**self._rec_preview(r), "meets_confidence": _conf(r) >= min_conf}
            for r in recs["recommendations"]
        ]
        self._write_audit(
            db,
            project_id,
            None,
            audit_actions.ACTION_EXP_SUGGESTION_PREVIEWED,
            {"platform_key": platform_key, "count": len(previews)},
        )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "min_confidence": min_conf,
            "suggestions": previews,
            "writes": False,
        }

    # ------------------------------------------------------------------ #
    # 2. Генерация предложений (запись, без биллинга)                     #
    # ------------------------------------------------------------------ #

    def generate_suggestions(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        idempotency_prefix: str | None = None,
        current_user_id: int | None = None,
        worker_owner_id: str | None = None,
        source: str = "manual",
    ) -> dict[str, Any]:
        """Создать предложения (proposed). Дедуп по cooldown + idempotency; без списаний."""
        if not self._feature_enabled():
            return {
                "project_id": project_id,
                "platform_key": platform_key,
                "scanned": 0,
                "created": 0,
                "skipped": 0,
                "suggestions": [],
                "disabled": True,
            }
        now = datetime.now(UTC)
        experiment_suggestion_repository.cleanup_expired(db, project_id, now)
        account_id = self._account_id(db, project_id)
        max_active = self._max_active_per_project()
        max_per_tick = self._max_per_tick()
        min_conf = self._min_confidence()
        cooldown_since = now - timedelta(seconds=self._cooldown_seconds())
        expires_at = (
            now + timedelta(seconds=self._expire_seconds()) if self._expire_seconds() else None
        )

        recs = self._topic_svc().recommend_next_topics(
            db, project_id, platform_key, max_per_tick * 3
        )
        created: list[Any] = []
        skipped = 0
        scanned = 0
        for rec in recs["recommendations"]:
            scanned += 1
            if len(created) >= max_per_tick:
                break
            if _conf(rec) < min_conf:
                skipped += 1
                continue
            if (
                experiment_suggestion_repository.count_active_for_project(db, project_id)
                >= max_active
            ):
                skipped += 1
                break
            # Тему клипуем сразу — тогда дедуп-поиск и запись используют одно значение.
            topic = str(rec.get("topic", "")).strip()[:512]
            if not topic:
                skipped += 1
                continue
            # Дедуп: та же тема/площадка в окне cooldown (сравнение — в Python, tz-safe).
            recent = experiment_suggestion_repository.find_recent_similar(
                db, project_id, platform_key, topic
            )
            if recent is not None and self._within_cooldown(recent.created_at, cooldown_since):
                skipped += 1
                continue
            idem = None
            if idempotency_prefix:
                # Ключ включает project_id — исключаем межарендную коллизию по чужому префиксу.
                idem = f"p{project_id}-{idempotency_prefix}-{self._topic_key(topic, platform_key)}"
                if experiment_suggestion_repository.get_by_idempotency_key(db, idem) is not None:
                    skipped += 1
                    continue
            suggestion = experiment_suggestion_repository.create_suggestion(
                db,
                account_id=account_id,
                project_id=project_id,
                platform_key=platform_key,
                suggestion_type=self._suggestion_type(rec),
                source=source,
                status="proposed",
                topic=topic,
                title=self._title(rec, topic),
                reason=str(rec.get("reason", ""))[:2000],
                confidence_score=_conf(rec),
                recommendation_payload=self._sanitize_payload(rec),
                source_signals=list(rec.get("source_signals", [])),
                risk_flags=list(rec.get("risk_flags", [])),
                suggested_cta=_clip(rec.get("suggested_cta"), 512),
                suggested_media_type=_clip(rec.get("suggested_media_type"), 64),
                suggested_publish_time=_clip(rec.get("suggested_time"), 20),
                estimated_units=int(rec.get("estimated_units", 0) or 0),
                idempotency_key=idem,
                worker_owner_id=worker_owner_id,
                expires_at=expires_at,
            )
            created.append(suggestion)
            self._write_audit(
                db,
                project_id,
                current_user_id,
                audit_actions.ACTION_EXP_SUGGESTION_CREATED,
                {
                    "suggestion_id": suggestion.id,
                    "suggestion_type": suggestion.suggestion_type,
                    "confidence": suggestion.confidence_score,
                },
            )
        self._write_audit(
            db,
            project_id,
            current_user_id,
            audit_actions.ACTION_EXP_SUGGESTION_GENERATED,
            {
                "created": len(created),
                "skipped": skipped,
                "scanned": scanned,
                "platform_key": platform_key,
                "source": source,
            },
        )
        if created:
            self._notify_owner(
                db,
                project_id,
                "experiment_suggestion_created",
                "Новые A/B-предложения",
                f"Worker создал предложений: {len(created)}.",
                current_user_id,
                action_url=f"/ui/projects/{project_id}/experiment-suggestions",
            )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "scanned": scanned,
            "created": len(created),
            "skipped": skipped,
            "suggestions": [self._suggestion_view(s) for s in created],
        }

    # ------------------------------------------------------------------ #
    # 3-5. Решения клиента                                                #
    # ------------------------------------------------------------------ #

    def accept_suggestion(
        self, db: Session, suggestion_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Принять предложение (status accepted). Эксперимент отдельно."""
        suggestion = self._get_suggestion(db, suggestion_id)
        experiment_suggestion_repository.mark_accepted(
            db, suggestion, current_user_id, datetime.now(UTC)
        )
        # Лёгкий положительный сигнал обучения по теме.
        self._learning_svc().record_suggestion_signal(
            db,
            suggestion.project_id,
            suggestion.topic,
            positive=True,
            platform_key=suggestion.platform_key,
        )
        self._write_audit(
            db,
            suggestion.project_id,
            current_user_id,
            audit_actions.ACTION_EXP_SUGGESTION_ACCEPTED,
            {"suggestion_id": suggestion_id},
        )
        return self._suggestion_view(suggestion, refreshed=True, db=db)

    def reject_suggestion(
        self,
        db: Session,
        suggestion_id: int,
        reason: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Отклонить предложение (status rejected) + слабый негативный сигнал обучения."""
        suggestion = self._get_suggestion(db, suggestion_id)
        experiment_suggestion_repository.mark_rejected(
            db, suggestion, current_user_id, datetime.now(UTC), reason
        )
        self._learning_svc().record_suggestion_signal(
            db,
            suggestion.project_id,
            suggestion.topic,
            positive=False,
            platform_key=suggestion.platform_key,
        )
        self._write_audit(
            db,
            suggestion.project_id,
            current_user_id,
            audit_actions.ACTION_EXP_SUGGESTION_REJECTED,
            {"suggestion_id": suggestion_id},
        )
        return self._suggestion_view(suggestion, refreshed=True, db=db)

    def dismiss_suggestion(
        self, db: Session, suggestion_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Скрыть предложение (status dismissed)."""
        suggestion = self._get_suggestion(db, suggestion_id)
        experiment_suggestion_repository.mark_dismissed(
            db, suggestion, current_user_id, datetime.now(UTC)
        )
        self._write_audit(
            db,
            suggestion.project_id,
            current_user_id,
            audit_actions.ACTION_EXP_SUGGESTION_DISMISSED,
            {"suggestion_id": suggestion_id},
        )
        return self._suggestion_view(suggestion, refreshed=True, db=db)

    # ------------------------------------------------------------------ #
    # 6. Создание A/B из предложения (платно, идемпотентно)               #
    # ------------------------------------------------------------------ #

    def create_experiment_from_suggestion(
        self,
        db: Session,
        suggestion_id: int,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Создать A/B-эксперимент из предложения. Варианты — в очередь ревью. Live нет."""
        suggestion = self._get_suggestion(db, suggestion_id)
        if suggestion.status == "experiment_created" and suggestion.experiment_id is not None:
            return {
                **self._suggestion_view(suggestion),
                "experiment_id": suggestion.experiment_id,
                "outcome": "skipped_duplicate",
            }
        # Платное действие только для «живых» предложений — не тратим units на
        # отклонённые/скрытые/истёкшие/ошибочные.
        if suggestion.status not in ("proposed", "accepted"):
            raise ExperimentSuggestionError(
                f"Нельзя создать эксперимент из предложения в статусе {suggestion.status}"
            )
        key = idempotency_key or f"suggestion-{suggestion_id}-experiment"
        try:
            result = self._ab_svc().create_experiment_from_topic(
                db,
                suggestion.project_id,
                suggestion.platform_key,
                suggestion.topic,
                current_user_id=current_user_id,
                idempotency_key=key,
            )
        except InsufficientBalanceError:
            self._write_audit(
                db,
                suggestion.project_id,
                current_user_id,
                audit_actions.ACTION_EXP_SUGGESTION_FAILED,
                {"suggestion_id": suggestion_id, "reason": "insufficient_balance"},
            )
            raise
        except Exception as exc:  # noqa: BLE001 — не роняем API
            experiment_suggestion_repository.mark_failed(
                db, suggestion, f"experiment create failed: {type(exc).__name__}"
            )
            raise ExperimentSuggestionError(str(exc)) from exc

        experiment_id = result["experiment"]["id"]
        # Связать эксперимент с предложением (в metadata) и наоборот.
        experiment = content_experiment_repository.get_experiment_by_id(db, experiment_id)
        if experiment is not None:
            meta = dict(experiment.experiment_metadata or {})
            meta["suggestion_id"] = suggestion_id
            content_experiment_repository.update_experiment(
                db, experiment, experiment_metadata=meta
            )
        experiment_suggestion_repository.mark_experiment_created(
            db, suggestion, experiment_id, datetime.now(UTC)
        )
        self._write_audit(
            db,
            suggestion.project_id,
            current_user_id,
            audit_actions.ACTION_EXP_SUGGESTION_EXPERIMENT_CREATED,
            {"suggestion_id": suggestion_id, "experiment_id": experiment_id},
        )
        return {
            **self._suggestion_view(suggestion, refreshed=True, db=db),
            "experiment_id": experiment_id,
            "outcome": result.get("outcome", "created"),
        }

    # ------------------------------------------------------------------ #
    # 7. Точка входа worker-а                                             #
    # ------------------------------------------------------------------ #

    def run_worker_suggestions_for_project(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        worker_owner_id: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Прогон предложений для проекта из worker-а. Никаких live-публикаций."""
        result: dict[str, Any] = {
            "project_id": project_id,
            "enabled": self._worker_enabled(),
            "dry_run": dry_run,
            "scanned": 0,
            "created": 0,
            "skipped": 0,
            "experiments_created": 0,
            "errors": [],
        }
        if not self._worker_enabled():
            return result
        try:
            if dry_run:
                preview = self.preview_suggestions(db, project_id, platform_key)
                result["scanned"] = len(preview["suggestions"])
                self._write_audit(
                    db,
                    project_id,
                    None,
                    audit_actions.ACTION_WORKER_EXP_SUGGESTIONS_PREVIEWED,
                    {"scanned": result["scanned"], "platform_key": platform_key},
                )
                return result
            prefix = self._worker_prefix(worker_owner_id, project_id, self._cooldown_window())
            gen = self.generate_suggestions(
                db,
                project_id,
                platform_key,
                idempotency_prefix=prefix,
                worker_owner_id=worker_owner_id,
                source="worker",
            )
            result["scanned"] = gen["scanned"]
            result["created"] = gen["created"]
            result["skipped"] = gen["skipped"]
            self._write_audit(
                db,
                project_id,
                None,
                audit_actions.ACTION_WORKER_EXP_SUGGESTIONS_CREATED,
                {
                    "created": gen["created"],
                    "skipped": gen["skipped"],
                    "platform_key": platform_key,
                },
            )
            if gen["skipped"]:
                # Отдельное событие про пропуски (дедуп/cooldown/ниже порога/лимит).
                self._write_audit(
                    db,
                    project_id,
                    None,
                    audit_actions.ACTION_WORKER_EXP_SUGGESTIONS_SKIPPED,
                    {"skipped": gen["skipped"], "platform_key": platform_key},
                )
            if self._auto_create_enabled():
                created = self._worker_auto_create(db, project_id, gen["suggestions"], result)
                result["experiments_created"] = created
        except Exception as exc:  # noqa: BLE001 — worker не роняет тик
            result["errors"].append(f"suggestions p{project_id}: {type(exc).__name__}")
            self._write_audit(
                db,
                project_id,
                None,
                audit_actions.ACTION_WORKER_EXP_SUGGESTIONS_FAILED,
                {"error": type(exc).__name__, "project_id": project_id},
            )
        return result

    def _worker_auto_create(
        self,
        db: Session,
        project_id: int,
        suggestion_views: list[dict[str, Any]],
        result: dict[str, Any],
    ) -> int:
        """Авто-создать A/B из лучших предложений (только draft/needs_review; без live)."""
        created = 0
        for view in suggestion_views:
            if view.get("suggestion_type") not in _EXPERIMENTABLE:
                continue
            try:
                out = self.create_experiment_from_suggestion(db, view["id"])
                if out.get("experiment_id"):
                    created += 1
                    self._write_audit(
                        db,
                        project_id,
                        None,
                        audit_actions.ACTION_WORKER_EXPERIMENT_CREATED,
                        {"suggestion_id": view["id"], "experiment_id": out["experiment_id"]},
                    )
            except InsufficientBalanceError:
                result["errors"].append("auto_create: insufficient_balance")
                break  # нет смысла продолжать без баланса
            except Exception as exc:  # noqa: BLE001
                result["errors"].append(f"auto_create: {type(exc).__name__}")
        return created

    # ------------------------------------------------------------------ #
    # 8. Дашборд                                                          #
    # ------------------------------------------------------------------ #

    def build_suggestion_dashboard(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Сводка предложений проекта для UI."""
        suggestions = experiment_suggestion_repository.list_for_project(
            db, project_id, platform_key=platform_key, limit=200
        )
        by_status: dict[str, int] = {}
        confidences: list[float] = []
        reasons: dict[str, int] = {}
        for s in suggestions:
            by_status[s.status] = by_status.get(s.status, 0) + 1
            if s.status in ("proposed", "accepted"):
                confidences.append(s.confidence_score)
            key = s.suggestion_type
            reasons[key] = reasons.get(key, 0) + 1
        active = [
            self._suggestion_view(s) for s in suggestions if s.status in ("proposed", "accepted")
        ]
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "active_count": len(active),
            "accepted": by_status.get("accepted", 0),
            "rejected": by_status.get("rejected", 0),
            "dismissed": by_status.get("dismissed", 0),
            "experiments_created": by_status.get("experiment_created", 0),
            "avg_confidence": avg_conf,
            "top_types": sorted(reasons.items(), key=lambda kv: kv[1], reverse=True)[:5],
            "worker_enabled": self._worker_enabled(),
            "auto_create_enabled": self._auto_create_enabled(),
            "active_suggestions": active,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _suggestion_type(self, rec: dict[str, Any]) -> str:
        category = str(rec.get("category", "publish_more"))
        return category if category in _SUGGESTION_TYPES else "publish_more"

    @staticmethod
    def _title(rec: dict[str, Any], topic: str) -> str:
        labels = {
            "publish_more": "Публиковать чаще",
            "avoid": "Избегать",
            "retest": "Перетестировать",
            "explore": "Раскрыть тему",
            "fill_gap": "Закрыть пробел",
        }
        label = labels.get(str(rec.get("category", "")), "Рекомендация")
        return f"{label}: {topic}"[:255]

    @staticmethod
    def _rec_preview(rec: dict[str, Any]) -> dict[str, Any]:
        return {
            "topic": rec.get("topic"),
            "suggestion_type": rec.get("category"),
            "reason": rec.get("reason"),
            "confidence_score": rec.get("confidence_score"),
            "source_signals": rec.get("source_signals", []),
            "risk_flags": rec.get("risk_flags", []),
            "suggested_cta": rec.get("suggested_cta"),
            "suggested_media_type": rec.get("suggested_media_type"),
            "suggested_time": rec.get("suggested_time"),
            "estimated_units": rec.get("estimated_units", 0),
        }

    @staticmethod
    def _suggestion_view(
        suggestion: Any, refreshed: bool = False, db: Session | None = None
    ) -> dict[str, Any]:
        if refreshed and db is not None:
            db.refresh(suggestion)
        return {
            "id": suggestion.id,
            "project_id": suggestion.project_id,
            "platform_key": suggestion.platform_key,
            "suggestion_type": suggestion.suggestion_type,
            "source": suggestion.source,
            "status": suggestion.status,
            "topic": suggestion.topic,
            "title": suggestion.title,
            "reason": suggestion.reason,
            "confidence_score": round(suggestion.confidence_score, 3),
            "source_signals": list(suggestion.source_signals or []),
            "risk_flags": list(suggestion.risk_flags or []),
            "suggested_cta": suggestion.suggested_cta,
            "suggested_media_type": suggestion.suggested_media_type,
            "suggested_publish_time": suggestion.suggested_publish_time,
            "estimated_units": suggestion.estimated_units,
            "experiment_id": suggestion.experiment_id,
            "created_at": suggestion.created_at.isoformat() if suggestion.created_at else None,
        }

    @staticmethod
    def _sanitize_payload(rec: dict[str, Any]) -> dict[str, Any]:
        # Только безопасные поля рекомендации (без сырых объектов/секретов).
        return {
            "category": rec.get("category"),
            "confidence_score": rec.get("confidence_score"),
            "suggested_cta": rec.get("suggested_cta"),
            "suggested_media_type": rec.get("suggested_media_type"),
            "suggested_time": rec.get("suggested_time"),
            "estimated_units": rec.get("estimated_units", 0),
        }

    @staticmethod
    def _within_cooldown(created_at: datetime | None, cooldown_since: datetime) -> bool:
        """Создано ли ``created_at`` после начала окна cooldown (tz-safe: naive→UTC)."""
        if created_at is None:
            return False
        moment = created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
        return moment >= cooldown_since

    @staticmethod
    def _topic_key(topic: str, platform_key: str | None) -> str:
        raw = f"{platform_key or 'all'}:{topic.strip().lower()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _worker_prefix(worker_owner_id: str | None, project_id: int, window: int) -> str:
        # Ключ окна: owner + проект + бакет окна cooldown. Бакет двигается вместе с
        # cooldown, поэтому после окна idempotency больше не блокирует повторное
        # предложение той же темы (иначе тема пропадала бы навсегда).
        owner = (worker_owner_id or "worker").split(":")[0]
        return f"worker-{owner}-{project_id}-w{window}"

    def _cooldown_window(self) -> int:
        """Номер бакета окна cooldown для текущего момента (0, если cooldown отключён)."""
        seconds = self._cooldown_seconds()
        if seconds <= 0:
            return 0
        return int(datetime.now(UTC).timestamp() // seconds)

    def _get_suggestion(self, db: Session, suggestion_id: int) -> Any:
        suggestion = experiment_suggestion_repository.get_by_id(db, suggestion_id)
        if suggestion is None:
            raise ExperimentSuggestionError(f"Предложение id={suggestion_id} не найдено")
        return suggestion

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ExperimentSuggestionError(f"Проект id={project_id} не найден")
        return project.account_id

    def _notify_owner(  # noqa: PLR0913 — единый безопасный хук уведомления
        self,
        db: Session,
        project_id: int,
        notification_type: str,
        title: str,
        message: str,
        current_user_id: int | None,
        action_url: str | None = None,
    ) -> None:
        """Безопасно уведомить владельца проекта (не роняет основное действие)."""
        try:
            from app.services.notification_service import NotificationService

            NotificationService(settings=self._settings).notify_project_owner(
                db,
                project_id,
                notification_type,
                title,
                message,
                actor_user_id=current_user_id,
                entity_type="project",
                entity_id=project_id,
                action_url=action_url,
            )
        except Exception:  # noqa: BLE001 — уведомление не критично
            logger.warning("experiment suggestion notification failed", exc_info=False)

    # --- Настройки ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _feature_enabled(self) -> bool:
        # Мастер-выключатель фичи (гейтит и ручной preview/generate, не только worker).
        return bool(self._resolve_settings().experiment_suggestions_enabled_effective)

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().experiment_suggestions_worker_enabled_effective)

    def _auto_create_enabled(self) -> bool:
        return bool(self._resolve_settings().experiment_suggestions_auto_create_effective)

    def _min_confidence(self) -> float:
        return float(
            getattr(self._resolve_settings(), "experiment_suggestions_min_confidence", 0.55)
        )

    def _max_per_tick(self) -> int:
        return int(getattr(self._resolve_settings(), "experiment_suggestions_max_per_tick", 5))

    def _max_active_per_project(self) -> int:
        return int(
            getattr(self._resolve_settings(), "experiment_suggestions_max_active_per_project", 20)
        )

    def _cooldown_seconds(self) -> int:
        return int(getattr(self._resolve_settings(), "experiment_suggestions_cooldown_seconds", 0))

    def _expire_seconds(self) -> int:
        return int(getattr(self._resolve_settings(), "experiment_suggestions_expire_seconds", 0))

    # --- Ленивые зависимости ---

    def _topic_svc(self) -> TopicOptimizationService:
        if self._topic is None:
            from app.services.topic_optimization_service import TopicOptimizationService

            self._topic = TopicOptimizationService(settings=self._settings)
        return self._topic

    def _ab_svc(self) -> ABTestingService:
        if self._ab is None:
            from app.services.ab_testing_service import ABTestingService

            self._ab = ABTestingService(settings=self._settings)
        return self._ab

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self,
        db: Session,
        project_id: int,
        user_id: int | None,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        project = project_repository.get_project_by_id(db, project_id)
        account_id = project.account_id if project is not None else None
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=project_id,
            entity_type="experiment_suggestion",
            metadata=metadata,
        )


def _clip(value: Any, length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:length]


def _conf(rec: dict[str, Any]) -> float:
    """Уверенность рекомендации как float (None/пусто → 0.0)."""
    return float(rec.get("confidence_score") or 0.0)


def get_experiment_suggestion_service() -> ExperimentSuggestionService:
    """DI-фабрика сервиса предложений экспериментов."""
    return ExperimentSuggestionService()
