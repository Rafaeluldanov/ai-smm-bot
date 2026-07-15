"""AIChiefOfStaffService — AI Chief of Staff / Executive Assistant Layer (v0.7.1).

Персональный AI-ассистент владельца бизнеса. Ежедневно/еженедельно анализирует состояние
бизнеса (поверх AI Executive Layer, Growth Agent, Sales/Content/Analytics), формирует
executive briefing (изменения/риски/возможности/приоритеты), создаёт задачи для владельца и
запоминает его решения, подмешивая их контекстом в будущие AI-рекомендации.

Поток: **Analyze → Briefing → Recommend → Owner Approval → Task**. Это advisory + assistant.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ выполняет задачи автоматически; accept/complete лишь меняют статус;
- НЕ меняет бизнес/CRM/бюджет/продажи, НЕ запускает рекламу, НЕ публикует, НЕ включает live;
- decision memory лишь ДОБАВЛЯЕТ контекст рекомендациям, НЕ меняет другие слои напрямую;
- строго per-project; секретов нет; каждое изменение — в AuditLog; бесплатно (0 units).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import chief_of_staff_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.ai_business_task import AIBusinessTask
    from app.models.business_decision_memory import BusinessDecisionMemory
    from app.models.executive_briefing import ExecutiveBriefing
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Максимальная длина title (совпадает с моделями String(255)) — для дедупа задач.
_TITLE_MAX = 255
# Порог значимого изменения метрики между брифингами.
_CHANGE_EPS = 2.0


class AIChiefOfStaffError(Exception):
    """Ошибка Chief of Staff (нет проекта/брифинга/задачи/решения) — API → 400/404."""


class AIChiefOfStaffService:
    """AI помощник руководителя: analyze → briefing → task → decision memory."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Брифинги                                                           #
    # ------------------------------------------------------------------ #

    def generate_daily_briefing(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Ежедневный executive briefing + задачи для владельца."""
        self._require_project(db, project_id)
        plan = self._executive_plan(db, project_id, user_id)
        cur = dict(plan.get("current_state") or {})
        snapshot = self._snapshot(cur)
        owner_context = self.build_decision_context(db, project_id)

        prev = repo.get_latest_briefing(db, project_id, type="daily")
        prev_snapshot = self._prev_snapshot(prev)
        key_changes = self._daily_changes(snapshot, prev_snapshot, plan)
        risks = self._briefing_risks(plan, snapshot, prev_snapshot)
        opportunities = [str(o) for o in (plan.get("opportunities") or [])]
        recommended = [str(a) for a in (plan.get("priority_actions") or [])]
        summary = self._briefing_summary(plan, owner_context)

        briefing = repo.create_briefing(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            type="daily",
            title="Ежедневный брифинг руководителя",
            summary=summary,
            business_state={**snapshot, "owner_context": owner_context},
            key_changes=key_changes,
            risks=risks,
            opportunities=opportunities,
            recommended_actions=recommended,
            confidence_score=float(plan.get("confidence_score", 0.0) or 0.0),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_CHIEF_BRIEFING_GENERATED,
            project_id,
            user_id,
            briefing.id,
            {"type": "daily"},
        )
        return {
            "briefing": repo.public_briefing_view(briefing),
            "tasks": self._attach_tasks(db, project_id, briefing.id, plan, user_id),
        }

    def generate_weekly_review(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Weekly Business Review: последние 7 дней против предыдущих 7 дней."""
        self._require_project(db, project_id)
        plan = self._executive_plan(db, project_id, user_id)
        cur = dict(plan.get("current_state") or {})
        snapshot = self._snapshot(cur)
        owner_context = self.build_decision_context(db, project_id)

        now = datetime.now(UTC)
        this_week = self._window_metrics(db, project_id, now - timedelta(days=7), now)
        prev_week = self._window_metrics(
            db, project_id, now - timedelta(days=14), now - timedelta(days=7)
        )
        key_changes = self._weekly_changes(this_week, prev_week)
        plan_risks = [str(r) for r in (plan.get("risks") or [])]
        risks = self._weekly_risks(this_week, prev_week) + plan_risks
        opportunities = [str(o) for o in (plan.get("opportunities") or [])]
        recommended = [str(a) for a in (plan.get("priority_actions") or [])]

        briefing = repo.create_briefing(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            type="weekly",
            title="Еженедельный обзор бизнеса",
            summary=self._weekly_summary(this_week, prev_week, plan),
            business_state={
                **snapshot,
                "this_week": this_week,
                "prev_week": prev_week,
                "owner_context": owner_context,
            },
            key_changes=key_changes,
            risks=risks,
            opportunities=opportunities,
            recommended_actions=recommended,
            confidence_score=float(plan.get("confidence_score", 0.0) or 0.0),
        )
        self._write_audit(
            db,
            audit_actions.ACTION_CHIEF_BRIEFING_GENERATED,
            project_id,
            user_id,
            briefing.id,
            {"type": "weekly"},
        )
        return {
            "briefing": repo.public_briefing_view(briefing),
            "tasks": self._attach_tasks(db, project_id, briefing.id, plan, user_id),
        }

    def _attach_tasks(
        self,
        db: Session,
        project_id: int,
        briefing_id: int,
        plan: dict[str, Any],
        user_id: int | None,
    ) -> list[dict[str, Any]]:
        """Создать задачи из действий плана + привязать ВСЕ открытые задачи к новому брифингу.

        Иначе повторный брифинг (все действия задедуплены) оставил бы брифинг без задач,
        хотя открытые задачи ещё есть — get_latest_briefing показал бы пустой список.
        """
        self._create_tasks_from_actions(
            db, project_id, briefing_id, plan.get("actions") or [], user_id
        )
        open_tasks = repo.reassign_open_tasks_to_briefing(db, project_id, briefing_id)
        return [repo.public_task_view(t) for t in open_tasks]

    def get_latest_briefing(
        self, db: Session, project_id: int, type: str | None = None
    ) -> dict[str, Any]:
        """Последний брифинг проекта (+ его задачи)."""
        self._require_project(db, project_id)
        briefing = repo.get_latest_briefing(db, project_id, type=type)
        if briefing is None:
            return {"project_id": project_id, "has_briefing": False, "briefing": None, "tasks": []}
        return {
            "project_id": project_id,
            "has_briefing": True,
            "briefing": repo.public_briefing_view(briefing),
            "tasks": [
                repo.public_task_view(t)
                for t in repo.list_tasks(db, project_id, briefing_id=briefing.id)
            ],
        }

    def mark_briefing_viewed(
        self, db: Session, briefing_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отметить брифинг просмотренным."""
        briefing = self._require_briefing(db, briefing_id)
        repo.mark_viewed(db, briefing)
        return repo.public_briefing_view(briefing)

    # ------------------------------------------------------------------ #
    # Задачи владельца                                                   #
    # ------------------------------------------------------------------ #

    def list_tasks(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список задач владельца (по убыванию приоритета, опц. по статусу)."""
        self._require_project(db, project_id)
        return [repo.public_task_view(t) for t in repo.list_tasks(db, project_id, status=status)]

    def accept_task(self, db: Session, task_id: int, user_id: int | None = None) -> dict[str, Any]:
        """Одобрить задачу (status=accepted). НЕ выполняет действие."""
        task = self._require_task(db, task_id)
        if task.status in ("completed", "rejected"):
            raise AIChiefOfStaffError("Задача уже закрыта")
        if task.status == "accepted":  # повторный accept — no-op, чтобы не плодить аудит/re-stamp
            raise AIChiefOfStaffError("Задача уже одобрена")
        repo.accept_task(db, task, user_id=user_id)
        self._write_audit(
            db, audit_actions.ACTION_CHIEF_TASK_ACCEPTED, task.project_id, user_id, task.id, {}
        )
        return repo.public_task_view(task)

    def reject_task(self, db: Session, task_id: int, user_id: int | None = None) -> dict[str, Any]:
        """Отклонить задачу (status=rejected)."""
        task = self._require_task(db, task_id)
        if task.status == "completed":
            raise AIChiefOfStaffError("Задача уже завершена")
        if task.status == "rejected":
            raise AIChiefOfStaffError("Задача уже отклонена")
        repo.reject_task(db, task)
        self._write_audit(
            db, audit_actions.ACTION_CHIEF_TASK_REJECTED, task.project_id, user_id, task.id, {}
        )
        return repo.public_task_view(task)

    def complete_task(
        self, db: Session, task_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Зафиксировать выполнение задачи (status=completed). Внешних действий НЕТ."""
        task = self._require_task(db, task_id)
        if task.status == "rejected":
            raise AIChiefOfStaffError("Нельзя завершить отклонённую задачу")
        if task.status == "completed":
            raise AIChiefOfStaffError("Задача уже завершена")
        repo.complete_task(db, task)
        self._write_audit(
            db, audit_actions.ACTION_CHIEF_TASK_COMPLETED, task.project_id, user_id, task.id, {}
        )
        return repo.public_task_view(task)

    def _create_tasks_from_actions(
        self,
        db: Session,
        project_id: int,
        briefing_id: int,
        actions: list[dict[str, Any]],
        user_id: int | None,
    ) -> list[dict[str, Any]]:
        """Создать задачи владельца из приоритетных действий плана (impact×confidence)."""
        if not self._resolve_settings().chief_of_staff_enabled_effective:
            return []
        account_id = self._account_id(db, project_id)
        # Дедуп по (task_type, title) среди ВСЕХ статусов — завершённые/отклонённые не повторять.
        existing = {(t.task_type, t.title) for t in repo.list_tasks(db, project_id, limit=1000)}
        created: list[dict[str, Any]] = []
        for action in actions:
            task_type = str(action.get("action_type", "content"))
            title = str(action.get("title", "")).strip()[:_TITLE_MAX]
            if not title or (task_type, title) in existing:
                continue
            score = float(action.get("priority", 0.0) or 0.0)
            row = repo.create_task(
                db,
                project_id=project_id,
                account_id=account_id,
                briefing_id=briefing_id,
                task_type=task_type,
                title=title,
                priority=self._priority_bucket(score),
                priority_score=score,
                description=str(action.get("description", "")),
                reasoning=list(action.get("reasoning") or []),
                expected_impact=dict(action.get("expected_impact") or {}),
                source_modules=sorted({*(action.get("source_modules") or []), "chief_of_staff"}),
            )
            existing.add((task_type, title))
            created.append(repo.public_task_view(row))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_CHIEF_TASK_CREATED,
                project_id,
                user_id,
                briefing_id,
                {"created": len(created)},
            )
        return created

    @staticmethod
    def _priority_bucket(score: float) -> str:
        """0..100 → critical/high/medium/low."""
        if score >= 70:
            return "critical"
        if score >= 45:
            return "high"
        if score >= 25:
            return "medium"
        return "low"

    # ------------------------------------------------------------------ #
    # Память решений владельца                                           #
    # ------------------------------------------------------------------ #

    def save_decision_memory(
        self,
        db: Session,
        project_id: int,
        *,
        decision_type: str,
        key: str,
        value: dict[str, Any] | None = None,
        reason: str | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Запомнить решение владельца (предпочтение/стратегия/ограничение/одобрение)."""
        from app.models.business_decision_memory import KEY_MAX_LENGTH
        from app.models.executive_briefing import DECISION_TYPES

        self._require_project(db, project_id)
        if decision_type not in DECISION_TYPES:
            raise AIChiefOfStaffError("Неизвестный тип решения")
        # Нормализуем ДО [:KEY_MAX_LENGTH], чтобы поиск активной записи и хранение сравнивали
        # один и тот же ключ (иначе длинный key обходил бы «одна активная запись на key»).
        clean_key = (key or "").strip()[:KEY_MAX_LENGTH]
        if not clean_key:
            raise AIChiefOfStaffError("Укажите ключ решения")
        decision = repo.save_decision(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            decision_type=decision_type,
            key=clean_key,
            value=value or {},
            reason=reason,
            user_id=user_id,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_CHIEF_MEMORY_CREATED,
            project_id,
            user_id,
            decision.id,
            {"key": clean_key, "decision_type": decision_type},
        )
        return repo.public_decision_view(decision)

    def get_decisions(
        self, db: Session, project_id: int, active_only: bool = True
    ) -> list[dict[str, Any]]:
        """Список запомненных решений владельца."""
        self._require_project(db, project_id)
        return [
            repo.public_decision_view(d)
            for d in repo.get_decisions(db, project_id, active_only=active_only)
        ]

    def disable_decision(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Деактивировать запомненное решение (active=False). Запись не удаляется."""
        decision = self._require_decision(db, decision_id)
        repo.disable_decision(db, decision)
        self._write_audit(
            db,
            audit_actions.ACTION_CHIEF_MEMORY_DELETED,
            decision.project_id,
            user_id,
            decision.id,
            {"key": decision.key},
        )
        return repo.public_decision_view(decision)

    def build_decision_context(self, db: Session, project_id: int) -> dict[str, Any]:
        """Контекст владельца из активных решений — для будущих AI-рекомендаций.

        Лишь СОБИРАЕТ контекст (preferences/strategies/restrictions/approvals + по ключам),
        НЕ меняет AI Learning / Content Strategy / Campaign Manager напрямую.
        """
        decisions = repo.get_decisions(db, project_id, active_only=True)
        context: dict[str, Any] = {
            "preferences": [],
            "strategies": [],
            "restrictions": [],
            "approvals": [],
            "by_key": {},
        }
        bucket = {
            "preference": "preferences",
            "strategy": "strategies",
            "restriction": "restrictions",
            "approval": "approvals",
        }
        for d in decisions:
            entry = {"key": d.key, "value": dict(d.value or {}), "reason": d.reason}
            context[bucket.get(d.decision_type, "preferences")].append(entry)
            context["by_key"][d.key] = dict(d.value or {})
        return context

    def apply_decision_memory(
        self, db: Session, project_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Подготовить контекст решений владельца для AI-слоёв (advisory, без прямых изменений)."""
        self._require_project(db, project_id)
        context = self.build_decision_context(db, project_id)
        return {
            "project_id": project_id,
            "owner_context": context,
            "applies_to": ["ai_learning", "content_strategy", "campaign_manager"],
            "note": "Контекст добавляется к рекомендациям; бизнес/CRM/бюджет не меняются.",
        }

    # ------------------------------------------------------------------ #
    # Сводка                                                             #
    # ------------------------------------------------------------------ #

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка ассистента (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_chief_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Интеграции (Executive / Growth / Analytics)                        #
    # ------------------------------------------------------------------ #

    def _executive_plan(self, db: Session, project_id: int, user_id: int | None) -> dict[str, Any]:
        """Свежий исполнительный план (reuse AIExecutiveService, v0.7.0): состояние + действия."""
        try:
            from app.services.ai_executive_service import AIExecutiveService

            executive = AIExecutiveService(settings=self._resolve_settings())
            bundle = executive.create_executive_plan(db, project_id, user_id=user_id)
            plan = dict(bundle.get("plan") or {})
            plan["actions"] = bundle.get("actions") or []
            return plan
        except Exception as exc:  # noqa: BLE001 — брифинг не должен падать из-за нижнего слоя
            logger.warning("chief executive plan failed: %s", type(exc).__name__)
            return {"current_state": {}, "actions": [], "risks": [], "opportunities": []}

    def _window_metrics(
        self, db: Session, project_id: int, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Метрики окна [start, end): лиды/выручка (AILeadEvent) + охват/ER (analytics)."""
        try:
            from sqlalchemy import func, select

            from app.models.ai_lead_event import AILeadEvent
            from app.models.post_analytics_snapshot import PostAnalyticsSnapshot

            leads = db.execute(
                select(func.count(AILeadEvent.id)).where(
                    AILeadEvent.project_id == project_id,
                    AILeadEvent.created_at >= start,
                    AILeadEvent.created_at < end,
                )
            ).scalar_one()
            revenue = db.execute(
                select(func.coalesce(func.sum(AILeadEvent.value), 0.0)).where(
                    AILeadEvent.project_id == project_id,
                    AILeadEvent.created_at >= start,
                    AILeadEvent.created_at < end,
                )
            ).scalar_one()
            reach = db.execute(
                select(func.coalesce(func.sum(PostAnalyticsSnapshot.reach), 0)).where(
                    PostAnalyticsSnapshot.project_id == project_id,
                    PostAnalyticsSnapshot.snapshot_at >= start,
                    PostAnalyticsSnapshot.snapshot_at < end,
                )
            ).scalar_one()
            return {
                "leads": int(leads or 0),
                "revenue": round(float(revenue or 0.0), 2),
                "reach": int(reach or 0),
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("chief window metrics failed: %s", type(exc).__name__)
            return {"leads": 0, "revenue": 0.0, "reach": 0}

    # ------------------------------------------------------------------ #
    # Деривация текста брифинга                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _snapshot(cur: dict[str, Any]) -> dict[str, Any]:
        rev = cur.get("revenue_state", {}) if isinstance(cur.get("revenue_state"), dict) else {}
        sales = cur.get("sales_state", {}) if isinstance(cur.get("sales_state"), dict) else {}
        return {
            "business_health": cur.get("business_health", 0.0),
            "growth_score": cur.get("growth_score", 0.0),
            "total_revenue": rev.get("total_revenue", 0.0),
            "conversion_rate": rev.get("conversion_rate", 0.0),
            "best_platform": rev.get("best_platform", ""),
            "leads": sales.get("leads", 0),
        }

    @staticmethod
    def _prev_snapshot(prev: ExecutiveBriefing | None) -> dict[str, Any]:
        if prev is None or not isinstance(prev.business_state, dict):
            return {}
        return {k: v for k, v in prev.business_state.items() if k != "owner_context"}

    def _daily_changes(
        self, cur: dict[str, Any], prev: dict[str, Any], plan: dict[str, Any]
    ) -> list[str]:
        changes: list[str] = []
        best = str(cur.get("best_platform") or "")
        prev_best = str(prev.get("best_platform") or "")
        if best and prev and best != prev_best:
            changes.append(f"«{best}» стал главным источником заявок")
        elif best and not prev:
            changes.append(f"«{best}» — главный источник заявок")
        changes += self._metric_change(
            "Growth Score", cur.get("growth_score"), prev.get("growth_score")
        )
        changes += self._metric_change(
            "Выручка", cur.get("total_revenue"), prev.get("total_revenue")
        )
        if not changes:
            opps = plan.get("opportunities") or []
            if opps:
                changes.append(f"Ключевая точка роста: {opps[0]}")
            else:
                changes.append("Существенных изменений за день не выявлено")
        return changes

    @staticmethod
    def _metric_change(label: str, cur: Any, prev: Any) -> list[str]:
        if cur is None or prev is None:
            return []
        try:
            c, p = float(cur), float(prev)
        except (TypeError, ValueError):
            return []
        if c > p + _CHANGE_EPS:
            return [f"{label} вырос до {round(c, 1)}"]
        if c < p - _CHANGE_EPS:
            return [f"{label} снизился до {round(c, 1)}"]
        return []

    def _briefing_risks(
        self, plan: dict[str, Any], cur: dict[str, Any], prev: dict[str, Any]
    ) -> list[str]:
        risks = [str(r) for r in (plan.get("risks") or [])]
        c_conv, p_conv = cur.get("conversion_rate"), prev.get("conversion_rate")
        if c_conv is not None and p_conv is not None:
            try:
                if float(c_conv) < float(p_conv) - 0.01:
                    risks.append("Падает конверсия")
            except (TypeError, ValueError):
                pass
        return risks

    @staticmethod
    def _briefing_summary(plan: dict[str, Any], owner_context: dict[str, Any]) -> str:
        base = str(plan.get("executive_summary") or "").strip()
        if not base:
            base = "Собран ежедневный обзор бизнеса."
        restrictions = owner_context.get("restrictions") or []
        if restrictions:
            base += " (учтены ограничения владельца)"
        return base

    def _weekly_changes(self, this_week: dict[str, Any], prev_week: dict[str, Any]) -> list[str]:
        changes: list[str] = []
        for label, key in (("Лиды", "leads"), ("Выручка", "revenue"), ("Охват", "reach")):
            changes += self._week_delta(label, this_week.get(key), prev_week.get(key))
        if not changes:
            changes.append("Показатели недели стабильны относительно прошлой")
        return changes

    @staticmethod
    def _week_delta(label: str, cur: Any, prev: Any) -> list[str]:
        c, p = float(cur or 0), float(prev or 0)
        if c == p:
            return []
        direction = "вырос" if c > p else "снизился"
        if p > 0:
            pct = round((c - p) / p * 100)
            return [f"{label}: {direction} на {abs(pct)}% ({round(p, 1)} → {round(c, 1)})"]
        if c > 0:
            return [f"{label}: {direction} ({round(p, 1)} → {round(c, 1)})"]
        return []

    @staticmethod
    def _weekly_risks(this_week: dict[str, Any], prev_week: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        if float(this_week.get("revenue", 0) or 0) < float(prev_week.get("revenue", 0) or 0):
            risks.append("Выручка за неделю снизилась")
        if float(this_week.get("leads", 0) or 0) < float(prev_week.get("leads", 0) or 0):
            risks.append("Поток лидов за неделю снизился")
        return risks

    @staticmethod
    def _weekly_summary(
        this_week: dict[str, Any], prev_week: dict[str, Any], plan: dict[str, Any]
    ) -> str:
        base = str(plan.get("executive_summary") or "").strip()
        lead_line = (
            f"За неделю: {this_week.get('leads', 0)} лидов, выручка {this_week.get('revenue', 0)} "
            f"(было {prev_week.get('leads', 0)} лидов / {prev_week.get('revenue', 0)})."
        )
        return f"{lead_line} {base}".strip()

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIChiefOfStaffError(f"Проект id={project_id} не найден")
        return project

    def _require_briefing(self, db: Session, briefing_id: int) -> ExecutiveBriefing:
        briefing = repo.get_briefing(db, briefing_id)
        if briefing is None:
            raise AIChiefOfStaffError("Брифинг не найден")
        return briefing

    def _require_task(self, db: Session, task_id: int) -> AIBusinessTask:
        task = repo.get_task(db, task_id)
        if task is None:
            raise AIChiefOfStaffError("Задача не найдена")
        return task

    def _require_decision(self, db: Session, decision_id: int) -> BusinessDecisionMemory:
        decision = repo.get_decision(db, decision_id)
        if decision is None:
            raise AIChiefOfStaffError("Решение не найдено")
        return decision

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
            entity_type="executive_briefing",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_chief_of_staff_service() -> AIChiefOfStaffService:
    """DI-фабрика AI Chief of Staff / Executive Assistant Layer."""
    return AIChiefOfStaffService()
