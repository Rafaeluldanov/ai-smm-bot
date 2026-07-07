"""CLI: показать JSON-схему формы «БОТ СММ» для CRM (без БД и сети).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_crm_bot_smm_form
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_crm_bot_smm_form --json
"""

import argparse

from app.services.crm_bot_smm_form_service import CrmBotSmmFormService


def main() -> None:
    """Точка входа CLI превью схемы формы."""
    parser = argparse.ArgumentParser(description="Схема формы «БОТ СММ» для CRM")
    parser.add_argument("--json", action="store_true", help="Вывести схему в JSON")
    args = parser.parse_args()

    schema = CrmBotSmmFormService().build_form_schema()
    if args.json:
        print(schema.model_dump_json(indent=2, ensure_ascii=False))
        return

    print(f"Форма «{schema.title}» (версия {schema.version})")
    print(f"Отключённые режимы: {', '.join(schema.disabled_modes) or '—'}\n")
    for section in schema.sections:
        marker = " [список]" if section.repeatable else ""
        print(f"=== {section.title} ({section.key}){marker} ===")
        if section.description:
            print(f"    {section.description}")
        for field in section.fields:
            flags = []
            if field.required:
                flags.append("required")
            if field.required_if:
                flags.append(f"required_if {field.required_if}")
            suffix = f" ({', '.join(flags)})" if flags else ""
            options = f" [{', '.join(field.options)}]" if field.options else ""
            print(f"    • {field.name}: {field.type}{options}{suffix} — {field.label}")
        print()

    print("Заметки по безопасности:")
    for note in schema.safety_notes:
        print(f"  ! {note}")


if __name__ == "__main__":
    main()
