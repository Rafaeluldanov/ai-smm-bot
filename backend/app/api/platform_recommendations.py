"""REST API экспертной базы SMM-рекомендаций Botfleet — v1.0.1.

Полностью READ-ONLY статическая база знаний: роль, частота, сигналы, форматы, правила, риски, KPI,
недельный ритм, чек-лист, кросс-платформенная адаптация. НЕ меняет расписание/автопостинг, НЕ
публикует, НЕ создаёт workflow, НЕ ходит во внешние API, НЕ пишет в БД, НЕ списывает units.
Обычный GET не пишет audit.

Роуты:
- GET /platform-recommendations               — список платформ (кратко)
- GET /platform-recommendations/universal      — универсальные принципы/конвейер/ритм/чек-лист
- GET /platform-recommendations/{platform_slug}— рекомендации по платформе (canonical или alias)
- GET /projects/{project_id}/platforms/{platform_slug}/recommendations — то же, но под tenant-гардом
  (страницы платформ project-scoped).

Неизвестная платформа → 404; битый ресурс → контролируемый 500 без stack trace в ответе.
"""

from collections.abc import Callable
from typing import Annotated, Any, TypeVar

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.security_guards import require_project_access
from app.services.platform_recommendations_service import (
    PlatformRecommendationsError,
    PlatformRecommendationsService,
    UnknownPlatformError,
    get_platform_recommendations_service,
)

router = APIRouter(tags=["platform-recommendations"])

RecsSvc = Annotated[PlatformRecommendationsService, Depends(get_platform_recommendations_service)]

_T = TypeVar("_T")


def _run(action: Callable[[], _T]) -> _T:
    """Выполнить read-only действие: unknown → 404, битый ресурс → контролируемый 500."""
    try:
        return action()
    except UnknownPlatformError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except PlatformRecommendationsError:
        # Контролируемый 500 без stack trace/пути в ответе.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="База рекомендаций временно недоступна",
        ) from None


# --------------------------------------------------------------------------- #
# Global read-only routes                                                     #
# --------------------------------------------------------------------------- #


@router.get("/platform-recommendations")
def list_platform_recommendations(service: RecsSvc) -> dict[str, Any]:
    """Краткий список платформ базы знаний (slug/title/role/частота)."""
    return _run(lambda: {"platforms": service.list_platforms()})


@router.get("/platform-recommendations/universal")
def universal_recommendations(service: RecsSvc) -> dict[str, Any]:
    """Универсальные принципы, конвейер, недельный ритм, чек-лист (read-only)."""
    return _run(service.get_universal_recommendations)


@router.get("/platform-recommendations/{platform_slug}")
def platform_recommendations(platform_slug: str, service: RecsSvc) -> dict[str, Any]:
    """Полные рекомендации по платформе (canonical slug или разрешённый alias)."""
    return _run(lambda: service.get_platform_recommendations(platform_slug))


# --------------------------------------------------------------------------- #
# Project-scoped route (страницы платформ project-scoped) — с tenant-гардом    #
# --------------------------------------------------------------------------- #


@router.get(
    "/projects/{project_id}/platforms/{platform_slug}/recommendations",
    dependencies=[Depends(require_project_access)],
)
def project_platform_recommendations(
    project_id: int, platform_slug: str, service: RecsSvc
) -> dict[str, Any]:
    """Рекомендации по платформе в контексте проекта (auth + tenant isolation)."""
    return _run(lambda: service.get_platform_recommendations(platform_slug))
