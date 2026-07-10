"""Pydantic-схемы аудит-лога (без секретов)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditLogEntryRead(BaseModel):
    """Запись аудита в ответах API (метаданные санитизированы)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int | None = None
    user_id: int | None = None
    project_id: int | None = None
    action: str
    entity_type: str
    entity_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="entry_metadata")
    created_at: datetime
