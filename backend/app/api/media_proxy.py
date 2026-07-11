"""API media-proxy: временные публичные ссылки на медиа + публичная отдача.

- Создание/список/отзыв ссылок — под ``require_project_access`` (tenant-изоляция).
- Публичная отдача ``GET /media/public/{token}`` — БЕЗ авторизации (по случайному
  токену), с ограничением по времени/типу/размеру; внутренние пути не раскрываются.
- raw-токен возвращается один раз при создании; в БД хранится только хеш.

Instagram live-публикация НЕ выполняется — это только foundation для public image_url.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.security_guards import OptionalUser, require_project_access
from app.services.media_proxy_service import (
    MediaProxyError,
    MediaProxyNotAvailableError,
    MediaProxyService,
    get_media_proxy_service,
)

DbSession = Annotated[Session, Depends(get_db)]
ProxySvc = Annotated[MediaProxyService, Depends(get_media_proxy_service)]

# --- Управление ссылками (требует доступа к проекту) --- #

router = APIRouter(prefix="/media-proxy/projects", tags=["media-proxy"])
# Публичная отдача — отдельный роутер без auth-зависимостей.
public_router = APIRouter(prefix="/media", tags=["media-proxy-public"])


def _result_dict(result: Any) -> dict[str, Any]:
    return {
        "id": result.id,
        "url": result.url,
        "url_masked": result.url_masked,
        "token_prefix": result.token_prefix,
        "expires_at": result.expires_at,
        "content_type": result.content_type,
        "file_name": result.file_name,
        "media_asset_id": result.media_asset_id,
        "status": result.status,
        "warnings": result.warnings,
    }


@router.post(
    "/{project_id}/media-assets/{media_asset_id}/public-link",
    dependencies=[Depends(require_project_access)],
)
def create_media_asset_link(
    project_id: int,
    media_asset_id: int,
    db: DbSession,
    service: ProxySvc,
    user: OptionalUser,
    payload: Annotated[dict[str, Any], Body(default_factory=dict)],
) -> dict[str, Any]:
    """Создать временную публичную ссылку для медиа-актива. real URL — один раз."""
    try:
        result = service.create_public_link(
            db,
            project_id,
            media_asset_id,
            purpose=str(payload.get("purpose", "instagram")),
            ttl_seconds=payload.get("ttl_seconds"),
            current_user_id=user.id if user is not None else None,
        )
    except MediaProxyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _result_dict(result)


@router.post(
    "/{project_id}/posts/{post_id}/public-links",
    dependencies=[Depends(require_project_access)],
)
def create_post_links(
    project_id: int,
    post_id: int,
    db: DbSession,
    service: ProxySvc,
    user: OptionalUser,
    payload: Annotated[dict[str, Any], Body(default_factory=dict)],
) -> list[dict[str, Any]]:
    """Создать публичные ссылки для медиа поста (media_asset_ids)."""
    from app.repositories import post_repository

    post = post_repository.get_post_by_id(db, post_id)
    if post is None or post.project_id != project_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")
    try:
        results = service.create_public_links_for_post(
            db,
            post_id,
            platform=str(payload.get("platform", "instagram")),
            purpose=str(payload.get("purpose", "instagram")),
            max_items=int(payload.get("max_items", 10)),
            ttl_seconds=payload.get("ttl_seconds"),
            current_user_id=user.id if user is not None else None,
        )
    except MediaProxyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return [_result_dict(r) for r in results]


@router.get("/{project_id}/links", dependencies=[Depends(require_project_access)])
def list_links(project_id: int, db: DbSession, service: ProxySvc) -> list[dict[str, Any]]:
    """Ссылки проекта (маскированные, без токенов)."""
    return service.list_project_links(db, project_id)


@router.get("/{project_id}/status", dependencies=[Depends(require_project_access)])
def media_proxy_status(project_id: int, service: ProxySvc) -> dict[str, Any]:
    """Статус media-proxy: base URL, HTTPS-готовность, TTL, лимиты."""
    return service.validate_public_base_url()


@router.delete("/{project_id}/links/{link_id}", dependencies=[Depends(require_project_access)])
def revoke_link(
    project_id: int, link_id: int, db: DbSession, service: ProxySvc, user: OptionalUser
) -> dict[str, Any]:
    """Отозвать ссылку проекта (soft: status=revoked)."""
    revoked = service.revoke_link(
        db, project_id, link_id, current_user_id=user.id if user is not None else None
    )
    return {"revoked": revoked, "link_id": link_id}


@public_router.get("/public/{token}")
def serve_public_media(token: str, db: DbSession, service: ProxySvc) -> Response:
    """Публичная отдача медиа по токену (БЕЗ авторизации). Ошибка/истёк/отозван → 404.

    Внутренние пути файлов не раскрываются. Заголовки: Content-Type/Length,
    Cache-Control, X-Content-Type-Options: nosniff.
    """
    try:
        resolved = service.resolve_token(db, token)
    except MediaProxyNotAvailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except MediaProxyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=resolved.content,
        media_type=resolved.content_type,
        headers={
            "Content-Length": str(resolved.content_length),
            "Cache-Control": "public, max-age=300",
            "X-Content-Type-Options": "nosniff",
        },
    )
