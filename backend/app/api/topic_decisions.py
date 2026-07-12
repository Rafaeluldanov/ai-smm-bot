"""REST API решений об автовыборе темы (v0.4.4).

Все роуты — под tenant-изоляцией. Preview/создание решения — бесплатно; пост не создаётся
и live-публикаций нет. Секретов/токенов в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_optional_user, get_topic_decision_service
from app.api.security_guards import require_project_access, require_topic_decision_access
from app.models.user import User
from app.repositories import schedule_topic_decision_repository
from app.services.schedule_topic_decision_service import (
    ScheduleTopicDecisionService,
    TopicDecisionError,
)

router = APIRouter(prefix="/topic-decisions", tags=["topic-decisions"])

DbSession = Annotated[Session, Depends(get_db)]
DecSvc = Annotated[ScheduleTopicDecisionService, Depends(get_topic_decision_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except TopicDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


# --- Запросы ---


class PreviewRequest(BaseModel):
    """Preview решения (без записи)."""

    platform_key: str | None = None
    plan_id: int | None = None
    category_id: int | None = None
    publish_time: str | None = None


class CreateRequest(BaseModel):
    """Создание решения (запись, без поста и без списаний)."""

    platform_key: str | None = None
    plan_id: int | None = None
    category_id: int | None = None
    publish_time: str | None = None
    idempotency_key: str | None = None


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_decisions(
    project_id: int,
    db: DbSession,
    platform_key: str | None = None,
    decision_status: str | None = None,
    source: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список решений проекта (фильтры платформа/статус/источник)."""
    rows = schedule_topic_decision_repository.list_for_project(
        db, project_id, _platform(platform_key), decision_status, source, limit, offset
    )
    service = ScheduleTopicDecisionService()
    return [service._decision_view(d) for d in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: DecSvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Сводка решений проекта для UI."""
    return service.build_decision_dashboard(db, project_id, _platform(platform_key))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int, payload: PreviewRequest, db: DbSession, service: DecSvc
) -> dict[str, Any]:
    """Предпросмотр решения (без записи и без списания)."""
    return _run(
        lambda: service.preview_decision_for_plan(
            db,
            project_id,
            _platform(payload.platform_key),
            plan_id=payload.plan_id,
            category_id=payload.category_id,
            publish_time=payload.publish_time,
        )
    )


@router.post("/projects/{project_id}/create", dependencies=[Depends(require_project_access)])
def create(
    project_id: int, payload: CreateRequest, db: DbSession, service: DecSvc
) -> dict[str, Any]:
    """Создать решение (без поста и без live). Идемпотентно."""
    return _run(
        lambda: service.create_decision_for_plan(
            db,
            project_id,
            _platform(payload.platform_key),
            plan_id=payload.plan_id,
            category_id=payload.category_id,
            publish_time=payload.publish_time,
            idempotency_key=payload.idempotency_key,
            decision_mode="dry_run",
        )
    )


# --- Роуты решения ---


@router.get("/{decision_id}", dependencies=[Depends(require_topic_decision_access)])
def get_decision(decision_id: int, db: DbSession) -> dict[str, Any]:
    """Одно решение."""
    decision = schedule_topic_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return ScheduleTopicDecisionService()._decision_view(decision)


@router.post("/{decision_id}/apply-dry", dependencies=[Depends(require_topic_decision_access)])
def apply_dry(decision_id: int, db: DbSession, service: DecSvc) -> dict[str, Any]:
    """Показать, как решение повлияло бы на payload драфта (без записи, без live)."""
    decision = schedule_topic_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    view = service._decision_view(decision)
    base_payload = {
        "title": "",
        "generation_notes": {"source": "schedule_automation", "live": False},
    }
    return {
        "decision_id": decision_id,
        "draft_payload": service.apply_decision_to_draft_payload(view, base_payload),
        "live": False,
        "writes": False,
    }
