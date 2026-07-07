"""Тесты CLI-помощников «БОТ СММ» (офлайн, без сети и БД)."""

import json
from pathlib import Path

import pytest

from app.scripts import (
    apply_crm_onboarding_payload,
    preview_crm_bot_smm_form,
    preview_crm_category_plan,
    validate_crm_onboarding_payload,
)

EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "crm_bot_smm_onboarding_teeon.json"
)


def test_cli_modules_have_main() -> None:
    assert callable(preview_crm_bot_smm_form.main)
    assert callable(validate_crm_onboarding_payload.main)
    assert callable(apply_crm_onboarding_payload.main)
    assert callable(preview_crm_category_plan.main)


def test_example_payload_is_present_and_secret_free() -> None:
    payload = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    # В примере нет реальных секретов: только null или плейсхолдер.
    for resource in payload["resources"]:
        api_key = resource.get("api_key")
        assert api_key in (None, "PASTE_IN_CRM_SECRET_FIELD")


def test_form_schema_cli_runs(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("sys.argv", ["preview_crm_bot_smm_form"])
    preview_crm_bot_smm_form.main()
    out = capsys.readouterr().out
    assert "БОТ СММ" in out
    assert "project" in out


def test_validate_cli_runs(capsys: pytest.CaptureFixture[str], monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(
        "sys.argv",
        ["validate_crm_onboarding_payload", "--payload-path", str(EXAMPLE_PATH)],
    )
    validate_crm_onboarding_payload.main()
    out = capsys.readouterr().out
    assert "Валидация: OK" in out
