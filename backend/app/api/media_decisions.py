"""REST API решений об автовыборе медиа (v0.4.5).

Все роуты — под tenant-изоляцией. Preview/создание решения — бесплатно; пост не создаётся
и live-публикаций нет; публичные ссылки автоматически не создаются. Секретов/токенов и
внутренних путей к файлам в ответах нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_media_decision_service, get_optional_user
from app.api.security_guards import require_media_decision_access, require_project_access
from app.models.user import User
from app.repositories import schedule_media_decision_repository
from app.services.schedule_media_decision_service import (
    MediaDecisionError,
    ScheduleMediaDecisionService,
)

router = APIRouter(prefix="/media-decisions", tags=["media-decisions"])

DbSession = Annotated[Session, Depends(get_db)]
DecSvc = Annotated[ScheduleMediaDecisionService, Depends(get_media_decision_service)]
OptUser = Annotated[User | None, Depends(get_optional_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except MediaDecisionError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _platform(value: str | None) -> str | None:
    return None if value in (None, "", "all") else value


# --- Запросы ---


class PreviewRequest(BaseModel):
    """Preview решения о медиа (без записи)."""

    platform_key: str | None = None
    plan_id: int | None = None
    topic_decision_id: int | None = None


class CreateRequest(BaseModel):
    """Создание решения о медиа (запись, без поста и без списаний)."""

    platform_key: str | None = None
    plan_id: int | None = None
    topic_decision_id: int | None = None
    idempotency_key: str | None = None


# --- Роуты проекта ---


@router.get("/projects/{project_id}", dependencies=[Depends(require_project_access)])
def list_decisions(
    project_id: int,
    db: DbSession,
    platform_key: str | None = None,
    decision_status: str | None = None,
    strategy: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Список решений проекта (фильтры платформа/статус/стратегия)."""
    rows = schedule_media_decision_repository.list_for_project(
        db, project_id, _platform(platform_key), decision_status, strategy, limit, offset
    )
    service = ScheduleMediaDecisionService()
    return [service._decision_view(d) for d in rows]


@router.get("/projects/{project_id}/dashboard", dependencies=[Depends(require_project_access)])
def dashboard(
    project_id: int, db: DbSession, service: DecSvc, platform_key: str | None = None
) -> dict[str, Any]:
    """Сводка решений о медиа проекта для UI."""
    return service.build_media_decision_dashboard(db, project_id, _platform(platform_key))


@router.post("/projects/{project_id}/preview", dependencies=[Depends(require_project_access)])
def preview(
    project_id: int, payload: PreviewRequest, db: DbSession, service: DecSvc
) -> dict[str, Any]:
    """Предпросмотр решения о медиа (без записи и без списания)."""
    return _run(
        lambda: service.preview_media_decision_for_plan(
            db,
            project_id,
            _platform(payload.platform_key),
            plan_id=payload.plan_id,
            topic_decision_id=payload.topic_decision_id,
        )
    )


@router.post("/projects/{project_id}/create", dependencies=[Depends(require_project_access)])
def create(
    project_id: int, payload: CreateRequest, db: DbSession, service: DecSvc
) -> dict[str, Any]:
    """Создать решение о медиа (без поста и без live). Идемпотентно."""
    return _run(
        lambda: service.create_media_decision_for_plan(
            db,
            project_id,
            _platform(payload.platform_key),
            plan_id=payload.plan_id,
            topic_decision_id=payload.topic_decision_id,
            idempotency_key=payload.idempotency_key,
        )
    )


# --- Роуты решения ---


@router.get("/{decision_id}", dependencies=[Depends(require_media_decision_access)])
def get_decision(decision_id: int, db: DbSession) -> dict[str, Any]:
    """Одно решение о медиа."""
    decision = schedule_media_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    return ScheduleMediaDecisionService()._decision_view(decision)


@router.post("/{decision_id}/apply-dry", dependencies=[Depends(require_media_decision_access)])
def apply_dry(decision_id: int, db: DbSession, service: DecSvc) -> dict[str, Any]:
    """Показать, как решение повлияло бы на payload драфта (без записи, без live)."""
    decision = schedule_media_decision_repository.get_by_id(db, decision_id)
    if decision is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Не найдено")
    view = service._decision_view(decision)
    base_payload = {
        "title": "",
        "generation_notes": {"source": "schedule_automation", "live": False},
    }
    return {
        "decision_id": decision_id,
        "draft_payload": service.apply_media_decision_to_draft_payload(view, base_payload),
        "live": False,
        "writes": False,
    }
