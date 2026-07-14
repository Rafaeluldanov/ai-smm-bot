"""Репозиторий клиентского онбординга (сессии + результаты шагов) — v0.6.4.

Публичные представления без секретов/токенов/сырых payload. Tenant isolation — на сервис/API-слое.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.onboarding_session import OnboardingSession
from app.models.onboarding_step_result import OnboardingStepResult

# Веса завершения шагов (проценты).
_STEP_PERCENT: dict[str, int] = {
    "started": 0,
    "business_completed": 20,
    "media_completed": 40,
    "platforms_completed": 60,
    "goal_completed": 80,
    "ready": 100,
    "completed": 100,
}
# Активные (незавершённые) статусы. «ready»/«completed» — терминальные и СЮДА НЕ входят:
# завершённая сессия не должна подхватываться как активная (иначе новый онбординг невозможен).
_ACTIVE_STATUSES = (
    "started",
    "business_completed",
    "media_completed",
    "platforms_completed",
    "goal_completed",
    "paused",
)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------- #
# Sessions                                                                     #
# ---------------------------------------------------------------------------- #


def create_session(
    db: Session, *, account_id: int | None, user_id: int | None, project_id: int | None
) -> OnboardingSession:
    """Создать сессию онбординга (status=started, шаг 1)."""
    session = OnboardingSession(
        account_id=account_id,
        user_id=user_id,
        project_id=project_id,
        status="started",
        current_step=1,
        completion_percent=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_session_by_id(db: Session, session_id: int) -> OnboardingSession | None:
    """Сессия по id (или None)."""
    return db.get(OnboardingSession, session_id)


def get_active_session(db: Session, user_id: int) -> OnboardingSession | None:
    """Активная (незавершённая) сессия пользователя (свежая), если есть."""
    stmt = (
        select(OnboardingSession)
        .where(
            OnboardingSession.user_id == user_id,
            OnboardingSession.status.in_(_ACTIVE_STATUSES),
            OnboardingSession.finished_at.is_(None),
        )
        .order_by(OnboardingSession.id.desc())
    )
    return db.execute(stmt).scalars().first()


def update_step(
    db: Session,
    session: OnboardingSession,
    *,
    status: str,
    current_step: int,
    data_field: str | None = None,
    data: dict[str, Any] | None = None,
) -> OnboardingSession:
    """Обновить статус/шаг сессии и (опционально) данные шага."""
    session.status = status
    session.current_step = current_step
    session.completion_percent = _STEP_PERCENT.get(status, session.completion_percent)
    if data_field is not None and hasattr(session, data_field):
        setattr(session, data_field, data or {})
    db.commit()
    db.refresh(session)
    return session


def complete_step(db: Session, session: OnboardingSession, *, status: str) -> OnboardingSession:
    """Пометить сессию завершённым статусом шага (без смены данных)."""
    session.status = status
    session.completion_percent = _STEP_PERCENT.get(status, session.completion_percent)
    db.commit()
    db.refresh(session)
    return session


def finish_session(
    db: Session, session: OnboardingSession, *, status: str = "ready"
) -> OnboardingSession:
    """Завершить онбординг (status=ready/completed, 100%)."""
    session.status = status
    session.completion_percent = 100
    session.finished_at = _now()
    db.commit()
    db.refresh(session)
    return session


def get_progress(session: OnboardingSession) -> dict[str, Any]:
    """Короткая сводка прогресса сессии."""
    return {
        "session_id": session.id,
        "status": session.status,
        "current_step": session.current_step,
        "completion_percent": session.completion_percent,
        "project_id": session.project_id,
    }


def public_session_view(session: OnboardingSession) -> dict[str, Any]:
    """Безопасное представление сессии (без секретов)."""
    return {
        "id": session.id,
        "account_id": session.account_id,
        "user_id": session.user_id,
        "project_id": session.project_id,
        "status": session.status,
        "current_step": session.current_step,
        "completion_percent": session.completion_percent,
        "business_data": dict(session.business_data or {}),
        "media_data": dict(session.media_data or {}),
        "platform_data": dict(session.platform_data or {}),
        "goal_data": dict(session.goal_data or {}),
        "finished_at": session.finished_at.isoformat() if session.finished_at else None,
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


# ---------------------------------------------------------------------------- #
# Step results                                                                 #
# ---------------------------------------------------------------------------- #


def save_result(
    db: Session,
    *,
    session_id: int,
    step_name: str,
    status: str,
    input_data: dict[str, Any] | None = None,
    output_data: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> OnboardingStepResult:
    """Записать результат шага (безопасные данные, без секретов)."""
    result = OnboardingStepResult(
        session_id=session_id,
        step_name=step_name,
        status=status,
        input_data=input_data or {},
        output_data=output_data or {},
        error_message=(error_message or "")[:500] or None,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def list_results(db: Session, session_id: int) -> list[OnboardingStepResult]:
    """Результаты шагов сессии (по порядку)."""
    stmt = (
        select(OnboardingStepResult)
        .where(OnboardingStepResult.session_id == session_id)
        .order_by(OnboardingStepResult.id.asc())
    )
    return list(db.execute(stmt).scalars().all())


def public_result_view(result: OnboardingStepResult) -> dict[str, Any]:
    """Безопасное представление результата шага."""
    return {
        "id": result.id,
        "step_name": result.step_name,
        "status": result.status,
        "output_data": dict(result.output_data or {}),
        "error_message": result.error_message,
        "created_at": result.created_at.isoformat() if result.created_at else None,
    }
