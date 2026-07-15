"""AIDecisionEngineService — AI Decision Engine (v0.7.4).

Выявляет бизнес-проблему, строит варианты решений (сценарии), оценивает и сравнивает их
эффект/риск/стоимость и рекомендует лучший. Это аналитический и рекомендательный слой.

Поток: **Problem → Decision Options → Scenario Analysis → AI Recommendation → Owner Approval**.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- НЕ применяет решения автоматически; select/reject/accept лишь меняют статус;
- НЕ меняет бизнес/CRM/бюджет/продажи, НЕ запускает рекламу, НЕ публикует, НЕ включает live;
- apply возможен ТОЛЬКО при status=accepted И подтверждении APPLY_DECISION → создаёт лишь
  ЧЕРНОВИК процесса (draft workflow); строго per-project; секретов нет; бесплатно (0 units);
- каждое изменение (created/analyzed/scenario_*/accepted/applied) пишется в AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import decision_repository as repo
from app.repositories import project_repository
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.ai_decision import AIDecision
    from app.models.decision_scenario import DecisionScenario
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

# Подтверждение, обязательное для применения решения.
APPLY_CONFIRMATION = "APPLY_DECISION"

# Порог значимого риска (для оценки соответствия предпочтениям владельца).
_HIGH_RISK = 35.0

# Тип решения → тип процесса (для draft workflow при apply).
_DECISION_TO_WORKFLOW: dict[str, str] = {
    "growth": "growth",
    "revenue": "sales",
    "marketing": "marketing",
    "sales": "sales",
    "content": "content",
    "efficiency": "operational",
    "operational": "operational",
}

# Шаблоны сценариев по типу решения: (title, description, impact, confidence, risk, cost).
_SCENARIO_TEMPLATES: dict[str, list[tuple[str, str, float, float, float, str]]] = {
    "sales": [
        (
            "Усилить продающий контент и CTA",
            "Больше офферов и призывов к действию",
            70,
            75,
            20,
            "low",
        ),
        ("Запустить кампанию доверия", "Кейсы и отзывы для роста доверия", 85, 65, 35, "medium"),
        ("Оптимизировать путь лида", "Упростить путь заявка → сделка", 60, 70, 15, "low"),
    ],
    "revenue": [
        ("Масштабировать работающие каналы", "Усилить каналы с выручкой", 78, 72, 22, "low"),
        ("Запустить кампанию доверия", "Повысить доверие и конверсию", 84, 64, 36, "medium"),
        ("Поднять средний чек офферами", "Пакеты/апселлы в контенте", 66, 68, 20, "low"),
    ],
    "growth": [
        ("Масштабировать работающий канал", "Больше активности в лучшем канале", 75, 72, 25, "low"),
        ("Запустить новую кампанию роста", "Отдельная кампания под рост", 85, 60, 40, "medium"),
        ("Усилить контент по деньгам", "Масштабировать темы, дающие выручку", 68, 74, 18, "low"),
    ],
    "marketing": [
        ("Запустить кампанию доверия", "Кейсы/отзывы как основа кампании", 82, 70, 30, "medium"),
        ("Усилить работающий канал", "Сфокусироваться на лучшем канале", 70, 76, 20, "low"),
        ("Пересмотреть контент-план", "Обновить темы и форматы", 60, 70, 15, "low"),
    ],
    "content": [
        ("Масштабировать работающие темы", "Больше контента по лучшим темам", 72, 78, 15, "low"),
        ("Обновить слабые темы", "Заменить темы без отклика", 60, 66, 20, "low"),
        ("Сменить форматы контента", "Новые форматы для вовлечения", 68, 60, 30, "medium"),
    ],
    "efficiency": [
        ("Улучшить CTA и офферы", "Повысить конверсию контента", 66, 76, 15, "low"),
        ("Создать новую кампанию", "Собрать заявки отдельной кампанией", 80, 60, 38, "medium"),
        ("Изменить контентную стратегию", "Перестроить темы под конверсию", 70, 64, 25, "medium"),
    ],
    "operational": [
        ("Назначить ответственных за этапы", "Закрепить владельцев процессов", 60, 80, 10, "low"),
        ("Снять блокеры процессов", "Разблокировать застрявшую работу", 75, 72, 20, "low"),
        ("Пересмотреть сроки и приоритеты", "Актуализировать план", 55, 74, 12, "low"),
    ],
}


class AIDecisionEngineError(Exception):
    """Ошибка Decision Engine (нет проекта/решения/сценария/подтверждения) — API → 400/404."""


class AIDecisionEngineService:
    """AI-движок решений: problem → scenarios → evaluate → recommend → approve → draft."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Решения                                                            #
    # ------------------------------------------------------------------ #

    def create_decision(
        self,
        db: Session,
        project_id: int,
        *,
        decision_type: str,
        title: str,
        problem_statement: str | None = None,
        objective: str | None = None,
        priority: str = "medium",
        source_risk_id: int | None = None,
        source_action_id: int | None = None,
        source_task_id: int | None = None,
        user_id: int | None = None,
    ) -> dict[str, Any]:
        """Создать решение (из Operations Risk / Business Action / Chief Task / вручную)."""
        from app.models.ai_decision import DECISION_PRIORITIES, DECISION_TYPES

        self._require_project(db, project_id)
        if decision_type not in DECISION_TYPES:
            raise AIDecisionEngineError("Неизвестный тип решения")
        if priority not in DECISION_PRIORITIES:
            raise AIDecisionEngineError("Неизвестный приоритет решения")
        clean_title = (title or "").strip()

        context: dict[str, Any] = {}
        if source_risk_id is not None:
            context["source_risk_id"] = source_risk_id
        if source_action_id is not None:
            context["source_action_id"] = source_action_id
        if source_task_id is not None:
            context["source_task_id"] = source_task_id
        # Предпочтения владельца (Chief of Staff) — учитываются при оценке.
        owner_context = self._owner_context(db, project_id)
        if owner_context.get("restrictions"):
            context["owner_risk_averse"] = True
            context["owner_restrictions"] = [r.get("key") for r in owner_context["restrictions"]]
        if not clean_title:
            raise AIDecisionEngineError("Укажите название решения")

        decision = repo.create_decision(
            db,
            project_id=project_id,
            account_id=self._account_id(db, project_id),
            decision_type=decision_type,
            title=clean_title,
            priority=priority,
            problem_statement=problem_statement,
            objective=objective,
            context=context,
        )
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_CREATED,
            project_id,
            user_id,
            decision.id,
            {"decision_type": decision_type},
        )
        return repo.public_decision_view(decision)

    def list_decisions(
        self, db: Session, project_id: int, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Список решений проекта (по статусу)."""
        self._require_project(db, project_id)
        return [
            repo.public_decision_view(d) for d in repo.list_decisions(db, project_id, status=status)
        ]

    def get_decision(self, db: Session, decision_id: int) -> dict[str, Any]:
        """Решение + сценарии + сигналы."""
        decision = self._require_decision(db, decision_id)
        return {
            "decision": repo.public_decision_view(decision),
            "scenarios": [
                repo.public_scenario_view(s) for s in repo.list_scenarios(db, decision_id)
            ],
            "signals": [repo.public_signal_view(s) for s in repo.list_signals(db, decision_id)],
        }

    def get_history(self, db: Session, project_id: int) -> list[dict[str, Any]]:
        """История решений проекта."""
        self._require_project(db, project_id)
        return [repo.public_decision_view(d) for d in repo.get_decision_history(db, project_id)]

    def get_summary(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка Decision Engine (для UI-состояния)."""
        self._require_project(db, project_id)
        return repo.build_decision_summary(db, project_id)

    # ------------------------------------------------------------------ #
    # Анализ: сигналы → сценарии → оценка → рекомендация                 #
    # ------------------------------------------------------------------ #

    def analyze_decision(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Полный анализ: собрать сигналы → построить сценарии → оценить → рекомендовать."""
        decision = self._require_decision(db, decision_id)
        # Нельзя откатывать уже одобренное/применённое решение назад (стёрло бы выбор владельца).
        if decision.status in ("accepted", "applied"):
            raise AIDecisionEngineError(
                "Решение уже одобрено/применено — повторный анализ запрещён"
            )
        repo.update_decision(db, decision, status="analyzing")
        self.collect_signals(db, decision_id, user_id)
        self.generate_scenarios(db, decision_id, user_id)
        self.evaluate_scenarios(db, decision_id)
        recommendation = self.recommend_best_scenario(db, decision_id, user_id)
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_ANALYZED,
            decision.project_id,
            user_id,
            decision.id,
            {"scenarios": len(repo.list_scenarios(db, decision_id))},
        )
        return {
            "decision": repo.public_decision_view(self._require_decision(db, decision_id)),
            "scenarios": [
                repo.public_scenario_view(s) for s in repo.list_scenarios(db, decision_id)
            ],
            "recommendation": recommendation,
        }

    def collect_signals(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Собрать взвешенные сигналы из смежных слоёв (Operations/Growth/Sales/Workflow)."""
        decision = self._require_decision(db, decision_id)
        if repo.list_signals(db, decision_id):
            return [repo.public_signal_view(s) for s in repo.list_signals(db, decision_id)]
        created: list[dict[str, Any]] = []
        for source, signal_type, value, weight in self._gather_signals(db, decision.project_id):
            row = repo.create_signal(
                db,
                decision_id=decision_id,
                source_module=source,
                signal_type=signal_type,
                value=value,
                weight=weight,
            )
            created.append(repo.public_signal_view(row))
        return created

    def generate_scenarios(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> list[dict[str, Any]]:
        """Построить варианты решения (сценарии) по типу решения. Дедуп по заголовку."""
        decision = self._require_decision(db, decision_id)
        if not self._resolve_settings().decision_engine_enabled_effective:
            return []
        templates = _SCENARIO_TEMPLATES.get(decision.decision_type, _SCENARIO_TEMPLATES["growth"])
        existing = {s.title.strip().lower() for s in repo.list_scenarios(db, decision_id)}
        created: list[dict[str, Any]] = []
        for title, description, impact, confidence, risk, cost in templates:
            if title.strip().lower() in existing:
                continue
            scenario = repo.create_scenario(
                db,
                decision_id=decision_id,
                title=title,
                description=description,
                assumptions=[f"Тип решения: {decision.decision_type}"],
                expected_impact={"impact": impact},
                risk_analysis={"risk": risk, "level": self._risk_level(risk)},
                cost_estimate={"level": cost},
                confidence_score=confidence,
            )
            existing.add(title.strip().lower())
            created.append(repo.public_scenario_view(scenario))
        if created:
            self._write_audit(
                db,
                audit_actions.ACTION_DECISION_SCENARIO_CREATED,
                decision.project_id,
                user_id,
                decision_id,
                {"created": len(created)},
            )
        return created

    def evaluate_scenarios(self, db: Session, decision_id: int) -> list[dict[str, Any]]:
        """Оценить сценарии: Decision Score = impact × confidence − risk penalty → 0..100."""
        decision = self._require_decision(db, decision_id)
        risk_averse = bool((decision.context or {}).get("owner_risk_averse"))
        out: list[dict[str, Any]] = []
        for scenario in repo.list_scenarios(db, decision_id):
            # rejected пропускаем целиком (score не считаем); selected сохраняет статус, но
            # его score пересчитываем.
            if scenario.status == "rejected":
                continue
            impact = float((scenario.expected_impact or {}).get("impact", 0.0) or 0.0)
            confidence = float(scenario.confidence_score or 0.0)
            risk = float((scenario.risk_analysis or {}).get("risk", 0.0) or 0.0)
            score = self._decision_score(impact, confidence, risk, risk_averse)
            scenario.expected_impact = {**(scenario.expected_impact or {}), "score": score}
            new_status = scenario.status if scenario.status == "selected" else "evaluated"
            repo.set_scenario_status(db, scenario, new_status)
            out.append(repo.public_scenario_view(scenario))
        return out

    @staticmethod
    def _decision_score(impact: float, confidence: float, risk: float, risk_averse: bool) -> float:
        """Decision Score = impact × (confidence/100) − risk penalty, clamp [0..100]."""
        risk_weight = 0.5 if risk_averse else 0.3  # предпочтения владельца: осторожнее к риску
        raw = impact * (confidence / 100.0) - risk_weight * risk
        return round(max(0.0, min(100.0, raw)), 1)

    def recommend_best_scenario(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Выбрать лучший сценарий (максимальный Decision Score) и рекомендовать его."""
        decision = self._require_decision(db, decision_id)
        scenarios = [s for s in repo.list_scenarios(db, decision_id) if s.status != "rejected"]
        if not scenarios:
            repo.update_decision(db, decision, status="reviewed")
            return {"scenario": None, "score": 0.0, "reason": "Нет сценариев для рекомендации"}
        # Явный выбор владельца имеет приоритет над максимальным score.
        selected = [s for s in scenarios if s.status == "selected"]
        best = (
            selected[0]
            if selected
            else max(
                scenarios, key=lambda s: float((s.expected_impact or {}).get("score", 0.0) or 0.0)
            )
        )
        best_score = round(float((best.expected_impact or {}).get("score", 0.0) or 0.0), 1)
        repo.update_decision(
            db,
            decision,
            status="recommended",
            recommended_scenario_id=best.id,
            confidence_score=best_score,
        )
        return {
            "scenario": repo.public_scenario_view(best),
            "score": best_score,
            "reason": self._recommendation_reason(best),
        }

    @staticmethod
    def _recommendation_reason(scenario: DecisionScenario) -> str:
        risk = float((scenario.risk_analysis or {}).get("risk", 0.0) or 0.0)
        if risk < _HIGH_RISK:
            return "Максимальный эффект при приемлемом риске"
        return "Наибольший ожидаемый эффект; риск выше среднего — контролируйте выполнение"

    # ------------------------------------------------------------------ #
    # Объяснение                                                         #
    # ------------------------------------------------------------------ #

    def explain_decision(self, db: Session, decision_id: int) -> dict[str, Any]:
        """Объяснение владельцу: почему AI выбрал этот путь."""
        decision = self._require_decision(db, decision_id)
        reasons: list[str] = []
        if decision.problem_statement:
            reasons.append(f"Проблема: {decision.problem_statement}")
        best_id = decision.recommended_scenario_id
        best = repo.get_scenario(db, best_id) if best_id is not None else None
        if best is not None:
            score = float((best.expected_impact or {}).get("score", 0.0) or 0.0)
            reasons.append(
                f"Рекомендован «{best.title}» — Decision Score {round(score, 1)}/100 "
                f"(эффект {best.expected_impact.get('impact', '—')}, риск "
                f"{best.risk_analysis.get('risk', '—')}, уверенность {best.confidence_score})."
            )
        if (decision.context or {}).get("owner_risk_averse"):
            reasons.append("Учтены предпочтения владельца — приоритет менее рискованным вариантам.")
        if not reasons:
            reasons.append("Запустите анализ (analyze), чтобы собрать сценарии и рекомендацию.")
        return {"decision_id": decision_id, "reasons": reasons}

    # ------------------------------------------------------------------ #
    # Выбор сценария / review                                            #
    # ------------------------------------------------------------------ #

    def select_scenario(
        self, db: Session, scenario_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Выбрать сценарий владельцем (status=selected + привязка к решению)."""
        scenario = self._require_scenario(db, scenario_id)
        decision = self._require_decision(db, scenario.decision_id)
        # Выбранным может быть только ОДИН сценарий: сбрасываем прежний выбор в evaluated,
        # иначе повторный analyze мог бы вернуть более ранний выбор владельца.
        for other in repo.list_scenarios(db, decision.id):
            if other.id != scenario.id and other.status == "selected":
                repo.set_scenario_status(db, other, "evaluated")
        repo.select_scenario(db, scenario)
        repo.update_decision(db, decision, recommended_scenario_id=scenario.id)
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_SCENARIO_SELECTED,
            decision.project_id,
            user_id,
            scenario.id,
            {},
        )
        return repo.public_scenario_view(scenario)

    def reject_scenario(
        self, db: Session, scenario_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Отклонить сценарий (status=rejected)."""
        scenario = self._require_scenario(db, scenario_id)
        decision = self._require_decision(db, scenario.decision_id)
        was_recommended = decision.recommended_scenario_id == scenario.id
        repo.reject_scenario(db, scenario)
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_SCENARIO_REJECTED,
            decision.project_id,
            user_id,
            scenario.id,
            {},
        )
        # Если отклонён рекомендованный сценарий (и решение ещё не одобрено) — пересобрать
        # рекомендацию среди выживших, чтобы recommended_scenario_id не указывал на rejected.
        if was_recommended and decision.status in ("draft", "analyzing", "reviewed", "recommended"):
            self.recommend_best_scenario(db, decision.id, user_id)
        return repo.public_scenario_view(scenario)

    # ------------------------------------------------------------------ #
    # Approve / Apply                                                    #
    # ------------------------------------------------------------------ #

    def accept_decision(
        self, db: Session, decision_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Одобрить решение (status=accepted). НЕ выполняет."""
        decision = self._require_decision(db, decision_id)
        if decision.status not in ("recommended", "reviewed"):
            raise AIDecisionEngineError("Сначала проанализируйте решение (analyze)")
        repo.update_decision(db, decision, status="accepted")
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_ACCEPTED,
            decision.project_id,
            user_id,
            decision.id,
            {},
        )
        return repo.public_decision_view(decision)

    def apply_decision(
        self, db: Session, decision_id: int, confirmation: str = "", user_id: int | None = None
    ) -> dict[str, Any]:
        """Применить решение. ТОЛЬКО status=accepted И confirmation=APPLY_DECISION.

        Создаёт лишь ЧЕРНОВИК процесса (draft workflow). НЕ запускает процессы, НЕ меняет
        CRM/бюджет, НЕ публикует, НЕ включает live.
        """
        decision = self._require_decision(db, decision_id)
        if decision.status != "accepted":
            raise AIDecisionEngineError("Сначала одобрите решение (accept)")
        if confirmation != APPLY_CONFIRMATION:
            raise AIDecisionEngineError("Требуется подтверждение APPLY_DECISION")
        draft_created = self._apply_draft_workflow(db, decision, user_id)
        repo.update_decision(db, decision, status="applied")
        self._write_audit(
            db,
            audit_actions.ACTION_DECISION_APPLIED,
            decision.project_id,
            user_id,
            decision.id,
            {"draft_workflow": draft_created},
        )
        return {
            "decision": repo.public_decision_view(decision),
            "applied": {"draft_workflow": draft_created},
            "live_enabled": False,  # apply НЕ запускает процессы/CRM/бюджет/публикации/live
            "note": "Создан черновик процесса. Процессы/CRM/бюджет/публикации не запускались.",
        }

    def _apply_draft_workflow(self, db: Session, decision: AIDecision, user_id: int | None) -> bool:
        """Создать ЧЕРНОВИК процесса из рекомендованного сценария (status=draft, не запускает)."""
        try:
            from app.services.ai_workflow_manager_service import AIWorkflowManagerService

            scenario = (
                repo.get_scenario(db, decision.recommended_scenario_id)
                if decision.recommended_scenario_id is not None
                else None
            )
            # Не строим черновик из отклонённого сценария (защита на случай reject после accept).
            if scenario is not None and scenario.status == "rejected":
                scenario = None
            name = scenario.title if scenario is not None else f"Решение: {decision.title}"
            workflow_type = _DECISION_TO_WORKFLOW.get(decision.decision_type, "custom")
            AIWorkflowManagerService(settings=self._resolve_settings()).create_workflow_from_goal(
                db,
                decision.project_id,
                name=name[:255],
                workflow_type=workflow_type,
                goal=decision.objective or decision.title,
                description=decision.problem_statement,
                status="draft",
                user_id=user_id,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — не роняем apply из-за нижнего слоя
            logger.warning("decision draft workflow failed: %s", type(exc).__name__)
            return False

    # ------------------------------------------------------------------ #
    # Сбор сигналов + контекст владельца                                 #
    # ------------------------------------------------------------------ #

    def _gather_signals(
        self, db: Session, project_id: int
    ) -> list[tuple[str, str, dict[str, Any], float]]:
        """Собрать сигналы из смежных слоёв (каждый в try/except)."""
        signals: list[tuple[str, str, dict[str, Any], float]] = []
        # Operations Center (v0.7.3): health + открытые риски.
        try:
            from app.repositories import operations_repository as ops_repo

            snapshot = ops_repo.get_latest_snapshot(db, project_id)
            open_risks = ops_repo.list_active_risks(db, project_id)
            if snapshot is not None:
                signals.append(
                    (
                        "operations_center",
                        "health",
                        {"health_score": snapshot.health_score, "risk_count": len(open_risks)},
                        2.0 if open_risks else 1.0,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision operations signal failed: %s", type(exc).__name__)
        # Growth / Sales (v0.7.0 executive state).
        try:
            from app.services.ai_executive_service import AIExecutiveService

            state = AIExecutiveService(settings=self._resolve_settings()).analyze_business_state(
                db, project_id
            )
            rev = state.get("revenue_state", {})
            signals.append(
                ("growth_agent", "growth_score", {"value": state.get("growth_score", 0.0)}, 1.5)
            )
            signals.append(
                (
                    "sales_intelligence",
                    "revenue",
                    {
                        "revenue": rev.get("total_revenue", 0.0),
                        "conversion": rev.get("conversion_rate", 0.0),
                    },
                    1.5,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision executive signal failed: %s", type(exc).__name__)
        # Workflow Manager (v0.7.2): активные процессы + блокеры.
        try:
            from app.repositories import workflow_repository as wf_repo

            active = wf_repo.get_active_workflows(db, project_id)
            blockers = sum(len(wf_repo.list_blockers(db, w.id, status="open")) for w in active)
            signals.append(
                (
                    "workflow_manager",
                    "execution",
                    {"active_workflows": len(active), "open_blockers": blockers},
                    1.0,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision workflow signal failed: %s", type(exc).__name__)
        # Campaign Manager: число активных кампаний.
        try:
            from app.repositories import ai_campaign_repository

            campaigns = ai_campaign_repository.list_campaigns(db, project_id)
            active_campaigns = sum(1 for c in campaigns if c.status in ("active", "review"))
            signals.append(("campaign_manager", "campaigns", {"active": active_campaigns}, 1.0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision campaign signal failed: %s", type(exc).__name__)
        return signals

    def _owner_context(self, db: Session, project_id: int) -> dict[str, Any]:
        """Контекст решений владельца (Chief of Staff, v0.7.1) — предпочтения/ограничения."""
        try:
            from app.services.ai_chief_of_staff_service import AIChiefOfStaffService

            return AIChiefOfStaffService(settings=self._resolve_settings()).build_decision_context(
                db, project_id
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("decision owner context failed: %s", type(exc).__name__)
            return {}

    @staticmethod
    def _risk_level(risk: float) -> str:
        if risk >= 60:
            return "high"
        if risk >= 30:
            return "medium"
        return "low"

    # ------------------------------------------------------------------ #
    # Инфраструктура                                                     #
    # ------------------------------------------------------------------ #

    def _require_project(self, db: Session, project_id: int) -> Any:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise AIDecisionEngineError(f"Проект id={project_id} не найден")
        return project

    def _require_decision(self, db: Session, decision_id: int) -> AIDecision:
        decision = repo.get_decision(db, decision_id)
        if decision is None:
            raise AIDecisionEngineError("Решение не найдено")
        return decision

    def _require_scenario(self, db: Session, scenario_id: int) -> DecisionScenario:
        scenario = repo.get_scenario(db, scenario_id)
        if scenario is None:
            raise AIDecisionEngineError("Сценарий не найден")
        return scenario

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
            entity_type="ai_decision",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_decision_engine_service() -> AIDecisionEngineService:
    """DI-фабрика AI Decision Engine."""
    return AIDecisionEngineService()
