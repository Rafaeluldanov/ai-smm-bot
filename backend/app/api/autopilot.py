"""REST API автопилота проекта — v0.5.6.

Клиентский слой «автопилот работает сам»: дашборд, чек-лист, health-check, настройка календаря/
Яндекс Диска/правил, старт/пауза, превью и первый draft. Всё под project-гардом. Секретов/сырых
токенов в ответах нет; live-публикаций и реальных внешних вызовов нет; массовой публикации нет.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_autopilot_service, get_current_user, get_db
from app.api.security_guards import require_project_access
from app.models.user import User
from app.services.autopilot_service import AutopilotError, AutopilotService

router = APIRouter(
    prefix="/autopilot", tags=["autopilot"], dependencies=[Depends(require_project_access)]
)

DbSession = Annotated[Session, Depends(get_db)]
AutopilotSvc = Annotated[AutopilotService, Depends(get_autopilot_service)]
CurrentUser = Annotated[User, Depends(get_current_user)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    try:
        return action()
    except AutopilotError as exc:
        message = str(exc)
        if "не найден" in message or "Нет доступа" in message:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=message) from exc


# --- Запросы ---


class ModeRequest(BaseModel):
    """Смена режима автопилота."""

    mode: str


class CalendarRequest(BaseModel):
    """Настройка календаря (упрощённая клиентская форма)."""

    platforms: list[str] = []
    frequency: str = "daily"
    weekdays: list[int] | None = None
    publish_times: list[str] = []
    posts_per_day: int = 1
    timezone: str | None = None
    start_date: str | None = None
    end_date: str | None = None


class YandexDiskRequest(BaseModel):
    """Подключение Яндекс Диска (публичная ссылка)."""

    public_url: str
    root_folder: str = "SMM"
    tags: list[str] = []


class ContentRulesRequest(BaseModel):
    """Правила контента (цель/тон/глубина/CTA)."""

    business_goal: str = ""
    tone: str = ""
    post_depth: str = "normal"
    cta: str = ""
    forbidden_phrases: list[str] = []
    preferred_topics: list[str] = []


class FirstDraftRequest(BaseModel):
    """Создать первый draft (needs_review)."""

    platform_key: str | None = None


# --- Роуты ---


@router.get("/projects/{project_id}")
def dashboard(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Дашборд автопилота проекта."""
    return _run(lambda: service.build_autopilot_dashboard(db, project_id))


@router.get("/projects/{project_id}/checklist")
def checklist(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Чек-лист настройки автопилота."""
    return _run(lambda: service.build_setup_checklist(db, project_id))


@router.post("/projects/{project_id}/health-check")
def health_check(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Проверка готовности автопилота (статус + блокеры)."""
    return _run(lambda: service.run_health_check(db, project_id))


@router.post("/projects/{project_id}/mode")
def set_mode(
    project_id: int,
    payload: ModeRequest,
    db: DbSession,
    service: AutopilotSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Сменить режим (full_auto/semi_auto)."""
    return _run(
        lambda: service.update_autopilot_mode(db, project_id, payload.mode, current_user_id=user.id)
    )


@router.post("/projects/{project_id}/calendar")
def configure_calendar(
    project_id: int,
    payload: CalendarRequest,
    db: DbSession,
    service: AutopilotSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Настроить календарь публикаций (создаёт/обновляет план)."""
    return _run(
        lambda: service.configure_calendar(
            db, project_id, payload.model_dump(), current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/yandex-disk")
def configure_yandex_disk(
    project_id: int,
    payload: YandexDiskRequest,
    db: DbSession,
    service: AutopilotSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Подключить Яндекс Диск (media source)."""
    return _run(
        lambda: service.configure_yandex_disk(
            db, project_id, payload.model_dump(), current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/content-rules")
def configure_content_rules(
    project_id: int,
    payload: ContentRulesRequest,
    db: DbSession,
    service: AutopilotSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Настроить правила контента (цель/тон/стиль)."""
    return _run(
        lambda: service.configure_content_rules(
            db, project_id, payload.model_dump(), current_user_id=user.id
        )
    )


@router.post("/projects/{project_id}/start")
def start(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Запустить автопилот (блокируется при незавершённой настройке; live-флаги не включает)."""
    return _run(lambda: service.start_autopilot(db, project_id, current_user_id=user.id))


@router.post("/projects/{project_id}/pause")
def pause(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Поставить автопилот на паузу."""
    return _run(lambda: service.pause_autopilot(db, project_id, current_user_id=user.id))


@router.post("/projects/{project_id}/preview-next")
def preview_next(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Превью ближайших публикаций (без записи)."""
    return _run(lambda: service.preview_next_posts(db, project_id))


@router.post("/projects/{project_id}/first-draft")
def first_draft(
    project_id: int,
    payload: FirstDraftRequest,
    db: DbSession,
    service: AutopilotSvc,
    user: CurrentUser,
) -> dict[str, Any]:
    """Создать первый пост как draft/needs_review (без live-публикации)."""
    return _run(
        lambda: service.create_first_draft_now(
            db, project_id, platform_key=payload.platform_key, current_user_id=user.id
        )
    )


@router.get("/projects/{project_id}/client-summary")
def client_summary(
    project_id: int, db: DbSession, service: AutopilotSvc, user: CurrentUser
) -> dict[str, Any]:
    """Простая клиентская сводка: работает / нужна настройка / проблема / на паузе."""
    return _run(lambda: service.summarize_for_client(db, project_id))
