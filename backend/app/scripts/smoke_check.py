"""Смоук-проверка приложения (без сети, БД и реальных публикаций).

Поднимает FastAPI-приложение in-process, дёргает ``/health`` и
``/health/readiness``, проверяет, что маршруты зарегистрированы и настройки
загружаются. Печатает сводку готовности (БЕЗ значений секретов) и завершает
процесс кодом 0 (ок) или 1 (есть проблемы).

Запуск:
  make smoke
  python -m app.scripts.smoke_check
"""

import sys

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_app


def run_smoke() -> tuple[bool, list[str]]:
    """Выполнить смоук-проверку. Возвращает (успех, список проблем)."""
    problems: list[str] = []
    app = create_app()

    if not app.routes:
        problems.append("Не зарегистрировано ни одного маршрута")

    with TestClient(app) as client:
        health = client.get("/health")
        if health.status_code != 200:
            problems.append(f"/health вернул {health.status_code}")
        readiness = client.get("/health/readiness")
        if readiness.status_code != 200:
            problems.append(f"/health/readiness вернул {readiness.status_code}")

    return (len(problems) == 0), problems


def summary_lines() -> list[str]:
    """Сводка окружения и готовности интеграций (без секретов)."""
    settings = get_settings()
    return [
        f"APP_ENV: {settings.app_env} (production={settings.is_production})",
        f"DB: {'sqlite' if settings.database_is_sqlite else 'postgresql'}",
        f"Telegram настроен: {settings.telegram_configured}",
        f"VK настроен: {settings.vk_configured}",
        f"Яндекс Диск настроен: {settings.yandex_disk_configured}",
        f"AI настроен: {settings.ai_configured}",
    ]


def main() -> None:
    """Точка входа смоук-проверки."""
    print("Смоук-проверка AI-SMM-бота (без сети и реальных публикаций)...")
    for line in summary_lines():
        print(f"  {line}")

    ok, problems = run_smoke()
    if ok:
        print("SMOKE OK — приложение поднимается, /health и /health/readiness отвечают 200")
        return

    print("SMOKE FAILED:")
    for problem in problems:
        print(f"  ! {problem}")
    sys.exit(1)


if __name__ == "__main__":
    main()
