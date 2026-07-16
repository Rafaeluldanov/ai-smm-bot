"""AIContinuousImprovementService — AI Continuous Improvement Engine (v0.8.0).

Строит цикл обучения бизнеса на истории решений и результатов: сохраняет опыт, создаёт события
обучения, анализирует итоги, находит паттерны и причины провалов, формирует backlog улучшений и
объясняет владельцу выводы.

Поток: **Performance Result → Experience Memory → Learning Event → Pattern Analysis →
Improvement Backlog → Owner Review**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это learning/аналитический слой: только учится и советует;
- НЕ меняет бизнес/стратегию/KPI/CRM/бюджет, НЕ выполняет задачи и улучшения, НЕ запускает
  рекламу, НЕ публикует; approve/reject меняют ТОЛЬКО статус улучшения;
- ВЕСЬ сбор смежных слоёв — READ-ONLY чтение персистов в try/except;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (experience/event/pattern/improvement_created/approved/rejected) → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import continuous_improvement_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.improvement_item import ImprovementItem
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# outcome опыта → тип события обучения.
_OUTCOME_TO_EVENT: dict[str, str] = {
    "success": "success",
    "failure": "failure",
    "neutral": "insight",
}


class AIContinuousImprovementError(Exception):
    """Ошибка Continuous Improvement (нет проекта/улучшения) — API → 400/404."""


class AIContinuousImprovementService:
    """AI-цикл обучения: experience → event → pattern → improvement → owner review."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Цикл обучения (анализ)                                              #
    # ------------------------------------------------------------------ #

    def run_learning_cycle(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Прогнать цикл обучения: опыт → события → паттерны → улучшения. НЕ меняет бизнес."""
        self._require_project(db, project_id)
        experiences = self.capture_experience(db, project_id, user_id)
        for experience in experiences:
            self.create_learning_event(db, experience, project_id, user_id)
        patterns = self.detect_patterns(db, project_id, user_id)
        improvements = self.generate_improvements(db, project_id, patterns, user_id)
        return {
            "experiences": experiences,
            "patterns": patterns,
            "improvements": improvements,
            "insights": self.explain_learning(db, project_id)["insights"],
        }

    def capture_experience(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Собрать опыт из Performance / Execution / Decision (read-only) → ExperienceMemory."""
        created: list[dict[str, Any]] = []
        account_id = self._account_id(db, project_id)

        # Performance: последний снимок эффективности (expected=target, actual=actual).
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                outcome = self._performance_outcome(snapshot.status)
                deviations = perf_repo.list_deviations(db, snapshot.id)
                lessons = [d.title for d in deviations] or ["Показатели в пределах плана"]
                score = round(float(snapshot.performance_score or 0), 1)
                exp = repo.create_experience(
                    db,
                    project_id=project_id,
                    account_id=account_id,
                    experience_type="performance",
                    source_id=snapshot.id,
                    title=f"Эффективность: score {score}",
                    context={"status": snapshot.status},
                    expected_result=dict(snapshot.target_state or {}),
                    actual_result=dict(snapshot.actual_state or {}),
                    outcome=outcome,
                    lessons=lessons,
                    confidence_score=float(snapshot.performance_score or 0.0),
                )
                created.append(repo.public_experience_view(exp))
        except Exception as exc:  # noqa: BLE001 — нижний слой не должен ронять сбор опыта
            logger.warning("improvement performance capture failed: %s", type(exc).__name__)

        # Execution: последний план исполнения (outcome по прогрессу).
        try:
            from app.repositories import execution_repository as exec_repo

            plans = exec_repo.list_execution_plans(db, project_id, limit=1)
            if plans:
                plan = plans[0]
                progress = float(exec_repo.calculate_progress(db, plan.id))
                blocked = exec_repo.get_blocked_tasks(db, plan.id)
                exp = repo.create_experience(
                    db,
                    project_id=project_id,
                    account_id=account_id,
                    experience_type="execution",
                    source_id=plan.id,
                    title=f"Исполнение: прогресс {progress}%",
                    context={"blocked_tasks": len(blocked)},
                    expected_result={"progress": 100.0},
                    actual_result={"progress": progress},
                    outcome=self._progress_outcome(progress),
                    lessons=(
                        [f"Заблокированных задач: {len(blocked)}"] if blocked else ["Блокеров нет"]
                    ),
                    confidence_score=progress,
                )
                created.append(repo.public_experience_view(exp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement execution capture failed: %s", type(exc).__name__)

        # Decision: последнее рекомендованное/принятое решение (контекст, outcome=neutral).
        try:
            from app.repositories import decision_repository as decision_repo

            decisions = [
                d
                for d in decision_repo.list_decisions(db, project_id, limit=5)
                if d.status in ("recommended", "accepted", "applied")
            ]
            if decisions:
                decision = decisions[0]
                exp = repo.create_experience(
                    db,
                    project_id=project_id,
                    account_id=account_id,
                    experience_type="decision",
                    source_id=decision.id,
                    title=f"Решение: {decision.title}",
                    context={"decision_type": decision.decision_type, "status": decision.status},
                    outcome="neutral",
                    lessons=["Решение зафиксировано в опыте"],
                    confidence_score=float(decision.confidence_score or 0.0),
                )
                created.append(repo.public_experience_view(exp))
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement decision capture failed: %s", type(exc).__name__)

        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_LEARNING_EXPERIENCE_CREATED,
                project_id,
                user_id,
                None,
                {"experiences": len(created)},
            )
        return created

    def create_learning_event(
        self,
        db: Session,
        experience: dict[str, Any],
        project_id: int,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать событие обучения из опыта (success/failure/insight/…)."""
        event_type = _OUTCOME_TO_EVENT.get(experience.get("outcome", "neutral"), "insight")
        event = repo.create_event(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            event_type=event_type,
            experience_id=experience.get("id"),
            title=f"{event_type}: {experience.get('title', '')}"[:255],
            description=f"Опыт «{experience.get('experience_type')}» → {event_type}",
            impact={"lessons": experience.get("lessons", [])},
        )
        self._write_audit(
            db,
            audit_actions.ACTION_LEARNING_EVENT_CREATED,
            project_id,
            user_id,
            event.id,
            {"event_type": event_type},
            entity_type="learning_event",
        )
        return repo.public_event_view(event)

    def analyze_outcome(
        self, expected_result: dict[str, Any], actual_result: dict[str, Any]
    ) -> str:
        """Сравнить план vs факт → success / failure / neutral (по средней доле достижения)."""
        ratios: list[float] = []
        for key, exp in (expected_result or {}).items():
            try:
                exp_value = float(exp)
            except (TypeError, ValueError):
                continue
            if exp_value <= 0:
                continue
            try:
                act_value = float((actual_result or {}).get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                act_value = 0.0
            ratios.append(min(2.0, act_value / exp_value))
        if not ratios:
            return "neutral"
        avg = sum(ratios) / len(ratios)
        if avg >= 0.9:
            return "success"
        if avg < 0.6:
            return "failure"
        return "neutral"

    # ------------------------------------------------------------------ #
    # Паттерны / причины провалов                                        #
    # ------------------------------------------------------------------ #

    def detect_patterns(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Найти паттерны в опыте: success/failure/optimization. Создать AIPattern."""
        history = repo.get_experience_history(db, project_id)
        successes = [e for e in history if e.outcome == "success"]
        failures = [e for e in history if e.outcome == "failure"]
        created: list[dict[str, Any]] = []

        if len(successes) >= 2:
            created.append(
                self._make_pattern(
                    db,
                    project_id,
                    "success_pattern",
                    "Повторяющийся успех",
                    "Найдены повторяющиеся успешные результаты — стоит закрепить подход.",
                    [e.title for e in successes[:5]],
                    min(100.0, len(successes) * 25.0),
                )
            )
        if failures:
            causes = self.analyze_failure(db, project_id)
            created.append(
                self._make_pattern(
                    db,
                    project_id,
                    "failure_pattern",
                    "Повторяющийся провал",
                    "Найдены провальные результаты — есть системные причины.",
                    causes or [e.title for e in failures[:5]],
                    min(100.0, len(failures) * 30.0),
                )
            )
        optimization_signals = self._optimization_signals(db, project_id)
        if optimization_signals:
            created.append(
                self._make_pattern(
                    db,
                    project_id,
                    "optimization_pattern",
                    "Точки оптимизации",
                    "Есть места, где исполнение можно ускорить/улучшить.",
                    optimization_signals,
                    60.0,
                )
            )
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_LEARNING_PATTERN_CREATED,
                project_id,
                user_id,
                None,
                {"patterns": len(created)},
                entity_type="ai_pattern",
            )
        return created

    def analyze_failure(self, db: Session, project_id: int) -> list[str]:
        """Определить причины провалов (стратегия/прогноз/исполнение/ресурсы). Только чтение."""
        causes: list[str] = []
        # Execution: блокеры + незакрытые задачи + отсутствие владельцев.
        try:
            from app.repositories import execution_repository as exec_repo

            plans = exec_repo.list_execution_plans(db, project_id, limit=1)
            if plans:
                tasks = exec_repo.list_tasks_for_plan(db, plans[0].id)
                blocked = [t for t in tasks if t.status == "blocked"]
                no_owner = [t for t in tasks if t.owner_user_id is None and t.status != "completed"]
                if blocked:
                    causes.append("проблемы исполнения: блокеры задач")
                if no_owner:
                    causes.append("нехватка ресурсов: задачи без владельцев")
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement failure execution failed: %s", type(exc).__name__)
        # Forecast: низкая уверенность прогноза.
        try:
            from app.repositories import business_forecast_repository as fc_repo

            forecast = fc_repo.get_latest_forecast(db, project_id)
            if forecast is not None and float(forecast.confidence_score or 0.0) < 40.0:
                causes.append("плохой прогноз: низкая уверенность модели")
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement failure forecast failed: %s", type(exc).__name__)
        # Performance: критические отклонения → неверная стратегия.
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None:
                critical = [
                    d
                    for d in perf_repo.list_deviations(db, snapshot.id)
                    if d.impact in ("high", "critical")
                ]
                if critical:
                    causes.append("неверная стратегия: значимые отклонения от плана")
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement failure performance failed: %s", type(exc).__name__)
        return causes

    def generate_improvements(
        self,
        db: Session,
        project_id: int,
        patterns: list[dict[str, Any]],
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Сформировать backlog улучшений из паттернов (только предложения)."""
        created: list[dict[str, Any]] = []
        account_id = self._account_id(db, project_id)
        for pattern in patterns:
            if pattern["pattern_type"] == "success_pattern":
                continue  # успех закрепляем, отдельного улучшения не нужно
            for signal in pattern.get("signals", [])[:3]:
                advice = self._improvement_for_signal(str(signal))
                improvement = repo.create_improvement(
                    db,
                    project_id=project_id,
                    account_id=account_id,
                    pattern_id=pattern["id"],
                    title=advice["title"],
                    priority=advice["priority"],
                    description=f"Из паттерна «{pattern['title']}»: {signal}",
                    expected_impact=advice["impact"],
                )
                created.append(repo.public_improvement_view(improvement))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_LEARNING_IMPROVEMENT_CREATED,
                project_id,
                user_id,
                None,
                {"improvements": len(created)},
                entity_type="improvement_item",
            )
        return created

    def explain_learning(self, db: Session, project_id: int) -> dict[str, Any]:
        """Объяснить владельцу: что AI понял из прошлого опыта."""
        summary = repo.build_learning_summary(db, project_id)
        patterns = repo.list_patterns(db, project_id)
        insights: list[str] = [
            f"Собрано опыта: {summary['experiences_total']}, "
            f"паттернов: {summary['patterns_total']}, "
            f"улучшений в backlog: {summary['improvements_total']}.",
        ]
        for pattern in patterns[:3]:
            insights.append(
                f"{pattern.pattern_type}: {pattern.title} (уверенность "
                f"{round(float(pattern.confidence_score or 0.0), 1)})."
            )
        if len(insights) == 1:
            insights.append("Пока недостаточно опыта — запустите анализ после нескольких циклов.")
        insights.append("Это обучение и рекомендации; бизнес/стратегия/KPI не меняются.")
        return {"project_id": project_id, "insights": insights}

    # ------------------------------------------------------------------ #
    # Approve / reject (только статус)                                   #
    # ------------------------------------------------------------------ #

    def approve_improvement(
        self, db: Session, improvement_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить улучшение (status=accepted). НЕ применяет."""
        improvement = self._require_improvement(db, improvement_id)
        if improvement.status not in ("identified", "reviewed"):
            raise AIContinuousImprovementError("Улучшение уже обработано")
        repo.update_improvement(db, improvement, status="accepted")
        self._write_audit(
            db,
            audit_actions.ACTION_LEARNING_IMPROVEMENT_APPROVED,
            improvement.project_id,
            user_id,
            improvement.id,
            {},
            entity_type="improvement_item",
        )
        return repo.public_improvement_view(improvement)

    def reject_improvement(
        self, db: Session, improvement_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить улучшение (status=rejected). НЕ применяет."""
        improvement = self._require_improvement(db, improvement_id)
        if improvement.status not in ("identified", "reviewed"):
            raise AIContinuousImprovementError("Улучшение уже обработано")
        repo.update_improvement(db, improvement, status="rejected")
        self._write_audit(
            db,
            audit_actions.ACTION_LEARNING_IMPROVEMENT_REJECTED,
            improvement.project_id,
            user_id,
            improvement.id,
            {},
            entity_type="improvement_item",
        )
        return repo.public_improvement_view(improvement)

    # ------------------------------------------------------------------ #
    # Чтение                                                             #
    # ------------------------------------------------------------------ #

    def get_history(
        self, db: Session, project_id: int, experience_type: str | None = None
    ) -> dict[str, Any]:
        """История опыта + события обучения + сводка."""
        self._require_project(db, project_id)
        return {
            "experiences": [
                repo.public_experience_view(e)
                for e in repo.get_experience_history(
                    db, project_id, experience_type=experience_type
                )
            ],
            "events": [repo.public_event_view(ev) for ev in repo.list_events(db, project_id)],
            "summary": repo.build_learning_summary(db, project_id),
        }

    def get_patterns(
        self, db: Session, project_id: int, pattern_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Паттерны проекта."""
        self._require_project(db, project_id)
        return [
            repo.public_pattern_view(p)
            for p in repo.list_patterns(db, project_id, pattern_type=pattern_type)
        ]

    def get_improvements(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Backlog улучшений проекта."""
        self._require_project(db, project_id)
        return [
            repo.public_improvement_view(i)
            for i in repo.list_improvements(db, project_id, status=status)
        ]

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _make_pattern(
        self,
        db: Session,
        project_id: int,
        pattern_type: str,
        title: str,
        description: str,
        signals: list[Any],
        confidence: float,
    ) -> dict[str, Any]:
        pattern = repo.create_pattern(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            pattern_type=pattern_type,
            title=title,
            description=description,
            signals=list(signals),
            confidence_score=round(self._clamp(confidence, 0.0, 100.0), 1),
        )
        return repo.public_pattern_view(pattern)

    def _optimization_signals(self, db: Session, project_id: int) -> list[str]:
        """Сигналы для optimization_pattern (блокеры/отклонения). Только чтение."""
        signals: list[str] = []
        try:
            from app.repositories import execution_repository as exec_repo

            plans = exec_repo.list_execution_plans(db, project_id, limit=1)
            if plans and exec_repo.get_blocked_tasks(db, plans[0].id):
                signals.append("блокеры/зависимости тормозят исполнение")
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement optimization exec failed: %s", type(exc).__name__)
        try:
            from app.repositories import performance_repository as perf_repo

            snapshot = perf_repo.get_latest_snapshot(db, project_id)
            if snapshot is not None and perf_repo.list_deviations(db, snapshot.id):
                signals.append("отклонения метрик от плана")
        except Exception as exc:  # noqa: BLE001
            logger.warning("improvement optimization perf failed: %s", type(exc).__name__)
        return signals

    @staticmethod
    def _improvement_for_signal(signal: str) -> dict[str, Any]:
        """Рекомендация улучшения по сигналу паттерна."""
        low = signal.lower()
        if "блокер" in low or "зависимост" in low:
            return {
                "title": "Уменьшить количество зависимостей и снять блокеры.",
                "priority": "high",
                "impact": {"metric": "execution", "note": "+скорость исполнения"},
            }
        if "владельц" in low or "ресурс" in low:
            return {
                "title": "Назначить владельцев задач без ответственных.",
                "priority": "high",
                "impact": {"metric": "execution", "note": "+ответственность"},
            }
        if "прогноз" in low:
            return {
                "title": "Улучшить качество данных для прогноза.",
                "priority": "medium",
                "impact": {"metric": "forecast", "note": "+точность"},
            }
        if "стратег" in low or "отклонен" in low:
            return {
                "title": "Пересмотреть стратегию по проблемным метрикам.",
                "priority": "high",
                "impact": {"metric": "strategy", "note": "+соответствие плану"},
            }
        return {
            "title": f"Устранить проблему: {signal}.",
            "priority": "medium",
            "impact": {"note": "улучшение результата"},
        }

    @staticmethod
    def _performance_outcome(status: str) -> str:
        if status == "healthy":
            return "success"
        if status == "critical":
            return "failure"
        return "neutral"

    @staticmethod
    def _progress_outcome(progress: float) -> str:
        if progress >= 80.0:
            return "success"
        if progress < 40.0:
            return "failure"
        return "neutral"

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        return max(low, min(high, float(value)))

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIContinuousImprovementError(f"Проект id={project_id} не найден")
        return project

    def _require_improvement(self, db: Session, improvement_id: int) -> ImprovementItem:
        improvement = repo.get_improvement(db, improvement_id)
        if improvement is None:
            raise AIContinuousImprovementError("Улучшение не найдено")
        return improvement

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _write_audit(
        self,
        db: Session,
        action: str,
        project_id: int,
        user_id: int | None,
        entity_id: int | None,
        metadata: dict[str, Any],
        entity_type: str = "experience_memory",
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=self._account_id(db, project_id),
            user_id=user_id,
            project_id=project_id,
            entity_type=entity_type,
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_continuous_improvement_service() -> AIContinuousImprovementService:
    """DI-фабрика AI Continuous Improvement."""
    return AIContinuousImprovementService()
