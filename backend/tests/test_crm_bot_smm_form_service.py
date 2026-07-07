"""Тесты сервиса формы «БОТ СММ»: схема и валидация онбординга."""

import copy
import json
from pathlib import Path
from typing import Any

from app.services.crm_bot_smm_form_service import CrmBotSmmFormService

EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "crm_bot_smm_onboarding_teeon.json"
)


def _example() -> dict[str, Any]:
    return copy.deepcopy(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))


def test_form_schema_has_required_sections() -> None:
    schema = CrmBotSmmFormService().build_form_schema()
    keys = {section.key for section in schema.sections}
    assert {
        "project",
        "site_or_topics",
        "resources",
        "keywords",
        "content_sources",
        "promotion_categories",
        "publishing_plan",
    } <= keys
    assert "auto_publish" in schema.disabled_modes


def test_form_schema_repeatable_and_secret_field() -> None:
    schema = CrmBotSmmFormService().build_form_schema()
    resources = next(s for s in schema.sections if s.key == "resources")
    assert resources.repeatable is True
    assert resources.min_items == 1
    api_field = next(f for f in resources.fields if f.name == "api_key")
    assert api_field.type == "secret"


def test_validate_example_is_valid() -> None:
    result = CrmBotSmmFormService().validate_onboarding_payload(_example())
    assert result.valid, result.errors


def test_website_required_when_has_website_true() -> None:
    payload = _example()
    payload["site_or_topics"]["website_url"] = ""
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("website_url" in err for err in result.errors)


def test_topics_required_when_no_website() -> None:
    payload = _example()
    payload["site_or_topics"]["has_website"] = False
    payload["site_or_topics"]["website_url"] = None
    payload["site_or_topics"]["manual_topics"] = []
    payload["site_or_topics"]["reference_sites"] = []
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("manual_topics" in err or "reference_sites" in err for err in result.errors)


def test_vk_resource_requires_external_id_or_url() -> None:
    payload = _example()
    for resource in payload["resources"]:
        if resource["resource_type"] == "vk":
            resource["external_id"] = None
            resource["url"] = None
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("vk" in err for err in result.errors)


def test_yandex_disk_requires_public_url() -> None:
    payload = _example()
    for resource in payload["resources"]:
        if resource["resource_type"] == "yandex_disk":
            resource["yandex_public_url"] = None
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("yandex_disk" in err for err in result.errors)


def test_auto_publish_mode_forbidden() -> None:
    payload = _example()
    payload["publishing_plans"][0]["mode"] = "auto_publish"
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("auto_publish" in err for err in result.errors)


def test_live_enabled_forbidden() -> None:
    payload = _example()
    payload["resources"][0]["live_enabled"] = True
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("live_enabled" in err for err in result.errors)


def test_at_least_one_resource_required() -> None:
    payload = _example()
    payload["resources"] = []
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("ресурс" in err.lower() for err in result.errors)


def test_category_requires_keywords_or_priorities() -> None:
    payload = _example()
    for category in payload["promotion_categories"]:
        category["keyword_queries"] = []
        category["product_priorities"] = {}
        category["technology_priorities"] = {}
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)
    assert not result.valid
    assert any("prioritie" in err or "ключи" in err for err in result.errors)
