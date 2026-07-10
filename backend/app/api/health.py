"""Health- и readiness-эндпоинты.

``/health`` — простой liveness-чек (сервис жив). ``/health/readiness`` —
readiness-чек: сообщает окружение, тип БД и какие интеграции настроены, без
сетевых вызовов и без обращения к БД. В production добавляет предупреждения о
не настроенных интеграциях и о SQLite вместо PostgreSQL.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.config import (
    Settings,
    get_settings,
    security_checks,
)

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
    media_enhancement_enabled: bool = False
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
    if (
        settings.telegram_live_publishing_enabled
        and not settings.telegram_live_publishing_configured
    ):
        warnings.append(
            "Telegram live publishing включён, но не хватает токена/канала по умолчанию"
        )
    if settings.vk_live_publishing_enabled and not settings.vk_live_publishing_configured:
        warnings.append("VK live publishing включён, но не хватает токена/группы по умолчанию")
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
        media_enhancement_enabled=settings.media_enhancement_enabled,
        warnings=warnings,
    )


class SecurityCheckRead(BaseModel):
    """Один пункт security-чек-листа."""

    key: str
    ok: bool
    severity: str  # info | warning | error
    message: str


class SecurityReadinessResponse(BaseModel):
    """Security-готовность: строгий чек-лист безопасности перед публичным запуском."""

    status: str  # ok | warning | error
    environment: str  # local | production
    app_env: str
    production_ready: bool = False
    checks: list[SecurityCheckRead] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.get(
    "/health/security-readiness",
    response_model=SecurityReadinessResponse,
    tags=["health"],
)
def security_readiness(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SecurityReadinessResponse:
    """Security-чек-лист. В production при фатальных ошибках → 503; в local — 200."""
    checks = security_checks(settings)
    errors = [c.message for c in checks if c.severity == "error"]
    warnings = [c.message for c in checks if c.severity == "warning"]
    if errors:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        result_status = "error"
    elif warnings:
        result_status = "warning"
    else:
        result_status = "ok"
    return SecurityReadinessResponse(
        status=result_status,
        environment="production" if settings.is_production else "local",
        app_env=settings.app_env,
        production_ready=not errors,
        checks=[
            SecurityCheckRead(key=c.key, ok=c.ok, severity=c.severity, message=c.message)
            for c in checks
        ],
        errors=errors,
        warnings=warnings,
    )
