"""REST API A/B-тестирования и оптимизации тем (v0.4.2).

Все роуты — под tenant-изоляцией. Варианты идут в очередь ревью; live-публикаций нет;
внешних API-вызовов нет. Секретов/токенов в ответах нет. Создание эксперимента платное
(идемпотентно); preview/рекомендации/ручной winner — бесплатно.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import (
    get_ab_testing_service,
    get_db,
    get_optional_user,
    get_topic_optimization_service,
)
from app.api.security_guards import (
    require_experiment_access,
    require_post_access,
    require_project_access,
    require_variant_access,
)
from app.models.user import User
from app.repositories import content_experiment_repository
from app.repositories.post_repository import PostNotFoundError
from app.services.ab_testing_service import ABTestingError, ABTestingService
from app.services.billing_service import InsufficientBalanceError
from app.services.topic_optimization_service import TopicOptimizationService

router = APIRouter(prefix="/experiments", tags=["experiments"])

DbSession = Annotated[Session, Depends(get_db)]
ABSvc = Annotated[ABTestingService, Depends(get_ab_testing_service)]
OptSvc = Annotated[TopicOptimizationService, Depends(get_topic_optimization_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except PostNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ABTestingError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


# --- Запросы ---


class PreviewTopicRequest(BaseModel):
    """Превью вариантов по теме (без записи)."""

    platform_key: str | None = None
    topic: str
    variant_count: int = 2


class CreateFromTopicRequest(BaseModel):
    """Создание эксперимента из темы (платно)."""

    platform_key: str | None = None
    topic: str
    experiment_type: str = "ab_test"
    variant_count: int = 2
    idempotency_key: str | None = None


class CreateFromPostRequest(BaseModel):
    """Создание эксперимента из существующего поста."""

    experiment_type: str = "ab_test"
    variant_count: int = 2
    idempotency_key: str | None = None


class ChooseWinnerRequest(BaseModel):
    """Выбор winner (manual/auto)."""

    method: str = "auto"  # manual | auto
    variant_id: int | None = None


class VariantFeedbackRequest(BaseModel):
    """Feedback по варианту."""

    event_type: str = "approved"  # approved | rejected | changes_requested | edited | manual_rating
    rating: int | None = Field(default=None, ge=1, le=5)
    comment: str | None = None


class VariantMetricsRequest(BaseModel):
    """Метрики варианта (ручной/demo снимок)."""

    views: int | None = None
    reach: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None


# --- Эксперименты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_experiments(
    project_id: int,
    db: DbSession,
    platform_key: str | None = None,
    experiment_status: str | None = None,
    experiment_type: str | None = None,
) -> list[dict[str, Any]]:
    """Список экспериментов проекта (фильтры платформа/статус/тип)."""
    runs = content_experiment_repository.list_experiments_for_project(
        db, project_id, _platform(platform_key), experiment_status, experiment_type
    )
    return [ABTestingService._experiment_view(e) for e in runs]


@router.post("/projects/{project_id}/preview-topic", dependencies=[Depends(require_project_access)])
def preview_topic(
    project_id: int, payload: PreviewTopicRequest, db: DbSession, service: ABSvc
) -> dict[str, Any]:
    """Предлагаемые варианты по теме + оценка списания (без записи)."""
    return _run(
        lambda: service.preview_topic(
            db, project_id, _platform(payload.platform_key), payload.topic, payload.variant_count
        )
    )


@router.post(
    "/projects/{project_id}/create-from-topic", dependencies=[Depends(require_project_access)]
)
def create_from_topic(
    project_id: int, payload: CreateFromTopicRequest, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Создать эксперимент из темы (платно, идемпотентно). Live нет."""
    return _run(
        lambda: service.create_experiment_from_topic(
            db,
            project_id,
            _platform(payload.platform_key),
            payload.topic,
            payload.experiment_type,
            payload.variant_count,
            _uid(user),
            payload.idempotency_key,
        )
    )


@router.post("/posts/{post_id}/create", dependencies=[Depends(require_post_access)])
def create_from_post(
    post_id: int, payload: CreateFromPostRequest, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Создать эксперимент из существующего поста (платно). Live нет."""
    return _run(
        lambda: service.create_experiment_from_post(
            db,
            post_id,
            payload.experiment_type,
            payload.variant_count,
            _uid(user),
            payload.idempotency_key,
        )
    )


@router.get("/{experiment_id}", dependencies=[Depends(require_experiment_access)])
def get_experiment(experiment_id: int, db: DbSession, service: ABSvc) -> dict[str, Any]:
    """Сводка эксперимента: варианты, winner, различия оценок."""
    return _run(lambda: service.build_experiment_summary(db, experiment_id))


@router.post("/{experiment_id}/score", dependencies=[Depends(require_experiment_access)])
def score_experiment(
    experiment_id: int, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Пересчитать оценки вариантов (платное действие — анализ)."""
    return _run(lambda: service.score_variants(db, experiment_id, _uid(user)))


@router.post("/{experiment_id}/choose-winner", dependencies=[Depends(require_experiment_access)])
def choose_winner(
    experiment_id: int, payload: ChooseWinnerRequest, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Выбрать winner (manual — бесплатно, auto — платный анализ)."""
    return _run(
        lambda: service.choose_winner(
            db, experiment_id, payload.method, payload.variant_id, _uid(user)
        )
    )


@router.post("/{experiment_id}/cancel", dependencies=[Depends(require_experiment_access)])
def cancel_experiment(
    experiment_id: int, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Отменить эксперимент."""
    return _run(lambda: service.cancel_experiment(db, experiment_id, _uid(user)))


# --- Варианты ---


@router.post("/variants/{variant_id}/feedback", dependencies=[Depends(require_variant_access)])
def variant_feedback(
    variant_id: int, payload: VariantFeedbackRequest, db: DbSession, service: ABSvc, user: OptUser
) -> dict[str, Any]:
    """Записать feedback по варианту (бесплатно)."""
    return _run(
        lambda: service.record_variant_feedback(
            db, variant_id, payload.event_type, payload.rating, payload.comment, _uid(user)
        )
    )


@router.post("/variants/{variant_id}/metrics", dependencies=[Depends(require_variant_access)])
def variant_metrics(
    variant_id: int, payload: VariantMetricsRequest, db: DbSession, service: ABSvc
) -> dict[str, Any]:
    """Привязать метрики к варианту (бесплатно)."""
    metrics = payload.model_dump(exclude_none=True)
    return _run(lambda: service.import_variant_metrics(db, variant_id, metrics))


# --- Рекомендации тем ---


@router.get(
    "/projects/{project_id}/recommendations", dependencies=[Depends(require_project_access)]
)
def recommendations(
    project_id: int,
    db: DbSession,
    service: OptSvc,
    platform_key: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Рекомендации тем (publish_more/avoid/retest/explore/fill_gap). Бесплатно."""
    return service.recommend_next_topics(db, project_id, _platform(platform_key), limit)


@router.get("/projects/{project_id}/strategy", dependencies=[Depends(require_project_access)])
def strategy(
    project_id: int, db: DbSession, service: OptSvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Стратегия тем: что бот будет делать чаще / избегать / уточнить."""
    return service.explain_topic_strategy(db, project_id, _platform(platform_key))
