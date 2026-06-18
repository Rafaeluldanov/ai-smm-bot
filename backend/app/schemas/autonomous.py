"""Pydantic-схемы автономного режима (Этап 10)."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _default_platforms() -> list[str]:
    return ["telegram", "vk"]


class AutonomousModeSettings(BaseModel):
    """Настройки автономного прогона (что разрешено автоматизировать)."""

    allow_external_images: bool = True
    allow_auto_approve: bool = False
    allow_auto_schedule: bool = False
    allow_auto_publish: bool = False
    require_human_review: bool = True
    platforms: list[str] = Field(default_factory=_default_platforms)
    dry_run: bool = False


class AutonomousRunStepRead(BaseModel):
    """Шаг прогона в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_name: str
    status: str
    entity_type: str | None = None
    entity_id: int | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AutonomousRunStepCreate(BaseModel):
    """Данные для создания шага."""

    run_id: int
    step_name: str
    status: str = "pending"
    entity_type: str | None = None
    entity_id: int | None = None
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AutonomousRunStepUpdate(BaseModel):
    """Частичное обновление шага."""

    status: str | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    input_payload: dict[str, Any] | None = None
    output_payload: dict[str, Any] | None = None
    warnings: list[str] | None = None
    errors: list[str] | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AutonomousRunRead(BaseModel):
    """Прогон в ответах API."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    mode: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    weeks: int
    posts_per_week: int
    business_priorities: dict[str, int] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class AutonomousRunCreate(BaseModel):
    """Данные для создания прогона."""

    project_id: int
    mode: str
    status: str = "created"
    weeks: int = 1
    posts_per_week: int = 3
    business_priorities: dict[str, int] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class AutonomousRunUpdate(BaseModel):
    """Частичное обновление прогона."""

    status: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    warnings: list[str] | None = None
    errors: list[str] | None = None


class AutonomousRunRequest(BaseModel):
    """Запрос на автономный прогон."""

    project_id: int | None = None
    project_slug: str | None = None
    mode: str = "semi_auto"
    weeks: int = 1
    posts_per_week: int = 3
    business_priorities: dict[str, int] | None = None
    settings: AutonomousModeSettings | None = None


class AutonomousRunSummary(BaseModel):
    """Сводка результатов прогона."""

    selected_topics_count: int = 0
    generated_posts_count: int = 0
    posts_needing_media_count: int = 0
    external_candidates_count: int = 0
    submitted_for_review_count: int = 0
    scheduled_publications_count: int = 0
    published_publications_count: int = 0
    failed_steps_count: int = 0


class AutonomousRunResult(BaseModel):
    """Результат прогона (для API run/dry-run)."""

    run: AutonomousRunRead
    steps: list[AutonomousRunStepRead] = Field(default_factory=list)
    selected_topics: int = 0
    generated_posts: int = 0
    posts_needing_media: int = 0
    external_candidates: int = 0
    submitted_for_review: int = 0
    scheduled_publications: int = 0
    published_publications: int = 0
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class AutonomousRunReport(BaseModel):
    """Отчёт по прогону с рекомендациями."""

    run_id: int
    project_id: int
    project_slug: str
    mode: str
    status: str
    summary: AutonomousRunSummary
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    steps: list[AutonomousRunStepRead] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)


class AutonomousSafetyReport(BaseModel):
    """Результат проверки безопасности запроса."""

    allowed: bool
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    effective_settings: AutonomousModeSettings
