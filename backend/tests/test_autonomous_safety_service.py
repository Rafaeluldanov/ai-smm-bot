"""Тесты safety-guardrails автономного режима."""

from types import SimpleNamespace

from app.schemas.autonomous import AutonomousModeSettings
from app.services.autonomous_safety_service import AutonomousSafetyService


def _service() -> AutonomousSafetyService:
    return AutonomousSafetyService()


def test_semi_auto_forbids_auto_publish() -> None:
    settings = AutonomousModeSettings(allow_auto_publish=True, allow_auto_schedule=True)
    effective = _service().get_mode_settings("semi_auto", settings)
    assert effective.allow_auto_publish is False
    assert effective.allow_auto_schedule is False
    assert effective.require_human_review is True


def test_auto_publish_requires_flag() -> None:
    off = _service().get_mode_settings(
        "auto_publish", AutonomousModeSettings(allow_auto_publish=False)
    )
    assert off.allow_auto_publish is False
    on = _service().get_mode_settings(
        "auto_publish",
        AutonomousModeSettings(allow_auto_publish=True, require_human_review=False),
    )
    assert on.allow_auto_publish is True


def test_needs_media_cannot_auto_schedule() -> None:
    post = SimpleNamespace(status="needs_media")
    can, reasons = _service().can_auto_schedule(post)
    assert can is False
    assert reasons


def test_external_stock_cannot_auto_approve() -> None:
    post = SimpleNamespace(status="draft", media_asset_id=1)
    media = SimpleNamespace(
        source_type="external_stock",
        license_type="external_needs_review",
        status="needs_license_review",
    )
    can, reasons = _service().can_auto_approve(post, media)
    assert can is False
    assert reasons


def test_dry_run_settings() -> None:
    effective = _service().get_mode_settings("dry_run", None)
    assert effective.dry_run is True
    assert effective.allow_auto_publish is False
    assert effective.allow_auto_schedule is False
    assert effective.require_human_review is True


def test_can_auto_publish_only_approved_or_scheduled() -> None:
    assert _service().can_auto_publish(SimpleNamespace(status="approved"))[0] is True
    assert _service().can_auto_publish(SimpleNamespace(status="scheduled"))[0] is True
    assert _service().can_auto_publish(SimpleNamespace(status="draft"))[0] is False
    assert _service().can_auto_publish(SimpleNamespace(status="needs_media"))[0] is False
