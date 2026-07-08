"""Тесты обратной совместимости CRM после добавления SaaS-слоя (offline)."""

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import project_repository
from app.services.crm_bot_smm_form_service import CrmBotSmmFormService

# Путь относительно этого файла — тест не зависит от рабочей директории pytest.
_EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "crm_bot_smm_onboarding_teeon.json"


def _payload() -> dict[str, Any]:
    return json.loads(_EXAMPLE.read_text(encoding="utf-8"))


def test_existing_crm_example_previews(db_session: Session) -> None:
    result = CrmBotSmmFormService().apply_onboarding_payload(db_session, _payload(), dry_run=True)
    assert result.dry_run is True
    assert result.project.slug == "teeon"


def test_existing_crm_example_applies(db_session: Session) -> None:
    result = CrmBotSmmFormService().apply_onboarding_payload(db_session, _payload(), dry_run=False)
    assert result.applied is True
    assert result.config_id is not None
    assert len(result.resources) >= 1


def test_crm_apply_is_idempotent_no_duplicates(db_session: Session) -> None:
    service = CrmBotSmmFormService()
    first = service.apply_onboarding_payload(db_session, _payload(), dry_run=False)
    second = service.apply_onboarding_payload(db_session, _payload(), dry_run=False)
    # Тот же config, без дублей ресурсов/категорий.
    assert first.config_id == second.config_id
    assert len(first.resources) == len(second.resources)
    assert len(first.categories) == len(second.categories)


def test_crm_created_project_has_no_account_id(db_session: Session) -> None:
    CrmBotSmmFormService().apply_onboarding_payload(db_session, _payload(), dry_run=False)
    project = project_repository.get_project_by_slug(db_session, "teeon")
    assert project is not None
    # account_id nullable — старая CRM-интеграция не привязывает проект к аккаунту.
    assert project.account_id is None


def test_old_crm_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/crm/bot-smm/form-schema").status_code == 200
