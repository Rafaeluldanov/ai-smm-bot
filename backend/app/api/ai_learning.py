"""REST API AI Learning Loop — v0.6.5.

Клиентский слой «AI обучение вашего бренда»: профиль обучения, запуск анализа,
рекомендации, объяснение и приём фидбэка. Всё под project-гардом. Обучение НЕ
публикует, НЕ включает live-флаги и НЕ меняет стратегию автоматически. Секретов нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ai_learning_service,
    get_content_strategy_service,
    get_current_user,
    get_db,
)
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.ai_learning_service import AILearningError, AILearningService
from app.services.content_strategy_service import ContentStrategyService

router = APIRouter(prefix="/projects", tags=["ai-learning"])

DbSession = Annotated[Session, Depends(get_db)]
LearningSvc = Annotated[AILearningService, Depends(get_ai_learning_service)]
StrategySvc = Annotated[ContentStrategyService, Depends(get_content_strategy_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AILearningError as exc:
        message = str(exc)
        if "не найден" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


class AnalyzeRequest(BaseModel):
    """Параметры запуска анализа (окно в днях)."""

    window_days: int = 90


class FeedbackRequest(BaseModel):
    """Клиентский фидбэк по посту («Как вам пост?»)."""

    sentiment: str | None = None  # excellent | good | ok | bad
    rating: int | None = None  # 1..5
    post_id: int | None = None
    comment_present: bool = False


@router.get("/{project_id}/learning", dependencies=[Depends(require_project_access)])
def get_learning(
    project_id: int, db: DbSession, service: LearningSvc, user: CurrentUser
) -> dict[str, Any]:
    """Профиль обучения проекта (сводка «что AI понял»)."""
    return _run(lambda: service.get_summary(db, project_id))


@router.post("/{project_id}/learning/analyze", dependencies=[Depends(require_project_access)])
def analyze_learning(
    project_id: int,
    payload: AnalyzeRequest,
    db: DbSession,
    service: LearningSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Запустить анализ постов + пересчитать профиль (не публикует, live не включает)."""
    return _run(
        lambda: service.analyze_project(
            db, project_id, window_days=payload.window_days, user_id=user.id
        )
    )


@router.get(
    "/{project_id}/learning/recommendations", dependencies=[Depends(require_project_access)]
)
def get_recommendations(
    project_id: int,
    db: DbSession,
    service: LearningSvc,
    strategy: StrategySvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Рекомендации следующего контента + рекомендованная стратегия (не применяется)."""
    return _run(
        lambda: {
            "next_content": service.recommend_next_content(db, project_id),
            "strategy": strategy.recommend_strategy(db, project_id),
        }
    )


@router.get("/{project_id}/learning/explanation", dependencies=[Depends(require_project_access)])
def get_explanation(
    project_id: int, db: DbSession, service: LearningSvc, user: CurrentUser
) -> dict[str, Any]:
    """Объяснение для клиента: что Botfleet понял и что улучшилось."""
    return _run(lambda: service.explain_learning(db, project_id))


@router.post("/{project_id}/learning/feedback", dependencies=[Depends(require_project_access)])
def post_feedback(
    project_id: int,
    payload: FeedbackRequest,
    db: DbSession,
    service: LearningSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Принять клиентский фидбэк по посту как сигнал обучения (без секретов)."""
    return _run(
        lambda: service.record_client_feedback(
            db,
            project_id,
            sentiment=payload.sentiment,
            rating=payload.rating,
            post_id=payload.post_id,
            comment_present=payload.comment_present,
            user_id=user.id,
        )
    )


@router.post("/{project_id}/learning/reset", dependencies=[Depends(require_project_access)])
def reset_learning(
    project_id: int, db: DbSession, service: LearningSvc, user: CurrentUser
) -> dict[str, Any]:
    """Сбросить агрегаты профиля (историю сигналов НЕ удаляем)."""
    return _run(lambda: service.reset_learning(db, project_id, user_id=user.id))
