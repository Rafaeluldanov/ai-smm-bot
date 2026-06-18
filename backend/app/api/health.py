"""Health-check эндпоинт."""

from fastapi import APIRouter
from pydantic import BaseModel

# Имя сервиса фиксировано контрактом /health и не зависит от настроек.
SERVICE_NAME = "ai-smm-bot"

router = APIRouter()


class HealthResponse(BaseModel):
    """Ответ health-check."""

    status: str
    service: str


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Проверка работоспособности сервиса."""
    return HealthResponse(status="ok", service=SERVICE_NAME)
