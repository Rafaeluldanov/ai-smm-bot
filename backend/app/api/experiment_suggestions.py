"""REST API предложений экспериментов (v0.4.3).

Все роуты — под tenant-изоляцией. Preview/генерация/приём — бесплатно; создание A/B из
предложения — платно (как обычное создание A/B). Live-публикаций нет; варианты идут в
очередь ревью. Секретов/токенов в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_experiment_suggestion_service, get_optional_user
from app.api.security_guards import (
    require_project_access,
    require_suggestion_access,
)
from app.models.user import User
from app.repositories import experiment_suggestion_repository
from app.services.billing_service import InsufficientBalanceError
from app.services.experiment_suggestion_service import (
    ExperimentSuggestionError,
    ExperimentSuggestionService,
)

router = APIRouter(prefix="/experiment-suggestions", tags=["experiment-suggestions"])

DbSession = Annotated[Session, Depends(get_db)]
SuggSvc = Annotated[ExperimentSuggestionService, Depends(get_experiment_suggestion_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except InsufficientBalanceError as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc
    except ExperimentSuggestionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _uid(user: User | None) -> int | None:
    return user.id if user is not None else None


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


# --- Запросы ---


class PreviewRequest(BaseModel):
    """Preview предложений (без записи)."""

    platform_key: str | None = None
    limit: int | None = None


class GenerateRequest(BaseModel):
    """Генерация предложений (запись, без списаний)."""

    platform_key: str | None = None
    idempotency_prefix: str | None = None


class RejectRequest(BaseModel):
    """Отклонение предложения."""

    reason: str | None = None


class CreateExperimentRequest(BaseModel):
    """Создание A/B из предложения (платно, идемпотентно)."""

    idempotency_key: str | None = None


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_suggestions(
    project_id: int,
    db: DbSession,
    platform_key: str | None = None,
    suggestion_status: str | None = None,
    suggestion_type: str | None = None,
) -> list[dict[str, Any]]:
    """Список предложений проекта (фильтры платформа/статус/тип)."""
    rows = experiment_suggestion_repository.list_for_project(
        db, project_id, _platform(platform_key), suggestion_status, suggestion_type
    )
    return [ExperimentSuggestionService._suggestion_view(s) for s in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: SuggSvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Сводка предложений проекта для UI."""
    return service.build_suggestion_dashboard(db, project_id, _platform(platform_key))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int, payload: PreviewRequest, db: DbSession, service: SuggSvc
) -> dict[str, Any]:
    """Предложения-кандидаты (без записи и без списания)."""
    return _run(
        lambda: service.preview_suggestions(
            db, project_id, _platform(payload.platform_key), payload.limit
        )
    )


@router.post("/projects/{project_id}/generate", dependencies=[Depends(require_project_access)])
def generate(
    project_id: int, payload: GenerateRequest, db: DbSession, service: SuggSvc, user: OptUser
) -> dict[str, Any]:
    """Создать предложения (proposed). Идемпотентно, без списаний."""
    return _run(
        lambda: service.generate_suggestions(
            db,
            project_id,
            _platform(payload.platform_key),
            idempotency_prefix=payload.idempotency_prefix,
            current_user_id=_uid(user),
            source="api",
        )
    )


@router.post(
    "/projects/{project_id}/worker-preview",
    dependencies=[Depends(require_project_access)],
)
def worker_preview(
    project_id: int,
    db: DbSession,
    service: SuggSvc,
    platform_key: str | None = None,
) -> dict[str, Any]:
    """Preview предложений в том же виде, что делает worker (только чтение)."""
    return _run(
        lambda: service.run_worker_suggestions_for_project(
            db, project_id, platform_key=_platform(platform_key), dry_run=True
        )
    )


# --- Роуты предложения ---


@router.get("/{suggestion_id}", dependencies=[Depends(require_suggestion_access)])
def get_suggestion(suggestion_id: int, db: DbSession) -> dict[str, Any]:
    """Одно предложение."""
    suggestion = experiment_suggestion_repository.get_by_id(db, suggestion_id)
    if suggestion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return ExperimentSuggestionService._suggestion_view(suggestion)


@router.post("/{suggestion_id}/accept", dependencies=[Depends(require_suggestion_access)])
def accept(suggestion_id: int, db: DbSession, service: SuggSvc, user: OptUser) -> dict[str, Any]:
    """Принять предложение (+ лёгкий сигнал обучения)."""
    return _run(lambda: service.accept_suggestion(db, suggestion_id, _uid(user)))


@router.post("/{suggestion_id}/reject", dependencies=[Depends(require_suggestion_access)])
def reject(
    suggestion_id: int, payload: RejectRequest, db: DbSession, service: SuggSvc, user: OptUser
) -> dict[str, Any]:
    """Отклонить предложение (+ слабый сигнал обучения)."""
    return _run(lambda: service.reject_suggestion(db, suggestion_id, payload.reason, _uid(user)))


@router.post("/{suggestion_id}/dismiss", dependencies=[Depends(require_suggestion_access)])
def dismiss(suggestion_id: int, db: DbSession, service: SuggSvc, user: OptUser) -> dict[str, Any]:
    """Скрыть предложение."""
    return _run(lambda: service.dismiss_suggestion(db, suggestion_id, _uid(user)))


@router.post(
    "/{suggestion_id}/create-experiment", dependencies=[Depends(require_suggestion_access)]
)
def create_experiment(
    suggestion_id: int,
    payload: CreateExperimentRequest,
    db: DbSession,
    service: SuggSvc,
    user: OptUser,
) -> dict[str, Any]:
    """Создать A/B-эксперимент из предложения (платно). Live нет."""
    return _run(
        lambda: service.create_experiment_from_suggestion(
            db, suggestion_id, _uid(user), payload.idempotency_key
        )
    )
