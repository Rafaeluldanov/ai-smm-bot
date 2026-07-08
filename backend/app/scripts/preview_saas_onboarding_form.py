"""CLI: показать JSON-схему SaaS-формы онбординга (без сети и БД).

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.preview_saas_onboarding_form
"""

from app.services.saas_onboarding_service import SaasOnboardingService


def main() -> None:
    """Точка входа CLI схемы SaaS-формы."""
    schema = SaasOnboardingService().build_form_schema()
    print(f"{schema.title} (версия {schema.version})")
    for section in schema.sections:
        flag = " [repeatable]" if section.repeatable else ""
        print(f"\n=== {section.key}: {section.title}{flag} ===")
        for field in section.fields:
            mark = " *" if field.required else ""
            print(f"  - {field.name} ({field.type}){mark} — {field.label}")
    print("\nПравила безопасности:")
    for note in schema.safety_notes:
        print(f"  ! {note}")


if __name__ == "__main__":
    main()
