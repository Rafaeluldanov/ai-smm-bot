"""AIWorkflowManagerService — AI Workflow Manager / Business Execution Layer (v0.7.2).

Превращает бизнес-цели и AI-рекомендации в управляемые процессы: цель → этапы →
ответственные → сроки → зависимости → прогресс → блокеры → рекомендации AI. Это слой
управления процессами (workflow management), НЕ исполнитель.

Поток: **Create Workflow → Generate Steps → Assign → Track → Analyze → Recommend**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ выполняет задачи автоматически; assign/complete/status лишь меняют статус этапа;
- НЕ меняет CRM/бюджет/продажи, НЕ запускает рекламу, НЕ публикует, НЕ включает live;
- НЕ совершает внешних действий; строго per-project; секретов нет; всё бесплатно (0 units);
- каждое изменение (created/step_created/step_assigned/step_completed/blocker_*) — в AuditLog.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import project_repository
from app.repositories import workflow_repository as repo
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.business_workflow import BusinessWorkflow
    from app.models.workflow_blocker import WorkflowBlocker
    from app.models.workflow_step import WorkflowStep
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Этапы по умолчанию для типа процесса (когда нет данных из AI-слоёв).
_DEFAULT_STEPS: dict[str, tuple[str, ...]] = {
    "sales": ("Подготовить кейсы клиентов", "Запустить кампанию", "Оптимизировать конверсию"),
    "growth": ("Определить точку роста", "Усилить работающий канал", "Замерить результат"),
    "marketing": ("Спланировать кампанию", "Подготовить контент", "Запустить и отслеживать"),
    "content": ("Собрать темы", "Подготовить контент-план", "Опубликовать и замерить"),
    "operational": ("Описать процесс", "Назначить ответственных", "Внедрить и проверить"),
    "custom": ("Определить шаги", "Назначить ответственных", "Отслеживать прогресс"),
}
# Рекомендация по типу блокера.
_BLOCKER_ADVICE: dict[str, str] = {
    "dependency": "Разблокируйте зависимость или измените порядок этапов",
    "resource": "Выделите ресурс или ответственного под этап",
    "approval": "Получите одобрение ответственного, чтобы снять блокер",
    "missing_data": "Соберите недостающие данные для этапа",
    "external": "Согласуйте с внешней стороной и зафиксируйте срок",
}
# Порог «долгого» блокера (дней) для рекомендации назначить ответственного.
_STALE_BLOCKER_DAYS = 7


class AIWorkflowManagerError(Exception):
    """Ошибка Workflow Manager (нет проекта/процесса/этапа/блокера) — API → 400/404."""


class AIWorkflowManagerService:
    """AI-менеджер процессов: create → generate steps → assign → track → analyze → recommend."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Процессы                                                           #
    # ------------------------------------------------------------------ #

    def create_workflow_from_goal(
        self,
        db: Session,
        project_id: int,
        *,
        name: str,
        workflow_type: str,
        goal: str | None = None,
        description: str | None = None,
        target_value: float = 0.0,
        deadline: datetime | None = None,
        objective_id: int | None = None,
        task_id: int | None = None,
        status: str = "draft",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать процесс из бизнес-цели (Business OS) или AI-задачи (Chief of Staff)."""
        from app.models.business_workflow import WORKFLOW_STATUSES, WORKFLOW_TYPES

        self._require_project(db, project_id)
        if workflow_type not in WORKFLOW_TYPES:
            raise AIWorkflowManagerError("Неизвестный тип процесса")
        if status not in WORKFLOW_STATUSES:
            raise AIWorkflowManagerError("Неизвестный статус процесса")
        meta: dict[str, Any] = {}
        clean_name = (name or "").strip()
        # Обогащение из бизнес-цели / AI-задачи (без изменения источника).
        if objective_id is not None:
            objective = self._objective(db, objective_id, project_id)
            if objective is not None:
                clean_name = clean_name or f"Процесс: {objective.title}"
                goal = goal or objective.title
                target_value = target_value or float(objective.target_value or 0.0)
                deadline = deadline or objective.deadline
                meta["source_objective_id"] = objective_id
        if task_id is not None:
            task = self._chief_task(db, task_id, project_id)
            if task is not None:
                clean_name = clean_name or f"Процесс: {task.title}"
                goal = goal or task.title
                description = description or task.description
                meta["source_task_id"] = task_id
        if not clean_name:
            raise AIWorkflowManagerError("Укажите название процесса")

        workflow = repo.create_workflow(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            name=clean_name,
            workflow_type=workflow_type,
            description=description,
            goal=goal,
            status=status,
            target_value=target_value,
            start_date=datetime.now(UTC) if status == "active" else None,
            deadline=deadline,
            created_by_user_id=user_id,
            workflow_metadata=meta,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_WORKFLOW_CREATED,
            project_id,
            user_id,
            workflow.id,
            {"workflow_type": workflow_type, "status": status},
        )
        return repo.public_workflow_view(workflow)

    def list_workflows(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список процессов проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_workflow_view(w) for w in repo.list_workflows(db, project_id, status=status)
        ]

    def get_workflow(self, db: Session, workflow_id: int) -> dict[str, Any]:
        """Процесс + этапы + блокеры (с актуальным прогрессом)."""
        workflow = self._require_workflow(db, workflow_id)
        repo.calculate_progress(db, workflow)
        return {
            "workflow": repo.public_workflow_view(workflow),
            "steps": [repo.public_step_view(s) for s in repo.list_steps(db, workflow_id)],
            "blockers": [repo.public_blocker_view(b) for b in repo.list_blockers(db, workflow_id)],
        }

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка процессов проекта (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_workflow_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Генерация этапов                                                   #
    # ------------------------------------------------------------------ #

    def generate_workflow_steps(
        self, db: Session, workflow_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Сгенерировать этапы: AI Executive Plan + Chief Tasks + дефолт по типу процесса."""
        workflow = self._require_workflow(db, workflow_id)
        if not self._resolve_settings().workflow_manager_enabled_effective:
            return []
        titles = self._candidate_step_titles(db, workflow)
        existing = {s.title.strip().lower() for s in repo.list_steps(db, workflow_id)}
        created: list[dict[str, Any]] = []
        order = repo.next_order_number(db, workflow_id)
        for title, priority in titles:
            norm = title.strip().lower()
            if not norm or norm in existing:
                continue
            step = repo.create_step(
                db,
                workflow_id=workflow_id,
                title=title,
                order_number=order,
                priority=priority,
            )
            existing.add(norm)
            order += 1
            created.append(repo.public_step_view(step))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_WORKFLOW_STEP_CREATED,
                workflow.project_id,
                user_id,
                workflow_id,
                {"created": len(created)},
            )
        repo.calculate_progress(db, workflow)
        return created

    def _candidate_step_titles(
        self, db: Session, workflow: BusinessWorkflow
    ) -> list[tuple[str, str]]:
        """Кандидаты этапов (title, priority): из executive-плана + Chief-задач + дефолта типа."""
        out: list[tuple[str, str]] = []
        seen: set[str] = set()

        def _add(title: str, priority: str) -> None:
            norm = title.strip().lower()
            if title.strip() and norm not in seen:
                seen.add(norm)
                out.append((title.strip(), priority))

        # 1) Приоритетные действия исполнительного плана (Business OS / Executive Layer).
        for action in self._executive_actions(db, workflow.project_id):
            _add(str(action.get("title", "")), self._priority_bucket(action.get("priority", 0.0)))
        # 2) Открытые задачи AI Chief of Staff (интеграция задача → этап).
        for task in self._chief_open_tasks(db, workflow.project_id):
            _add(str(task.get("title", "")), str(task.get("priority", "medium")))
        # 3) Дефолтные этапы по типу процесса.
        for title in _DEFAULT_STEPS.get(workflow.workflow_type, _DEFAULT_STEPS["custom"]):
            _add(title, "medium")
        return out

    @staticmethod
    def _priority_bucket(score: Any) -> str:
        try:
            value = float(score)
        except (TypeError, ValueError):
            return "medium"
        if value >= 70:
            return "critical"
        if value >= 45:
            return "high"
        if value >= 25:
            return "medium"
        return "low"

    # ------------------------------------------------------------------ #
    # Прогресс                                                            #
    # ------------------------------------------------------------------ #

    def calculate_workflow_progress(self, db: Session, workflow_id: int) -> float:
        """Пересчитать прогресс процесса (completed / все, кроме cancelled × 100)."""
        workflow = self._require_workflow(db, workflow_id)
        return repo.calculate_progress(db, workflow)

    # ------------------------------------------------------------------ #
    # Здоровье процесса + рекомендации                                    #
    # ------------------------------------------------------------------ #

    def analyze_workflow_health(self, db: Session, workflow_id: int) -> dict[str, Any]:
        """Анализ здоровья процесса: просрочки, блокеры, отсутствие движения, риски."""
        workflow = self._require_workflow(db, workflow_id)
        steps = repo.list_steps(db, workflow_id)
        open_blockers = repo.list_blockers(db, workflow_id, status="open")
        now = datetime.now(UTC)

        overdue = [s for s in steps if self._is_overdue(s, now)]
        stuck = [s for s in steps if self._is_stuck(s, now)]

        penalty = 12 * len(open_blockers) + 10 * len(overdue) + 6 * len(stuck)
        health_score = round(max(0.0, min(100.0, 100.0 - penalty)), 1)

        risks: list[str] = []
        if overdue:
            risks.append(f"Просрочено этапов: {len(overdue)}")
        if open_blockers:
            risks.append(f"Открытых блокеров: {len(open_blockers)}")
        if stuck:
            risks.append(f"Этапы без движения: {len(stuck)}")
        if not risks and workflow.status == "active" and workflow.progress_percent < 100:
            risks.append("Критичных рисков нет — держите темп")

        return {
            "workflow_id": workflow_id,
            "health_score": health_score,
            "progress_percent": round(float(workflow.progress_percent or 0.0), 1),
            "overdue_steps": len(overdue),
            "open_blockers": len(open_blockers),
            "stuck_steps": len(stuck),
            "risks": risks,
            "recommendations": self._recommendations(steps, open_blockers, now),
        }

    def create_ai_recommendations(self, db: Session, workflow_id: int) -> list[str]:
        """AI-рекомендации по процессу (что сделать, чтобы снять блокеры/ускорить)."""
        self._require_workflow(db, workflow_id)
        steps = repo.list_steps(db, workflow_id)
        open_blockers = repo.list_blockers(db, workflow_id, status="open")
        return self._recommendations(steps, open_blockers, datetime.now(UTC))

    def _recommendations(
        self, steps: list[WorkflowStep], open_blockers: list[WorkflowBlocker], now: datetime
    ) -> list[str]:
        recs: list[str] = []
        for blocker in open_blockers:
            advice = _BLOCKER_ADVICE.get(blocker.blocker_type, "Определите план снятия блокера")
            recs.append(f"Блокер «{blocker.title}»: {advice}")
            if self._blocker_age_days(blocker, now) >= _STALE_BLOCKER_DAYS:
                recs.append(f"Блокер «{blocker.title}» держится >7 дней — назначьте ответственного")
        for step in steps:
            if self._is_overdue(step, now):
                recs.append(f"Этап «{step.title}» просрочен — пересмотрите срок или ускорьте")
            elif step.status == "in_progress" and step.owner_user_id is None:
                recs.append(f"Этап «{step.title}» в работе без ответственного — назначьте его")
        if not recs:
            recs.append("Процесс здоров — продолжайте отслеживать статусы этапов")
        return recs

    # ------------------------------------------------------------------ #
    # Этапы: назначение / статус / завершение                            #
    # ------------------------------------------------------------------ #

    def list_steps(self, db: Session, workflow_id: int) -> list[dict[str, Any]]:
        """Этапы процесса по порядку."""
        self._require_workflow(db, workflow_id)
        return [repo.public_step_view(s) for s in repo.list_steps(db, workflow_id)]

    def assign_step(
        self, db: Session, step_id: int, owner_user_id: int | None, user_id: int | None = None
    ) -> dict[str, Any]:
        """Назначить ответственного за этап. НЕ выполняет этап."""
        step = self._require_step(db, step_id)
        if step.status in ("completed", "cancelled"):
            raise AIWorkflowManagerError("Этап уже закрыт")
        repo.assign_step(db, step, owner_user_id=owner_user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_WORKFLOW_STEP_ASSIGNED,
            self._workflow_project_id(db, step.workflow_id),
            user_id,
            step.id,
            {"owner_user_id": owner_user_id},
        )
        return repo.public_step_view(step)

    def update_step_status(
        self,
        db: Session,
        step_id: int,
        status: str,
        *,
        progress_percent: float | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Сменить статус этапа. НЕ запускает внешних действий."""
        from app.models.business_workflow import WORKFLOW_STEP_STATUSES

        step = self._require_step(db, step_id)
        if status not in WORKFLOW_STEP_STATUSES:
            raise AIWorkflowManagerError("Неизвестный статус этапа")
        if step.status in ("completed", "cancelled"):
            raise AIWorkflowManagerError("Этап уже закрыт")
        if status == "completed":
            return self.complete_step(db, step_id, user_id=user_id)
        repo.update_step_status(db, step, status, progress_percent=progress_percent)
        self._recalculate(db, step.workflow_id)
        return repo.public_step_view(step)

    def complete_step(
        self, db: Session, step_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Завершить этап (status=completed). НЕ запускает внешних действий."""
        step = self._require_step(db, step_id)
        if step.status == "completed":
            raise AIWorkflowManagerError("Этап уже завершён")
        if step.status == "cancelled":
            raise AIWorkflowManagerError("Нельзя завершить отменённый этап")
        repo.update_step_status(db, step, "completed", stamp_completed=True)
        project_id = self._workflow_project_id(db, step.workflow_id)
        self._write_audit(
            db,
            audit_actions.ACTION_WORKFLOW_STEP_COMPLETED,
            project_id,
            user_id,
            step.id,
            {},
        )
        self._recalculate(db, step.workflow_id)
        return repo.public_step_view(step)

    # ------------------------------------------------------------------ #
    # Блокеры                                                             #
    # ------------------------------------------------------------------ #

    def create_blocker(
        self,
        db: Session,
        workflow_id: int,
        *,
        blocker_type: str,
        title: str,
        step_id: int | None = None,
        description: str | None = None,
        severity: str = "medium",
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать блокер процесса (status=open). Помечает связанный этап как blocked."""
        from app.models.business_workflow import BLOCKER_SEVERITIES, BLOCKER_TYPES

        workflow = self._require_workflow(db, workflow_id)
        if blocker_type not in BLOCKER_TYPES:
            raise AIWorkflowManagerError("Неизвестный тип блокера")
        if severity not in BLOCKER_SEVERITIES:
            raise AIWorkflowManagerError("Неизвестная тяжесть блокера")
        clean_title = (title or "").strip()
        if not clean_title:
            raise AIWorkflowManagerError("Укажите название блокера")
        if step_id is not None:
            step = self._require_step(db, step_id)
            if step.workflow_id != workflow_id:
                raise AIWorkflowManagerError("Этап не принадлежит этому процессу")
            if step.status not in ("completed", "cancelled"):
                repo.update_step_status(db, step, "blocked")
        blocker = repo.create_blocker(
            db,
            workflow_id=workflow_id,
            step_id=step_id,
            blocker_type=blocker_type,
            title=clean_title,
            description=description,
            severity=severity,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_WORKFLOW_BLOCKER_CREATED,
            workflow.project_id,
            user_id,
            blocker.id,
            {"blocker_type": blocker_type, "severity": severity},
        )
        return repo.public_blocker_view(blocker)

    def resolve_blocker(
        self, db: Session, blocker_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Снять блокер (status=resolved). Связанный blocked-этап → assigned/pending."""
        blocker = self._require_blocker(db, blocker_id)
        if blocker.status == "resolved":
            raise AIWorkflowManagerError("Блокер уже снят")
        repo.resolve_blocker(db, blocker)
        if blocker.step_id is not None:
            step = repo.get_step(db, blocker.step_id)
            # Разблокируем этап только если на нём НЕ осталось других открытых блокеров.
            still_blocked = any(
                b.step_id == blocker.step_id
                for b in repo.list_blockers(db, blocker.workflow_id, status="open")
            )
            if step is not None and step.status == "blocked" and not still_blocked:
                restored = "assigned" if step.owner_user_id is not None else "pending"
                repo.update_step_status(db, step, restored)
        self._write_audit(
            db,
            audit_actions.ACTION_WORKFLOW_BLOCKER_RESOLVED,
            self._workflow_project_id(db, blocker.workflow_id),
            user_id,
            blocker.id,
            {},
        )
        return repo.public_blocker_view(blocker)

    # ------------------------------------------------------------------ #
    # Внутреннее: сбор сигналов из смежных слоёв                          #
    # ------------------------------------------------------------------ #

    def _executive_actions(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Приоритетные действия исполнительного плана (reuse AIExecutiveService, v0.7.0)."""
        try:
            from app.services.ai_executive_service import AIExecutiveService

            executive = AIExecutiveService(settings=self._resolve_settings())
            plan = executive.get_plan(db, project_id)
            if plan.get("has_plan"):
                return list(plan.get("actions") or [])
        except Exception as exc:  # noqa: BLE001 — вспомогательный слой не критичен
            logger.warning("workflow executive actions failed: %s", type(exc).__name__)
        return []

    def _chief_open_tasks(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """Открытые задачи AI Chief of Staff (интеграция задача → этап, v0.7.1)."""
        try:
            from app.repositories import chief_of_staff_repository as chief_repo

            return [
                chief_repo.public_task_view(t) for t in chief_repo.list_open_tasks(db, project_id)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("workflow chief tasks failed: %s", type(exc).__name__)
            return []

    def _objective(self, db: Session, objective_id: int, project_id: int) -> Any:
        from app.repositories import business_os_repository

        objective = business_os_repository.get_objective(db, objective_id)
        if objective is None or objective.project_id != project_id:
            raise AIWorkflowManagerError("Цель не найдена в этом проекте")
        return objective

    def _chief_task(self, db: Session, task_id: int, project_id: int) -> Any:
        from app.repositories import chief_of_staff_repository as chief_repo

        task = chief_repo.get_task(db, task_id)
        if task is None or task.project_id != project_id:
            raise AIWorkflowManagerError("Задача не найдена в этом проекте")
        return task

    # --- признаки здоровья ---

    @staticmethod
    def _as_aware(dt: datetime | None) -> datetime | None:
        """Привести datetime из БД к tz-aware (SQLite отдаёт naive, Postgres — aware)."""
        if dt is None:
            return None
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    @classmethod
    def _is_overdue(cls, step: WorkflowStep, now: datetime) -> bool:
        deadline = cls._as_aware(step.deadline)
        return (
            deadline is not None
            and deadline < now
            and step.status not in ("completed", "cancelled")
        )

    @classmethod
    def _is_stuck(cls, step: WorkflowStep, now: datetime) -> bool:
        if step.status not in ("in_progress", "blocked"):
            return False
        updated = cls._as_aware(step.updated_at)
        return updated is not None and (now - updated) >= timedelta(days=_STALE_BLOCKER_DAYS)

    @classmethod
    def _blocker_age_days(cls, blocker: WorkflowBlocker, now: datetime) -> float:
        created = cls._as_aware(blocker.created_at)
        if created is None:
            return 0.0
        return (now - created).total_seconds() / 86400.0

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _recalculate(self, db: Session, workflow_id: int) -> None:
        workflow = repo.get_workflow(db, workflow_id)
        if workflow is not None:
            repo.calculate_progress(db, workflow)

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIWorkflowManagerError(f"Проект id={project_id} не найден")
        return project

    def _require_workflow(self, db: Session, workflow_id: int) -> BusinessWorkflow:
        workflow = repo.get_workflow(db, workflow_id)
        if workflow is None:
            raise AIWorkflowManagerError("Процесс не найден")
        return workflow

    def _require_step(self, db: Session, step_id: int) -> WorkflowStep:
        step = repo.get_step(db, step_id)
        if step is None:
            raise AIWorkflowManagerError("Этап не найден")
        return step

    def _require_blocker(self, db: Session, blocker_id: int) -> WorkflowBlocker:
        blocker = repo.get_blocker(db, blocker_id)
        if blocker is None:
            raise AIWorkflowManagerError("Блокер не найден")
        return blocker

    def _workflow_project_id(self, db: Session, workflow_id: int) -> int:
        workflow = repo.get_workflow(db, workflow_id)
        return workflow.project_id if workflow is not None else 0

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
            entity_type="business_workflow",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_workflow_manager_service() -> AIWorkflowManagerService:
    """DI-фабрика AI Workflow Manager / Business Execution Layer."""
    return AIWorkflowManagerService()
