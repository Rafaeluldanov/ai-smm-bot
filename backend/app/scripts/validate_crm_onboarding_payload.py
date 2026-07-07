"""CLI: проверить онбординг-пейлоад формы «БОТ СММ» (без БД и сети).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.validate_crm_onboarding_payload \
      --payload-path backend/examples/crm_bot_smm_onboarding_teeon.json
"""

import argparse
import json
from pathlib import Path

from app.services.crm_bot_smm_form_service import CrmBotSmmFormService


def main() -> None:
    """Точка входа CLI валидации онбординг-пейлоада."""
    parser = argparse.ArgumentParser(description="Валидация онбординг-пейлоада «БОТ СММ»")
    parser.add_argument("--payload-path", required=True, help="Путь к JSON-файлу пейлоада")
    args = parser.parse_args()

    payload = json.loads(Path(args.payload_path).read_text(encoding="utf-8"))
    result = CrmBotSmmFormService().validate_onboarding_payload(payload)

    print(f"Валидация: {'OK' if result.valid else 'ОШИБКИ'}")
    if result.errors:
        print("Ошибки:")
        for error in result.errors:
            print(f"  ! {error}")
    if result.warnings:
        print("Предупреждения:")
        for warning in result.warnings:
            print(f"  ~ {warning}")
    if result.valid and not result.warnings:
        print("Пейлоад валиден, замечаний нет.")


if __name__ == "__main__":
    main()
