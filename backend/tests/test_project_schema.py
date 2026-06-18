"""Тесты валидации slug в схемах Project."""

import pytest
from pydantic import ValidationError

from app.schemas.project import ProjectCreate, ProjectUpdate


def test_valid_slug_passes() -> None:
    project = ProjectCreate(name="Demo", slug="valid-slug_1")
    assert project.slug == "valid-slug_1"


def test_slug_is_lowercased() -> None:
    # Выбранный подход: slug приводится к нижнему регистру, а не отклоняется.
    project = ProjectCreate(name="TEEON", slug="TEEON")
    assert project.slug == "teeon"


def test_slug_with_space_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Demo", slug="bad slug")


def test_slug_with_cyrillic_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Demo", slug="проект")


def test_slug_too_short_rejected() -> None:
    with pytest.raises(ValidationError):
        ProjectCreate(name="Demo", slug="a")


def test_update_slug_optional_and_normalized() -> None:
    # slug в обновлении опционален...
    assert ProjectUpdate().slug is None
    # ...но если задан — нормализуется по тем же правилам.
    assert ProjectUpdate(slug="New_Slug").slug == "new_slug"
