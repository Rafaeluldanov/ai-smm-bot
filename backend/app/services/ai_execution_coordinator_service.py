"""AIExecutionCoordinatorService — AI Execution Coordinator (v0.7.8).

Превращает утверждённый стратегический план (Business Planner) в управляемую систему исполнения:
создаёт цели и задачи, назначает владельцев, контролирует сроки и прогресс, находит блокеры и
даёт AI-рекомендации. Это coordination-слой.

Поток: **Approved Strategic Plan → Execution Plan → Objectives → Tasks → Owners → Progress → AI
Coordination**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- это coordination-слой: только координирует и советует;
- НЕ выполняет задачи, НЕ меняет бизнес/CRM/бюджет, НЕ запускает рекламу, НЕ публикует;
- assign/complete/status меняют ТОЛЬКО статус/владельца; workflow-link (по подтверждению) создаёт
  лишь ЧЕРНОВИК процесса (draft workflow), процессы/CRM/бюджет не запускаются;
- строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (execution.created/objective_created/task_created/task_assigned/task_completed/
  blocker_detected) пишется в AuditLog.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import execution_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.execution_objective import ExecutionObjective
    from app.models.execution_plan import ExecutionPlan
    from app.models.execution_task import ExecutionTask
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Шаблон задач для одной цели исполнения: (title, description).
_TASK_TEMPLATE: tuple[tuple[str, str], ...] = (
    ("Подготовить", "Спланировать шаги и подготовить ресурсы"),
    ("Выполнить", "Реализовать ключевые шаги цели"),
    ("Проанализировать результат", "Измерить результат и скорректировать"),
)

# Порог «нет владельца слишком долго» (дни).
_NO_OWNER_DAYS = 7
# Порог «нет прогресса слишком долго» (дни).
_NO_PROGRESS_DAYS = 3

# Тип цели/плана → тип процесса (для draft workflow при workflow-link).
_WORKFLOW_TYPE_DEFAULT = "operational"

# Подтверждение, обязательное для связи задачи с черновиком процесса.
LINK_CONFIRMATION = "LINK_WORKFLOW"


class AIExecutionCoordinatorError(Exception):
    """Ошибка Execution Coordinator (нет проекта/плана/задачи/подтверждения) — API → 400/404."""


class AIExecutionCoordinatorService:
    """AI-координатор исполнения: plan → objectives → tasks → owners → progress → coordination."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Планы исполнения: создание / чтение                                #
    # ------------------------------------------------------------------ #

    def create_execution_plan(
        self,
        db: Session,
        project_id: int,
        *,
        strategic_plan_id: int,
        title: str | None = None,
        description: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать план исполнения из УТВЕРЖДЁННОГО стратег. плана. НЕ запускает генерацию."""
        self._require_project(db, project_id)
        strategic = self._require_approved_plan_in_project(db, strategic_plan_id, project_id)
        clean_title = (title or "").strip() or f"Исполнение: {strategic.title}"
        plan = repo.create_execution_plan(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            strategic_plan_id=strategic.id,
            title=clean_title,
            description=description,
            status="draft",
        )
        self._write_audit(
            db,
            audit_actions.ACTION_EXECUTION_CREATED,
            project_id,
            user_id,
            plan.id,
            {"strategic_plan_id": strategic.id},
        )
        return repo.public_plan_view(plan)

    def list_execution_plans(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список планов исполнения проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_plan_view(p)
            for p in repo.list_execution_plans(db, project_id, status=status)
        ]

    def get_execution_plan(self, db: Session, execution_plan_id: int) -> dict[str, Any]:
        """План исполнения + цели + задачи."""
        plan = self._require_plan(db, execution_plan_id)
        objectives: list[dict[str, Any]] = []
        for objective in repo.list_objectives(db, execution_plan_id):
            view = repo.public_objective_view(objective)
            view["tasks"] = [repo.public_task_view(t) for t in repo.list_tasks(db, objective.id)]
            objectives.append(view)
        return {"plan": repo.public_plan_view(plan), "objectives": objectives}

    def get_tasks(self, db: Session, execution_plan_id: int) -> list[dict[str, Any]]:
        """Все задачи плана исполнения."""
        self._require_plan(db, execution_plan_id)
        return [repo.public_task_view(t) for t in repo.list_tasks_for_plan(db, execution_plan_id)]

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка Execution Coordinator (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_execution_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Генерация целей и задач                                            #
    # ------------------------------------------------------------------ #

    def generate_execution(
        self, db: Session, execution_plan_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сгенерировать исполнение: цели (из quarter objectives) → задачи → прогресс. Advisory."""
        plan = self._require_plan(db, execution_plan_id)
        self.generate_execution_objectives(db, execution_plan_id, user_id)
        for objective in repo.list_objectives(db, execution_plan_id):
            self.generate_execution_tasks(db, objective.id, user_id)
        repo.update_execution_plan(db, plan, status="active")
        self.calculate_execution_progress(db, execution_plan_id)
        return {
            **self.get_execution_plan(db, execution_plan_id),
            "health": self.get_health(db, execution_plan_id),
        }

    def generate_execution_objectives(
        self, db: Session, execution_plan_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Создать цели исполнения из квартальных целей стратегического плана (дедуп по title)."""
        plan = self._require_plan(db, execution_plan_id)
        quarter_objectives = self._strategic_quarter_objectives(db, plan.strategic_plan_id)
        existing = {o.title.strip().lower() for o in repo.list_objectives(db, execution_plan_id)}
        created: list[dict[str, Any]] = []
        for q in quarter_objectives:
            title = f"{q.get('quarter', '')}: {q.get('title', '')}".strip(": ").strip()
            if not title or title.strip().lower() in existing:
                continue
            objective = repo.create_objective(
                db,
                execution_plan_id=execution_plan_id,
                title=title,
                description=q.get("description"),
                kpi=list(q.get("kpi") or []),
                priority=str(q.get("priority", "medium")),
                status="active",
            )
            existing.add(title.strip().lower())
            created.append(repo.public_objective_view(objective))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_EXECUTION_OBJECTIVE_CREATED,
                plan.project_id,
                user_id,
                execution_plan_id,
                {"created": len(created)},
            )
        return created

    def generate_execution_tasks(
        self, db: Session, objective_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Разбить цель на задачи (дедуп по title). Задачи без владельца, status=pending."""
        objective = self._require_objective(db, objective_id)
        existing = {t.title.strip().lower() for t in repo.list_tasks(db, objective_id)}
        created: list[dict[str, Any]] = []
        for title, description in _TASK_TEMPLATE:
            if title.strip().lower() in existing:
                continue
            task = repo.create_task(
                db,
                objective_id=objective_id,
                title=title,
                description=description,
                priority=objective.priority,
                status="pending",
            )
            existing.add(title.strip().lower())
            created.append(repo.public_task_view(task))
        if created:
            plan_id = objective.execution_plan_id
            plan = repo.get_execution_plan(db, plan_id)
            if plan is not None:
                self._write_audit(
                    db,
                    audit_actions.ACTION_EXECUTION_TASK_CREATED,
                    plan.project_id,
                    user_id,
                    objective_id,
                    {"created": len(created)},
                )
        return created

    # ------------------------------------------------------------------ #
    # Владельцы / статус / прогресс                                      #
    # ------------------------------------------------------------------ #

    def assign_owner(
        self, db: Session, task_id: int, owner_user_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Назначить владельца задачи: ТОЛЬКО owner + status (pending→assigned). НЕ выполняет."""
        task = self._require_task(db, task_id)
        plan = self._plan_for_task(db, task)
        self._require_account_member(db, plan, owner_user_id)
        new_status = "assigned" if task.status == "pending" else task.status
        repo.update_task(db, task, owner_user_id=owner_user_id, status=new_status)
        self._write_audit(
            db,
            audit_actions.ACTION_EXECUTION_TASK_ASSIGNED,
            plan.project_id,
            user_id,
            task_id,
            {"owner_user_id": owner_user_id},
        )
        return repo.public_task_view(task)

    def set_task_status(
        self, db: Session, task_id: int, status: str, user_id: int | None = None
    ) -> dict[str, Any]:
        """Сменить статус задачи. ТОЛЬКО статус (без выполнения действий)."""
        from app.models.execution_plan import EXECUTION_TASK_STATUSES

        if status not in EXECUTION_TASK_STATUSES:
            raise AIExecutionCoordinatorError("Неизвестный статус задачи")
        if status == "completed":
            return self.complete_task(db, task_id, user_id)
        task = self._require_task(db, task_id)
        plan = self._plan_for_task(db, task)
        repo.update_task_status(db, task, status)
        self.calculate_execution_progress(db, plan.id)
        return repo.public_task_view(task)

    def complete_task(
        self, db: Session, task_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Завершить задачу (completed, progress=100). ТОЛЬКО статус. НЕ запускает действий."""
        task = self._require_task(db, task_id)
        plan = self._plan_for_task(db, task)
        repo.update_task_status(db, task, "completed")
        self.calculate_execution_progress(db, plan.id)
        self._write_audit(
            db, audit_actions.ACTION_EXECUTION_TASK_COMPLETED, plan.project_id, user_id, task_id, {}
        )
        return repo.public_task_view(task)

    def calculate_execution_progress(self, db: Session, execution_plan_id: int) -> float:
        """Прогресс плана = completed tasks / all tasks × 100; сохраняется на плане."""
        plan = self._require_plan(db, execution_plan_id)
        progress = repo.calculate_progress(db, execution_plan_id)
        repo.update_execution_plan(db, plan, progress_percent=progress)
        return progress

    # ------------------------------------------------------------------ #
    # Блокеры / координация                                              #
    # ------------------------------------------------------------------ #

    def detect_blockers(
        self, db: Session, execution_plan_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Найти блокеры: overdue / нет владельца / нет прогресса / незакрытая зависимость.

        Аналитически (статус задач НЕ меняет). Пишет один audit blocker_detected при находках.
        """
        plan = self._require_plan(db, execution_plan_id)
        now = self._now()
        blockers: list[dict[str, Any]] = []
        for task in repo.list_tasks_for_plan(db, execution_plan_id):
            if task.status in ("completed", "cancelled"):
                continue
            deadline = self._as_aware(task.deadline)
            created = self._as_aware(task.created_at) or now
            age_days = (now - created).days
            if deadline is not None and deadline < now:
                blockers.append(self._blocker(task, "overdue", "Просрочен срок задачи"))
            if task.owner_user_id is None and age_days >= _NO_OWNER_DAYS:
                blockers.append(self._blocker(task, "no_owner", f"Нет владельца {age_days} дн."))
            if (
                task.status in ("assigned", "in_progress")
                and float(task.progress_percent or 0.0) <= 0.0
                and age_days >= _NO_PROGRESS_DAYS
            ):
                blockers.append(self._blocker(task, "no_progress", "Нет прогресса по задаче"))
            if self._has_unsatisfied_dependency(db, task):
                blockers.append(self._blocker(task, "dependency", "Незакрытая зависимость"))
            if task.status == "blocked":
                blockers.append(self._blocker(task, "blocked", "Задача помечена заблокированной"))
        if blockers:
            self._write_audit(
                db,
                audit_actions.ACTION_EXECUTION_BLOCKER_DETECTED,
                plan.project_id,
                user_id,
                execution_plan_id,
                {"blockers": len(blockers)},
            )
        return blockers

    def generate_coordination_recommendations(
        self, db: Session, execution_plan_id: int, blockers: list[dict[str, Any]] | None = None
    ) -> list[str]:
        """AI-рекомендации по блокерам (только советы). Учитывает стиль управления владельца.

        `blockers` можно передать заранее (напр. из get_health), чтобы detect_blockers (и его
        audit) не выполнялся повторно за один запрос.
        """
        if blockers is None:
            blockers = self.detect_blockers(db, execution_plan_id)
        style_note = self._management_style_note(db, execution_plan_id)
        recs: list[str] = []
        for b in blockers:
            title = b.get("title", "")
            btype = b.get("type")
            if btype == "no_owner":
                recs.append(f"Назначить ответственного за задачу «{title}».")
            elif btype == "overdue":
                recs.append(f"Пересмотреть срок или ускорить задачу «{title}».")
            elif btype == "no_progress":
                recs.append(f"Проверить статус задачи «{title}» — нет прогресса.")
            elif btype == "dependency":
                recs.append(f"Разблокировать зависимость для задачи «{title}».")
            elif btype == "blocked":
                recs.append(f"Снять блокировку с задачи «{title}».")
        if not recs:
            recs.append("Блокеров не выявлено — исполнение идёт по плану.")
        if style_note:
            recs.append(style_note)
        return recs

    def get_health(self, db: Session, execution_plan_id: int) -> dict[str, Any]:
        """Здоровье исполнения: прогресс + блокеры + рекомендации + счётчики."""
        plan = self._require_plan(db, execution_plan_id)
        tasks = repo.list_tasks_for_plan(db, execution_plan_id)
        blockers = self.detect_blockers(db, execution_plan_id)
        return {
            "execution_plan_id": execution_plan_id,
            "status": plan.status,
            "progress_percent": round(float(plan.progress_percent or 0.0), 1),
            "tasks_total": len(tasks),
            "tasks_completed": sum(1 for t in tasks if t.status == "completed"),
            "tasks_unassigned": sum(
                1 for t in tasks if t.owner_user_id is None and t.status != "completed"
            ),
            "blockers": blockers,
            # Переиспользуем уже вычисленные blockers → detect_blockers (и его audit) один раз.
            "recommendations": self.generate_coordination_recommendations(
                db, execution_plan_id, blockers=blockers
            ),
            "note": "Координация — совет; задачи не выполняются автоматически.",
        }

    # ------------------------------------------------------------------ #
    # Связь с Workflow (только черновик)                                 #
    # ------------------------------------------------------------------ #

    def create_workflow_link(
        self, db: Session, task_id: int, confirmation: str = "", user_id: int | None = None
    ) -> dict[str, Any]:
        """Связать задачу с ЧЕРНОВИКОМ процесса. ТОЛЬКО по LINK_WORKFLOW. НЕ запускает."""
        if confirmation != LINK_CONFIRMATION:
            raise AIExecutionCoordinatorError("Требуется подтверждение LINK_WORKFLOW")
        task = self._require_task(db, task_id)
        plan = self._plan_for_task(db, task)
        workflow_id = self._create_draft_workflow(db, plan, task, user_id)
        meta = dict(task.task_metadata or {})
        meta["workflow_link"] = {"workflow_id": workflow_id, "status": "draft"}
        task.task_metadata = meta
        db.commit()
        db.refresh(task)
        return {
            "task": repo.public_task_view(task),
            "workflow_link": {"workflow_id": workflow_id, "status": "draft"},
            "live_enabled": False,  # link НЕ запускает процессы/CRM/бюджет/публикации
            "note": "Создан черновик процесса. Процессы/CRM/бюджет/публикации не запускались.",
        }

    def _create_draft_workflow(
        self, db: Session, plan: ExecutionPlan, task: ExecutionTask, user_id: int | None
    ) -> int | None:
        """Создать draft workflow из задачи (status=draft, не запускает). Возвращает id или None."""
        try:
            from app.services.ai_workflow_manager_service import AIWorkflowManagerService

            result = AIWorkflowManagerService(
                settings=self._resolve_settings()
            ).create_workflow_from_goal(
                db,
                plan.project_id,
                name=task.title[:255],
                workflow_type=_WORKFLOW_TYPE_DEFAULT,
                goal=task.description or task.title,
                description=plan.title,
                status="draft",
                user_id=user_id,
            )
            # create_workflow_from_goal возвращает public_workflow_view (с ключом "id").
            return int(result["id"]) if isinstance(result, dict) and "id" in result else None
        except Exception as exc:  # noqa: BLE001 — не роняем link из-за нижнего слоя
            logger.warning("execution workflow link failed: %s", type(exc).__name__)
            return None

    # ------------------------------------------------------------------ #
    # Сигналы смежных слоёв                                              #
    # ------------------------------------------------------------------ #

    def _strategic_quarter_objectives(
        self, db: Session, strategic_plan_id: int | None
    ) -> list[dict[str, Any]]:
        """Квартальные цели исходного стратегического плана (Business Planner)."""
        if strategic_plan_id is None:
            return []
        try:
            from app.repositories import business_planner_repository as planner_repo

            return [
                planner_repo.public_objective_view(o)
                for o in planner_repo.list_objectives(db, strategic_plan_id)
            ]
        except Exception as exc:  # noqa: BLE001
            logger.warning("execution planner objectives failed: %s", type(exc).__name__)
            return []

    def _management_style_note(self, db: Session, execution_plan_id: int) -> str:
        """Заметка о стиле управления владельца (Chief of Staff Decision Memory)."""
        try:
            plan = repo.get_execution_plan(db, execution_plan_id)
            if plan is None:
                return ""
            from app.services.ai_chief_of_staff_service import AIChiefOfStaffService

            context = AIChiefOfStaffService(
                settings=self._resolve_settings()
            ).build_decision_context(db, plan.project_id)
            if context.get("restrictions"):
                return "Учтён стиль управления владельца — приоритет контролю рисков исполнения."
            return ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("execution management style failed: %s", type(exc).__name__)
            return ""

    def _has_unsatisfied_dependency(self, db: Session, task: ExecutionTask) -> bool:
        """Есть ли у задачи незакрытая зависимость (задача-предшественник не завершена)."""
        for dependency in repo.list_dependencies(db, task.id):
            if dependency.status == "satisfied":
                continue
            dep_id = dependency.depends_on_task_id
            if dep_id is None:
                # Внешняя/objective-зависимость без ссылки — незакрыта, если статус pending.
                if dependency.status != "satisfied":
                    return True
                continue
            dep_task = repo.get_task(db, dep_id)
            if dep_task is None or dep_task.status != "completed":
                return True
        return False

    @staticmethod
    def _blocker(task: ExecutionTask, blocker_type: str, detail: str) -> dict[str, Any]:
        return {
            "task_id": task.id,
            "title": task.title,
            "type": blocker_type,
            "detail": detail,
            "owner_user_id": task.owner_user_id,
            "status": task.status,
        }

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @staticmethod
    def _as_aware(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIExecutionCoordinatorError(f"Проект id={project_id} не найден")
        return project

    def _require_plan(self, db: Session, execution_plan_id: int) -> ExecutionPlan:
        plan = repo.get_execution_plan(db, execution_plan_id)
        if plan is None:
            raise AIExecutionCoordinatorError("План исполнения не найден")
        return plan

    def _require_objective(self, db: Session, objective_id: int) -> ExecutionObjective:
        objective = repo.get_objective(db, objective_id)
        if objective is None:
            raise AIExecutionCoordinatorError("Цель исполнения не найдена")
        return objective

    def _require_task(self, db: Session, task_id: int) -> ExecutionTask:
        task = repo.get_task(db, task_id)
        if task is None:
            raise AIExecutionCoordinatorError("Задача исполнения не найдена")
        return task

    def _plan_for_task(self, db: Session, task: ExecutionTask) -> ExecutionPlan:
        objective = self._require_objective(db, task.objective_id)
        return self._require_plan(db, objective.execution_plan_id)

    def _require_approved_plan_in_project(
        self, db: Session, strategic_plan_id: int, project_id: int
    ) -> Any:
        """Стратегический план существует, УТВЕРЖДЁН и принадлежит проекту (tenant isolation)."""
        from app.repositories import business_planner_repository as planner_repo

        plan = planner_repo.get_plan(db, strategic_plan_id)
        if plan is None:
            raise AIExecutionCoordinatorError("Стратегический план не найден")
        goal = planner_repo.get_goal(db, plan.goal_id)
        if goal is None or goal.project_id != project_id:
            raise AIExecutionCoordinatorError("Стратегический план не принадлежит этому проекту")
        if plan.status != "approved":
            raise AIExecutionCoordinatorError("Стратегический план не одобрен (approve)")
        return plan

    def _require_account_member(self, db: Session, plan: ExecutionPlan, owner_user_id: int) -> None:
        """Владелец задачи должен иметь доступ к аккаунту проекта (tenant isolation).

        FAIL CLOSED: любой сбой самой проверки — отказ (назначение НЕ проходит), а не пропуск.
        """
        from app.repositories import user_repository
        from app.services import saas_security_service as security

        account_id = plan.account_id
        if account_id is None:
            return
        try:
            user = user_repository.get_user_by_id(db, owner_user_id)
            allowed = user is not None and security.user_can_access_account(db, user, account_id)
        except Exception as exc:  # noqa: BLE001 — сбой проверки доступа → fail closed
            logger.warning("execution owner check failed: %s", type(exc).__name__)
            raise AIExecutionCoordinatorError("Не удалось проверить доступ владельца") from exc
        if not allowed:
            raise AIExecutionCoordinatorError("Владелец не имеет доступа к проекту")

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
            entity_type="execution_plan",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_execution_coordinator_service() -> AIExecutionCoordinatorService:
    """DI-фабрика AI Execution Coordinator."""
    return AIExecutionCoordinatorService()
