"""Схемы API self-service подключений платформ.

Секреты (``api_key``/``app_secret``) — **write-only**: принимаются на вход, но никогда
не возвращаются в ответах (наружу — только маска/факт наличия из сервиса).
"""

from pydantic import BaseModel, Field


class PlatformConnectionUpsert(BaseModel):
    """Данные формы подключения платформы (создание/обновление).

    Пустой секрет = «не менять» (оставить сохранённый). ``live_enabled`` из UI
    игнорируется сервисом (всегда false) — защита от случайной публикации.
    """

    title: str | None = None
    external_id: str | None = None
    url: str | None = None
    root_folder: str | None = None
    app_id: str | None = None
    redirect_uri: str | None = None
    default_cta: str | None = None
    tags: list[str] = Field(default_factory=list)
    # Секреты — write-only.
    api_key: str | None = None
    app_secret: str | None = None
    # Принимается, но сервис держит live выключенным на этом этапе.
    live_enabled: bool = False
