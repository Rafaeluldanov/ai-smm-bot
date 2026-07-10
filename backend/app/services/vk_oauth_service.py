"""Сервис VK OAuth connect flow: подключение пользовательского токена к ресурсу.

Оркестрирует подключение VK через кнопку (без ручного копирования ссылки):
1. ``build_start_url`` — собирает подписанный ``state`` и URL авторизации VK;
2. ``handle_callback`` — проверяет ``state``, меняет ``code`` на user-token, кладёт
   его в СЕКРЕТ ресурса (через ``crm_secret_service``) и запускает safe-check;
3. ``check_resource`` / ``status`` — статус подключения и повторная проверка доступа.

Safe-check (без публикаций): ``users.get`` (это пользователь?), ``groups.get
filter=admin`` (видит ли группу как админ), ``photos.getWallUploadServer`` (можно
ли грузить фото на стену — при ``error_code=27`` это НЕ user-token или нет прав).

Безопасность: наружу отдаётся только маска секрета и булевы статусы; токен и
секрет приложения не логируются и не возвращаются. ``state`` подписан HMAC —
подделать account/project/resource нельзя.
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
from typing import Any

from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.vk.oauth import VkApiError, VkOAuthClient, VkOAuthError
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import project_repository
from app.schemas.crm_bot_smm import CrmSmmResourceUpdate
from app.schemas.vk_oauth import VkConnectionStatus, VkSafeCheckResult
from app.services import crm_secret_service

# Секрет подписи state — тот же источник, что и dev-токен (НЕ из .env, можно
# переопределить ``SAAS_DEV_TOKEN_SECRET``). Не продакшн-крипта, но защищает от
# тривиальной подделки account/project/resource в callback.
_STATE_SECRET = os.environ.get(
    "SAAS_DEV_TOKEN_SECRET", "saas-dev-token-secret-not-for-production"
).encode("utf-8")

# VK error_code=27: токен не пользовательский или нет прав на photos.* — понятное
# сообщение для UI (см. задание v0.2.5).
_ERROR_27 = 27
_FAILURE_MESSAGE = (
    "Токен не пользовательский или аккаунт не имеет прав администратора/редактора группы."
)
_ERROR_27_MESSAGE = _FAILURE_MESSAGE


class VkOAuthConfigError(Exception):
    """VK OAuth не сконфигурирован (нет VK_APP_ID / secret / redirect_uri)."""


class VkOAuthGuardError(Exception):
    """Ресурс не найден, не VK, или не принадлежит проекту/аккаунту."""


class VkStateError(Exception):
    """Невалидный/подделанный ``state`` в callback."""


def sign_state(data: dict[str, Any]) -> str:
    """Подписать полезную нагрузку state (base64url + HMAC-SHA256)."""
    raw = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    sig = hmac.new(_STATE_SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def verify_state(state: str) -> dict[str, Any]:
    """Проверить подпись state и вернуть полезную нагрузку. Иначе — VkStateError."""
    if not state or "." not in state:
        raise VkStateError("пустой или неполный state")
    body, _, sig = state.rpartition(".")
    expected = hmac.new(_STATE_SECRET, body.encode("ascii"), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise VkStateError("подпись state неверна")
    try:
        padded = body + "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise VkStateError("повреждённый state") from exc
    if not isinstance(payload, dict):
        raise VkStateError("неожиданный формат state")
    return payload


def _normalize_group_id(external_id: str | None) -> str | None:
    """Из external_id VK-ресурса получить положительный числовой group_id."""
    if not external_id:
        return None
    digits = "".join(ch for ch in str(external_id) if ch.isdigit())
    return digits or None


class VkOAuthService:
    """Подключение VK user-token к ресурсу и безопасная проверка доступа."""

    def __init__(self, settings: Settings, transport: Any | None = None) -> None:
        self._settings = settings
        self._client = VkOAuthClient(transport=transport)

    # --- Конфигурация ---

    def _require_start_config(self) -> tuple[str, str, str]:
        app_id = (self._settings.vk_app_id or "").strip()
        redirect = (self._settings.vk_oauth_redirect_uri or "").strip()
        scope = (self._settings.vk_oauth_scope or "wall,photos,groups,offline").strip()
        if not app_id or not redirect:
            raise VkOAuthConfigError(
                "VK OAuth не настроен: задайте VK_APP_ID и VK_OAUTH_REDIRECT_URI."
            )
        return app_id, redirect, scope

    # --- Start ---

    def _guard_vk_resource(
        self, db: Session, resource_id: int, project_id: int | None, account_id: int | None
    ) -> Any:
        resource = crm_repo.get_resource_by_id(db, resource_id)
        if resource is None or resource.resource_type != "vk":
            raise VkOAuthGuardError("VK-ресурс не найден.")
        if project_id is not None and resource.project_id != project_id:
            raise VkOAuthGuardError("Ресурс не принадлежит указанному проекту.")
        if account_id is not None:
            project = project_repository.get_project_by_id(db, resource.project_id)
            if project is not None and project.account_id not in (None, account_id):
                raise VkOAuthGuardError("Проект принадлежит другому аккаунту.")
        return resource

    def build_start_url(
        self, db: Session, account_id: int, project_id: int, resource_id: int
    ) -> str:
        """Собрать URL авторизации VK с подписанным state (после guard ресурса)."""
        app_id, redirect, scope = self._require_start_config()
        self._guard_vk_resource(db, resource_id, project_id, account_id)
        state = sign_state(
            {
                "a": account_id,
                "p": project_id,
                "r": resource_id,
                "c": secrets.token_hex(8),
            }
        )
        return self._client.build_authorize_url(
            client_id=app_id, redirect_uri=redirect, scope=scope, state=state
        )

    # --- Callback ---

    def handle_callback(self, db: Session, code: str, state: str) -> VkSafeCheckResult:
        """Проверить state, обменять code на user-token, сохранить в секрет, safe-check."""
        payload = verify_state(state)
        resource_id = int(payload.get("r", 0))
        resource = self._guard_vk_resource(db, resource_id, payload.get("p"), payload.get("a"))

        app_id = (self._settings.vk_app_id or "").strip()
        secret = (self._settings.vk_app_secret or "").strip()
        redirect = (self._settings.vk_oauth_redirect_uri or "").strip()
        if not app_id or not secret or not redirect:
            raise VkOAuthConfigError(
                "VK OAuth не настроен: задайте VK_APP_ID, VK_APP_SECRET, VK_OAUTH_REDIRECT_URI."
            )

        token_data = self._client.exchange_code(
            client_id=app_id, client_secret=secret, redirect_uri=redirect, code=code
        )
        token = str(token_data["access_token"])
        # Сохраняем user-token в СЕКРЕТ ресурса (репозиторий шифрует + маскирует).
        crm_repo.update_resource(db, resource, CrmSmmResourceUpdate(api_key=token))
        return self._safe_check(resource, token)

    # --- Статус и проверка ---

    def status(self, db: Session, resource_id: int) -> VkConnectionStatus:
        """Статус подключения VK-ресурса без обращения к сети (+ публичный VK-конфиг)."""
        resource = self._guard_vk_resource(db, resource_id, None, None)
        present = crm_secret_service.is_encrypted(resource.api_key_encrypted)
        app_id = getattr(self._settings, "vk_app_id", "") or ""
        secret = getattr(self._settings, "vk_app_secret", "") or ""
        redirect = getattr(self._settings, "vk_oauth_redirect_uri", "") or ""
        default_group = getattr(self._settings, "vk_default_group_id", None)
        group_id = _normalize_group_id(resource.external_id) or (default_group or None)
        return VkConnectionStatus(
            resource_id=resource.id,
            connected=present,
            api_key_present=present,
            api_key_masked=resource.api_key_masked,
            external_id=resource.external_id,
            group_id=group_id,
            app_id=(app_id or None),
            redirect_uri=(redirect or None),
            configured=bool(app_id and secret and redirect),
        )

    def check_resource(self, db: Session, resource_id: int) -> VkSafeCheckResult:
        """Повторный safe-check по сохранённому токену ресурса (без публикаций)."""
        resource = self._guard_vk_resource(db, resource_id, None, None)
        if not crm_secret_service.is_encrypted(resource.api_key_encrypted):
            return VkSafeCheckResult(
                resource_id=resource.id,
                connected=False,
                api_key_present=False,
                api_key_masked=None,
                message="VK-токен не подключён — нажмите «Подключить VK».",
            )
        token = crm_secret_service.decrypt_secret(resource.api_key_encrypted)
        return self._safe_check(resource, token)

    # --- Safe-check (users.get / groups.get / photos.getWallUploadServer) ---

    def _safe_check(self, resource: Any, token: str) -> VkSafeCheckResult:
        result = VkSafeCheckResult(
            resource_id=resource.id,
            connected=True,
            api_key_present=True,
            api_key_masked=resource.api_key_masked,
        )
        group_id = _normalize_group_id(resource.external_id)

        # 1) users.get — распознан ли токен как пользовательский.
        try:
            data = self._client.call_method("users.get", token, {})
            users = data.get("response") or []
            if users:
                first = str(users[0].get("first_name", "")).strip()
                last = str(users[0].get("last_name", "")).strip()
                result.user_ok = True
                result.user_name = (f"{first} {last}").strip() or f"id{users[0].get('id')}"
        except VkApiError as exc:
            result.warnings.append(f"users.get: VK error {exc.error_code}")
        except VkOAuthError:
            result.warnings.append("users.get: сетевая ошибка")

        # 2) groups.get filter=admin — видит ли аккаунт группу ресурса как админ.
        if group_id is not None:
            try:
                data = self._client.call_method(
                    "groups.get", token, {"filter": "admin", "extended": 0}
                )
                response = data.get("response") or {}
                items = response.get("items") if isinstance(response, dict) else response
                admin_ids = {str(i) for i in (items or [])}
                if group_id in admin_ids:
                    result.group_visible = True
            except VkApiError as exc:
                result.warnings.append(f"groups.get: VK error {exc.error_code}")
            except VkOAuthError:
                result.warnings.append("groups.get: сетевая ошибка")

        # 3) photos.getWallUploadServer — доступна ли загрузка фото (без загрузки).
        if group_id is not None:
            try:
                data = self._client.call_method(
                    "photos.getWallUploadServer", token, {"group_id": group_id}
                )
                if (data.get("response") or {}).get("upload_url"):
                    result.photo_upload_ok = True
            except VkApiError as exc:
                result.error_code = exc.error_code
                if exc.error_code == _ERROR_27:
                    result.message = _ERROR_27_MESSAGE
                else:
                    result.warnings.append(f"photos.getWallUploadServer: VK error {exc.error_code}")
            except VkOAuthError:
                result.warnings.append("photos.getWallUploadServer: сетевая ошибка")
        else:
            result.warnings.append(
                "У ресурса не задан числовой group_id — проверка группы пропущена."
            )

        if result.user_ok and result.photo_upload_ok:
            result.message = "VK user token подключён: доступ к загрузке фото подтверждён."
        elif not result.message:
            # Safe-check не прошёл (не user-token / нет прав админа) — понятная причина.
            result.message = _FAILURE_MESSAGE
        return result
