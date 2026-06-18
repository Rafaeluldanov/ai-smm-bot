"""Тесты статусов поста и переходов."""

import pytest

from app.services.post_status_service import (
    InvalidPostStatusError,
    InvalidPostStatusTransitionError,
    can_transition,
    get_allowed_post_statuses,
    validate_transition,
)


def test_allowed_statuses() -> None:
    statuses = get_allowed_post_statuses()
    assert set(statuses) == {
        "draft",
        "needs_review",
        "approved",
        "scheduled",
        "published",
        "rejected",
        "needs_media",
    }


def test_valid_transitions() -> None:
    assert can_transition("draft", "needs_review") is True
    assert can_transition("approved", "scheduled") is True
    assert can_transition("needs_media", "draft") is True


def test_invalid_transition() -> None:
    assert can_transition("published", "rejected") is False
    assert can_transition("draft", "scheduled") is False


def test_validate_transition_forbidden_raises() -> None:
    with pytest.raises(InvalidPostStatusTransitionError):
        validate_transition("published", "rejected")


def test_validate_transition_unknown_raises() -> None:
    with pytest.raises(InvalidPostStatusError):
        validate_transition("draft", "totally-unknown")
