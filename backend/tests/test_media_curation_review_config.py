"""Тесты конфигурации collaborative review курирования (v0.4.9): безопасные дефолты."""

from app.config import Settings


def _s(**kw: object) -> Settings:
    return Settings(**kw)


def test_defaults_safe() -> None:
    s = _s()
    assert s.media_curation_review_enabled is True
    assert s.media_curation_review_require_approval is True
    assert s.media_curation_review_allow_self_approval is True


def test_require_approval_effective_true_by_default() -> None:
    assert _s().media_curation_review_require_approval_effective is True


def test_auto_apply_false_by_default() -> None:
    assert _s().media_curation_review_auto_apply_after_approval is False


def test_notify_false_by_default() -> None:
    assert _s().media_curation_review_notify_enabled is False


def test_external_ai_false_by_default() -> None:
    assert _s().media_curation_review_external_ai_enabled is False


def test_require_approval_disabled_when_review_disabled() -> None:
    s = _s(media_curation_review_enabled=False)
    assert s.media_curation_review_enabled_effective is False
    assert s.media_curation_review_require_approval_effective is False


def test_require_approval_disabled_when_curation_disabled() -> None:
    s = _s(media_curation_enabled=False)
    assert s.media_curation_review_enabled_effective is False
    assert s.media_curation_review_require_approval_effective is False


def test_default_priority_safe() -> None:
    assert _s().media_curation_review_default_priority_safe == "normal"
    assert (
        _s(
            media_curation_review_default_priority="high"
        ).media_curation_review_default_priority_safe
        == "high"
    )
    assert (
        _s(
            media_curation_review_default_priority="bogus"
        ).media_curation_review_default_priority_safe
        == "normal"
    )


def test_overdue_and_comment_limits_safe() -> None:
    assert (
        _s(media_curation_review_overdue_days=7).media_curation_review_overdue_seconds == 7 * 86400
    )
    assert _s(media_curation_review_overdue_days=0).media_curation_review_overdue_seconds >= 86400
    assert (
        _s(
            media_curation_review_max_comments_per_task=100
        ).media_curation_review_max_comments_per_task_safe
        == 100
    )
    assert (
        _s(
            media_curation_review_max_comments_per_task=0
        ).media_curation_review_max_comments_per_task_safe
        >= 1
    )


def test_parsing_works() -> None:
    s = _s(
        media_curation_review_require_approval=False,
        media_curation_review_allow_self_approval=False,
        media_curation_review_auto_apply_after_approval=False,
        media_curation_review_notify_enabled=False,
    )
    assert s.media_curation_review_require_approval is False
    assert s.media_curation_review_allow_self_approval is False


def test_no_live_flag_implied() -> None:
    s = _s(
        media_curation_review_enabled=True,
        media_curation_review_require_approval=True,
    )
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
    assert s.media_curation_review_external_ai_enabled is False
    assert s.media_curation_review_auto_apply_after_approval is False
