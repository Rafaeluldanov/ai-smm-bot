"""Репозиторий AI Decision Engine (v0.7.4): решения + сценарии + сигналы.

Публичные представления без секретов/токенов. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ai_decision import AIDecision
from app.models.decision_scenario import DecisionScenario
from app.models.decision_signal import DecisionSignal

# Поля решения, которые можно обновлять (whitelist).
_DECISION_FIELDS: frozenset[str] = frozenset(
    {
        "status",
        "priority",
        "title",
        "problem_statement",
        "objective",
        "recommended_scenario_id",
        "confidence_score",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Decisions                                                                    #
# ---------------------------------------------------------------------------- #


def create_decision(
    db: Session,
    *,
    project_id: int,
    account_id: int | None,
    decision_type: str,
    title: str,
    status: str = "draft",
    priority: str = "medium",
    problem_statement: str | None = None,
    objective: str | None = None,
    context: dict[str, Any] | None = None,
) -> AIDecision:
    """Создать AI-решение (status=draft по умолчанию)."""
    decision = AIDecision(
        project_id=project_id,
        account_id=account_id,
        decision_type=decision_type,
        status=status,
        priority=priority,
        title=title[:255],
        problem_statement=problem_statement,
        objective=objective,
        context=context or {},
        confidence_score=0.0,
    )
    db.add(decision)
    db.commit()
    db.refresh(decision)
    return decision


def get_decision(db: Session, decision_id: int) -> AIDecision | None:
    """Решение по id (или None)."""
    return db.get(AIDecision, decision_id)


def list_decisions(
    db: Session, project_id: int, *, status: str | None = None, limit: int = 200
) -> list[AIDecision]:
    """Решения проекта (свежие сверху), опционально по статусу."""
    stmt = select(AIDecision).where(AIDecision.project_id == project_id)
    if status is not None:
        stmt = stmt.where(AIDecision.status == status)
    stmt = stmt.order_by(AIDecision.id.desc()).limit(max(1, min(limit, 1000)))
    return list(db.execute(stmt).scalars().all())


def get_decision_history(db: Session, project_id: int, *, limit: int = 50) -> list[AIDecision]:
    """История решений проекта (свежие сверху)."""
    return list_decisions(db, project_id, limit=limit)


def update_decision(db: Session, decision: AIDecision, **fields: Any) -> AIDecision:
    """Обновить поля решения (только whitelist)."""
    for key, value in fields.items():
        if key in _DECISION_FIELDS:
            setattr(decision, key, value)
    db.commit()
    db.refresh(decision)
    return decision


# ---------------------------------------------------------------------------- #
# Scenarios                                                                     #
# ---------------------------------------------------------------------------- #


def create_scenario(
    db: Session,
    *,
    decision_id: int,
    title: str,
    description: str | None = None,
    assumptions: list[Any] | None = None,
    expected_impact: dict[str, Any] | None = None,
    risk_analysis: dict[str, Any] | None = None,
    cost_estimate: dict[str, Any] | None = None,
    confidence_score: float = 0.0,
    status: str = "generated",
) -> DecisionScenario:
    """Создать сценарий (вариант решения)."""
    scenario = DecisionScenario(
        decision_id=decision_id,
        title=title[:255],
        description=description,
        assumptions=assumptions or [],
        expected_impact=expected_impact or {},
        risk_analysis=risk_analysis or {},
        cost_estimate=cost_estimate or {},
        confidence_score=float(confidence_score or 0.0),
        status=status,
    )
    db.add(scenario)
    db.commit()
    db.refresh(scenario)
    return scenario


def get_scenario(db: Session, scenario_id: int) -> DecisionScenario | None:
    """Сценарий по id (или None)."""
    return db.get(DecisionScenario, scenario_id)


def list_scenarios(db: Session, decision_id: int, *, limit: int = 200) -> list[DecisionScenario]:
    """Сценарии решения по убыванию оценки (confidence как прокси до evaluate)."""
    stmt = (
        select(DecisionScenario)
        .where(DecisionScenario.decision_id == decision_id)
        .order_by(DecisionScenario.id.asc())
        .limit(max(1, min(limit, 1000)))
    )
    return list(db.execute(stmt).scalars().all())


def set_scenario_status(
    db: Session, scenario: DecisionScenario, status: str, *, confidence_score: float | None = None
) -> DecisionScenario:
    """Сменить статус сценария (+опционально уверенность)."""
    scenario.status = status
    if confidence_score is not None:
        scenario.confidence_score = float(confidence_score)
    db.commit()
    db.refresh(scenario)
    return scenario


def select_scenario(db: Session, scenario: DecisionScenario) -> DecisionScenario:
    """Пометить сценарий выбранным (status=selected)."""
    return set_scenario_status(db, scenario, "selected")


def reject_scenario(db: Session, scenario: DecisionScenario) -> DecisionScenario:
    """Отклонить сценарий (status=rejected)."""
    return set_scenario_status(db, scenario, "rejected")


# ---------------------------------------------------------------------------- #
# Signals                                                                       #
# ---------------------------------------------------------------------------- #


def create_signal(
    db: Session,
    *,
    decision_id: int,
    source_module: str,
    signal_type: str,
    value: dict[str, Any] | None = None,
    weight: float = 1.0,
) -> DecisionSignal:
    """Создать взвешенный сигнал решения."""
    signal = DecisionSignal(
        decision_id=decision_id,
        source_module=source_module,
        signal_type=signal_type,
        value=value or {},
        weight=float(weight or 1.0),
    )
    db.add(signal)
    db.commit()
    db.refresh(signal)
    return signal


def list_signals(db: Session, decision_id: int, *, limit: int = 500) -> list[DecisionSignal]:
    """Сигналы решения (по порядку создания)."""
    stmt = (
        select(DecisionSignal)
        .where(DecisionSignal.decision_id == decision_id)
        .order_by(DecisionSignal.id.asc())
        .limit(max(1, min(limit, 2000)))
    )
    return list(db.execute(stmt).scalars().all())


# ---------------------------------------------------------------------------- #
# Public views                                                                 #
# ---------------------------------------------------------------------------- #


def public_decision_view(decision: AIDecision) -> dict[str, Any]:
    """Безопасное представление решения (без секретов)."""
    return {
        "id": decision.id,
        "project_id": decision.project_id,
        "decision_type": decision.decision_type,
        "status": decision.status,
        "priority": decision.priority,
        "title": decision.title,
        "problem_statement": decision.problem_statement,
        "objective": decision.objective,
        "context": dict(decision.context or {}),
        "recommended_scenario_id": decision.recommended_scenario_id,
        "confidence_score": round(float(decision.confidence_score or 0.0), 1),
        "created_at": decision.created_at.isoformat() if decision.created_at else None,
    }


def public_scenario_view(scenario: DecisionScenario) -> dict[str, Any]:
    """Безопасное представление сценария."""
    return {
        "id": scenario.id,
        "decision_id": scenario.decision_id,
        "title": scenario.title,
        "description": scenario.description,
        "assumptions": list(scenario.assumptions or []),
        "expected_impact": dict(scenario.expected_impact or {}),
        "risk_analysis": dict(scenario.risk_analysis or {}),
        "cost_estimate": dict(scenario.cost_estimate or {}),
        "confidence_score": round(float(scenario.confidence_score or 0.0), 1),
        "status": scenario.status,
        "created_at": scenario.created_at.isoformat() if scenario.created_at else None,
    }


def public_signal_view(signal: DecisionSignal) -> dict[str, Any]:
    """Безопасное представление сигнала."""
    return {
        "id": signal.id,
        "decision_id": signal.decision_id,
        "source_module": signal.source_module,
        "signal_type": signal.signal_type,
        "value": dict(signal.value or {}),
        "weight": round(float(signal.weight or 0.0), 2),
        "created_at": signal.created_at.isoformat() if signal.created_at else None,
    }


def build_decision_summary(db: Session, project_id: int) -> dict[str, Any]:
    """Сводка Decision Engine: счётчики решений по ключевым статусам."""
    decisions = list_decisions(db, project_id)
    open_count = sum(1 for d in decisions if d.status in ("draft", "analyzing", "reviewed"))
    recommended = sum(1 for d in decisions if d.status == "recommended")
    return {
        "project_id": project_id,
        "decisions_total": len(decisions),
        "decisions_open": open_count,
        "decisions_recommended": recommended,
    }
