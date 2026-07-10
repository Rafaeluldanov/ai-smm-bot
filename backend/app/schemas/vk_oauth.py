"""Pydantic-схемы VK OAuth connect flow (наружу — без токена/секретов)."""

from pydantic import BaseModel, Field


class VkConnectionStatus(BaseModel):
    """Статус подключения VK-ресурса (без сети): факт наличия токена + маска + конфиг.

    Секреты наружу не отдаются: только факт подключения, маска, публичные app_id /
    redirect_uri и флаг ``configured`` (задан ли ``VK_APP_SECRET`` на сервере).
    """

    resource_id: int
    connected: bool
    api_key_present: bool
    api_key_masked: str | None = None
    external_id: str | None = None
    group_id: str | None = None
    app_id: str | None = None
    redirect_uri: str | None = None
    configured: bool = False


class VkSafeCheckResult(BaseModel):
    """Результат безопасной проверки доступа VK (без публикаций, только read + upload-URL).

    Токен наружу не отдаётся — только факт подключения, маска и статусы проверок.
    """

    resource_id: int
    connected: bool
    api_key_present: bool
    api_key_masked: str | None = None
    # users.get: аккаунт распознан как пользователь.
    user_ok: bool = False
    user_name: str | None = None
    # groups.get filter=admin: аккаунт видит группу ресурса как админ.
    group_visible: bool = False
    # photos.getWallUploadServer: доступна загрузка фото на стену (upload-URL получен).
    photo_upload_ok: bool = False
    error_code: int | None = None
    message: str = ""
    warnings: list[str] = Field(default_factory=list)
