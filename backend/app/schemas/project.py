"""Pydantic-схемы для Project.

Правило для slug (выбранный подход — НОРМАЛИЗАЦИЯ к нижнему регистру):
- допускаются только латиница, цифры, дефис ``-`` и подчёркивание ``_``;
- значение приводится к нижнему регистру (``TEEON`` -> ``teeon``);
- пробелы и кириллица не допускаются (ошибка валидации);
- минимальная длина — 2 символа.
"""

import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_PATTERN = re.compile(r"^[a-z0-9_-]+$")


def normalize_slug(value: str) -> str:
    """Привести slug к нижнему регистру и проверить допустимость."""
    normalized = value.strip().lower()
    if len(normalized) < 2:
        raise ValueError("slug должен содержать не менее 2 символов")
    if not _SLUG_PATTERN.fullmatch(normalized):
        raise ValueError(
            "slug может содержать только латиницу (нижний регистр), цифры, "
            "'-' и '_', без пробелов и кириллицы"
        )
    return normalized


class ProjectBase(BaseModel):
    """Общие поля проекта."""

    name: str = Field(min_length=1)
    slug: str
    description: str | None = None
    website_url: str | None = None
    is_active: bool = True

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str) -> str:
        return normalize_slug(value)


class ProjectCreate(ProjectBase):
    """Данные для создания проекта."""


class ProjectUpdate(BaseModel):
    """Данные для частичного обновления проекта (все поля опциональны)."""

    name: str | None = Field(default=None, min_length=1)
    slug: str | None = None
    description: str | None = None
    website_url: str | None = None
    is_active: bool | None = None

    @field_validator("slug")
    @classmethod
    def _validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_slug(value)


class ProjectRead(ProjectBase):
    """Представление проекта в ответах API (используется и для списка)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
