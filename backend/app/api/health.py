"""Health- и readiness-эндпоинты.

``/health`` — простой liveness-чек (сервис жив). ``/health/readiness`` —
readiness-чек: сообщает окружение, тип БД и какие интеграции настроены, без
сетевых вызовов и без обращения к БД. В production добавляет предупреждения о
не настроенных интеграциях и о SQLite вместо PostgreSQL.
"""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.config import get_settings

# Имя сервиса фиксировано контрактом /health и не зависит от настроек.
SERVICE_NAME = "ai-smm-bot"

router = APIRouter()


class HealthResponse(BaseModel):
    """Ответ health-check."""

    status: str
    service: str


class ReadinessResponse(BaseModel):
    """Ответ readiness-check: готовность окружения и интеграций."""

    status: str
    app_env: str
    database: str
    integrations: dict[str, bool] = Field(default_factory=dict)
    yandex_disk_public_mode: bool = False
    warnings: list[str] = Field(default_factory=list)


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Проверка работоспособности сервиса (liveness)."""
    return HealthResponse(status="ok", service=SERVICE_NAME)


@router.get("/health/readiness", response_model=ReadinessResponse, tags=["health"])
def readiness() -> ReadinessResponse:
    """Готовность сервиса: окружение, БД и настроенные интеграции (без сети)."""
    settings = get_settings()
    integrations = {
        "telegram": settings.telegram_configured,
        "vk": settings.vk_configured,
        "yandex_disk": settings.yandex_disk_configured,
        "ai": settings.ai_configured,
    }
    warnings: list[str] = []
    if settings.yandex_disk_public_mode and not settings.yandex_disk_public_configured:
        warnings.append(
            "Публичный режим Яндекс Диска включён, но YANDEX_DISK_PUBLIC_SMM_URL не задан"
        )
    if settings.is_production:
        if settings.database_is_sqlite:
            warnings.append("В production используется SQLite — задайте PostgreSQL DATABASE_URL")
        for name, configured in integrations.items():
            if not configured:
                warnings.append(f"Интеграция '{name}' не настроена для боевого режима")

    return ReadinessResponse(
        status="ready",
        app_env=settings.app_env,
        database="sqlite" if settings.database_is_sqlite else "postgresql",
        integrations=integrations,
        yandex_disk_public_mode=settings.yandex_disk_public_mode,
        warnings=warnings,
    )
