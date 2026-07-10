"""REST API VK OAuth connect flow (подключение user-token через кнопку).

Маршруты:
- ``GET /integrations/vk/oauth/start`` — редирект на авторизацию VK (подписанный state);
- ``GET /integrations/vk/oauth/callback`` — обмен code→token, сохранение секрета,
  safe-check; отдаёт HTML-страницу результата (без токена);
- ``GET /integrations/vk/status`` — статус подключения (без сети);
- ``POST /integrations/vk/oauth/check`` — повторная безопасная проверка доступа.

Публикаций нет; live VK не включается. Наружу — только маска секрета и статусы.
``start``/``callback`` не требуют dev-токена (их вызывает браузер/редирект VK),
защита — подписанный ``state``.
"""

import html
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_vk_oauth_service
from app.api.security_guards import require_vk_resource_access
from app.integrations.vk.oauth import VkOAuthError
from app.schemas.vk_oauth import VkConnectionStatus, VkSafeCheckResult
from app.services.vk_oauth_service import (
    VkOAuthConfigError,
    VkOAuthGuardError,
    VkOAuthService,
    VkStateError,
    verify_state,
)

router = APIRouter(prefix="/integrations/vk", tags=["integrations-vk"])

DbSession = Annotated[Session, Depends(get_db)]
OAuthSvc = Annotated[VkOAuthService, Depends(get_vk_oauth_service)]

_PAGE_CSS = (
    "body{font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;background:#0f1115;color:#e6e6e6;"
    "margin:0;padding:40px 20px}.card{max-width:560px;margin:0 auto;background:#181b22;"
    "border:1px solid #2a2f3a;border-radius:12px;padding:22px}h1{font-size:20px;margin:0 0 12px}"
    ".ok{color:#3ecf8e}.err{color:#ff6b6b}.muted{color:#9aa4b2;font-size:13px}"
    "a{color:#4f8cff}li{margin:4px 0}"
)


def _html_page(title: str, body: str, code: int = 200) -> HTMLResponse:
    doc = (
        "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)} — VK</title><style>{_PAGE_CSS}</style></head>"
        f"<body><div class='card'>{body}</div></body></html>"
    )
    return HTMLResponse(doc, status_code=code)


def _result_body(result: VkSafeCheckResult, project_id: int | None) -> str:
    def row(ok: bool, label: str) -> str:
        mark = "<span class='ok'>✔</span>" if ok else "<span class='err'>✗</span>"
        return f"<li>{mark} {html.escape(label)}</li>"

    back = (
        f"<p><a href='/ui/projects/{project_id}/dashboard'>← Вернуться к проекту</a></p>"
        if project_id
        else ""
    )
    warns = "".join(f"<li class='muted'>{html.escape(w)}</li>" for w in result.warnings)
    name = f" ({html.escape(result.user_name)})" if result.user_name else ""
    return (
        "<h1 class='ok'>VK подключён</h1>"
        "<p>Можно закрыть окно и вернуться в проект.</p>"
        f"<p class='muted'>Секрет сохранён в маске: {html.escape(result.api_key_masked or '••••')} "
        "(сам токен не показывается и не логируется).</p>"
        "<ul>"
        + row(result.user_ok, f"users.get — аккаунт распознан{name}")
        + row(result.group_visible, "groups.get filter=admin — аккаунт видит группу")
        + row(result.photo_upload_ok, "photos.getWallUploadServer — загрузка фото доступна")
        + "</ul>"
        + (f"<p class='err'>{html.escape(result.message)}</p>" if result.error_code else "")
        + (f"<ul>{warns}</ul>" if warns else "")
        + back
    )


@router.get("/oauth/start", response_model=None)
def oauth_start(
    account_id: int, project_id: int, resource_id: int, db: DbSession, service: OAuthSvc
) -> RedirectResponse | HTMLResponse:
    """Собрать URL авторизации VK и отправить пользователя на подтверждение доступа."""
    try:
        url = service.build_start_url(db, account_id, project_id, resource_id)
    except VkOAuthConfigError as exc:
        return _html_page(
            "VK OAuth не настроен",
            f"<h1 class='err'>Не настроено</h1><p>{html.escape(str(exc))}</p>",
            400,
        )
    except VkOAuthGuardError as exc:
        return _html_page(
            "Ошибка", f"<h1 class='err'>Отклонено</h1><p>{html.escape(str(exc))}</p>", 400
        )
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)


@router.get("/oauth/callback")
def oauth_callback(
    db: DbSession,
    service: OAuthSvc,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
) -> HTMLResponse:
    """Обменять code на user-token, сохранить в секрет ресурса и показать safe-check."""
    if error:
        detail = error_description or error
        return _html_page(
            "VK отклонил доступ",
            f"<h1 class='err'>Доступ не выдан</h1><p class='muted'>{html.escape(detail)}</p>",
            400,
        )
    if not code or not state:
        return _html_page(
            "Ошибка", "<h1 class='err'>Нет code/state</h1><p>Повторите подключение.</p>", 400
        )

    project_id: int | None = None
    try:
        raw_project = verify_state(state).get("p")
        project_id = int(raw_project) if raw_project is not None else None
    except (VkStateError, ValueError, TypeError):
        project_id = None

    try:
        result = service.handle_callback(db, code, state)
    except VkStateError as exc:
        return _html_page(
            "Ошибка state",
            f"<h1 class='err'>Недействительный state</h1><p>{html.escape(str(exc))}</p>",
            400,
        )
    except (VkOAuthConfigError, VkOAuthGuardError) as exc:
        return _html_page(
            "Ошибка", f"<h1 class='err'>Отклонено</h1><p>{html.escape(str(exc))}</p>", 400
        )
    except VkOAuthError:
        # Секреты/код не раскрываем в тексте ошибки.
        return _html_page(
            "Ошибка обмена",
            "<h1 class='err'>Не удалось обменять код на токен</h1>"
            "<p class='muted'>VK отклонил обмен. Повторите подключение.</p>",
            400,
        )
    return _html_page("VK подключён", _result_body(result, project_id))


@router.get(
    "/status",
    response_model=VkConnectionStatus,
    dependencies=[Depends(require_vk_resource_access)],
)
def oauth_status(resource_id: int, db: DbSession, service: OAuthSvc) -> VkConnectionStatus:
    """Статус подключения VK-ресурса (без сети): наличие токена и маска."""
    try:
        return service.status(db, resource_id)
    except VkOAuthGuardError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/oauth/check",
    response_model=VkSafeCheckResult,
    dependencies=[Depends(require_vk_resource_access)],
)
def oauth_check(resource_id: int, db: DbSession, service: OAuthSvc) -> VkSafeCheckResult:
    """Повторная безопасная проверка доступа VK по сохранённому токену (без публикаций)."""
    try:
        return service.check_resource(db, resource_id)
    except VkOAuthGuardError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
