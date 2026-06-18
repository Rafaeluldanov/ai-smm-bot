"""Тесты политики лицензий и безопасности внешних изображений."""

from types import SimpleNamespace
from typing import Any

from app.services.external_image_license_policy import (
    build_forbidden_usage,
    can_convert_to_media_asset,
    evaluate_candidate_safety,
    normalize_license_name,
)


def _candidate(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 1,
        "commercial_use_allowed": True,
        "modification_allowed": True,
        "attribution_required": False,
        "contains_people": False,
        "contains_logo": False,
        "safe_for_business": True,
        "author_name": "Автор",
        "license_name": "CC0",
        "license_url": "https://creativecommons.org/publicdomain/zero/1.0/",
        "review_status": "approved",
        "source_url": "https://x/1",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_cannot_claim_as_own_case() -> None:
    report = evaluate_candidate_safety(_candidate())
    assert report.can_claim_as_own_case is False
    assert any("кейс" in w for w in report.warnings)


def test_non_commercial_forbidden() -> None:
    candidate = _candidate(commercial_use_allowed=False)
    report = evaluate_candidate_safety(candidate)
    assert report.can_use_organically is False
    assert report.can_use_in_ads is False
    assert "commercial_use" in build_forbidden_usage(candidate)


def test_attribution_required_text() -> None:
    report = evaluate_candidate_safety(_candidate(attribution_required=True))
    assert report.required_attribution
    assert "Автор" in report.required_attribution


def test_logo_blocks_ads() -> None:
    report = evaluate_candidate_safety(_candidate(contains_logo=True))
    assert report.can_use_in_ads is False
    assert any("логот" in w.lower() for w in report.warnings)


def test_rejected_cannot_convert() -> None:
    can, reasons = can_convert_to_media_asset(_candidate(review_status="rejected"))
    assert can is False
    assert reasons


def test_unsafe_cannot_convert() -> None:
    can, _ = can_convert_to_media_asset(_candidate(safe_for_business=False))
    assert can is False


def test_approved_safe_can_convert() -> None:
    can, reasons = can_convert_to_media_asset(_candidate(review_status="approved"))
    assert can is True
    assert reasons == []


def test_normalize_license_name() -> None:
    assert normalize_license_name("  CC  BY  4.0 ") == "cc by 4.0"
