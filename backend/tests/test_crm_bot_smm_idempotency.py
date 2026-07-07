"""Тесты идемпотентности apply онбординга «БОТ СММ».

Повторный apply одного и того же пейлоада не должен плодить дубли; изменённые
данные должны обновлять существующие записи; пустой api_key не затирает секрет;
dry-run по-прежнему ничего не пишет.
"""

import copy
import json
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as repo
from app.services.crm_bot_smm_form_service import CrmBotSmmFormService

EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "crm_bot_smm_onboarding_teeon.json"
)

EXPECTED_COUNTS = {
    "resources": 4,
    "keywords": 4,
    "content_sources": 2,
    "categories": 1,
    "plans": 1,
}


def _example() -> dict[str, Any]:
    return copy.deepcopy(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))


def _counts(db: Session, config_id: int) -> dict[str, int]:
    categories = repo.list_categories_by_config(db, config_id)
    return {
        "resources": len(repo.list_resources_by_config(db, config_id)),
        "keywords": len(repo.list_keywords_by_config(db, config_id)),
        "content_sources": len(repo.list_content_sources_by_config(db, config_id)),
        "categories": len(categories),
        "plans": sum(len(repo.list_plans_by_category(db, c.id)) for c in categories),
    }


def test_apply_twice_creates_no_duplicates(db_session: Session) -> None:
    service = CrmBotSmmFormService()

    first = service.apply_onboarding_payload(db_session, _example(), dry_run=False)
    assert first.config_id is not None
    assert _counts(db_session, first.config_id) == EXPECTED_COUNTS

    second = service.apply_onboarding_payload(db_session, _example(), dry_run=False)
    # Тот же конфиг, те же счётчики — дубли не создаются.
    assert second.config_id == first.config_id
    assert _counts(db_session, second.config_id) == EXPECTED_COUNTS
    assert len(repo.list_configs(db_session)) == 1


def test_apply_changed_data_updates_existing_records(db_session: Session) -> None:
    service = CrmBotSmmFormService()
    first = service.apply_onboarding_payload(db_session, _example(), dry_run=False)
    assert first.config_id is not None
    config_id = first.config_id

    payload = _example()
    changed_query = payload["keywords"][0]["query"]
    payload["keywords"][0]["priority"] = 5
    payload["keywords"][0]["frequency"] = 99
    category_title = payload["promotion_categories"][0]["title"]
    payload["promotion_categories"][0]["description"] = "изменённое описание"
    payload["promotion_categories"][0]["product_priorities"] = {"футболки": 42}

    service.apply_onboarding_payload(db_session, payload, dry_run=False)

    # Счётчики не выросли.
    assert _counts(db_session, config_id) == EXPECTED_COUNTS

    keyword = repo.get_keyword_by_key(db_session, config_id, changed_query)
    assert keyword is not None
    assert keyword.priority == 5
    assert keyword.frequency == 99

    category = repo.get_category_by_key(db_session, config_id, category_title)
    assert category is not None
    assert category.description == "изменённое описание"
    assert category.product_priorities == {"футболки": 42}


def test_empty_api_key_does_not_erase_existing_secret(db_session: Session) -> None:
    service = CrmBotSmmFormService()
    service.apply_onboarding_payload(db_session, _example(), dry_run=False)
    config = repo.list_configs(db_session)[0]

    vk_before = next(
        r for r in repo.list_resources_by_config(db_session, config.id) if r.resource_type == "vk"
    )
    assert vk_before.api_key_encrypted is not None
    encrypted_before = vk_before.api_key_encrypted
    masked_before = vk_before.api_key_masked

    # Повторный apply с пустым api_key у VK-ресурса.
    payload = _example()
    for resource in payload["resources"]:
        if resource["resource_type"] == "vk":
            resource["api_key"] = None

    service.apply_onboarding_payload(db_session, payload, dry_run=False)

    vk_after = next(
        r for r in repo.list_resources_by_config(db_session, config.id) if r.resource_type == "vk"
    )
    assert vk_after.id == vk_before.id
    assert vk_after.api_key_encrypted == encrypted_before  # секрет не затёрт
    assert vk_after.api_key_masked == masked_before


def test_new_api_key_replaces_secret(db_session: Session) -> None:
    service = CrmBotSmmFormService()
    service.apply_onboarding_payload(db_session, _example(), dry_run=False)
    config = repo.list_configs(db_session)[0]
    vk_before = next(
        r for r in repo.list_resources_by_config(db_session, config.id) if r.resource_type == "vk"
    )
    encrypted_before = vk_before.api_key_encrypted

    payload = _example()
    for resource in payload["resources"]:
        if resource["resource_type"] == "vk":
            resource["api_key"] = "new-real-token-xyz"

    service.apply_onboarding_payload(db_session, payload, dry_run=False)
    vk_after = next(
        r for r in repo.list_resources_by_config(db_session, config.id) if r.resource_type == "vk"
    )
    assert vk_after.api_key_encrypted != encrypted_before  # секрет обновлён
    assert vk_after.api_key_masked is not None


def test_dry_run_still_writes_nothing(db_session: Session) -> None:
    service = CrmBotSmmFormService()
    service.apply_onboarding_payload(db_session, _example(), dry_run=True)
    service.apply_onboarding_payload(db_session, _example(), dry_run=True)
    assert repo.list_configs(db_session) == []
