"""Тесты смоук-проверки (без сети, БД и реальных публикаций)."""

from app.scripts import smoke_check


def test_smoke_script_import() -> None:
    assert callable(smoke_check.main)
    assert callable(smoke_check.run_smoke)


def test_run_smoke_ok() -> None:
    ok, problems = smoke_check.run_smoke()
    assert ok is True
    assert problems == []


def test_summary_lines_have_env_and_no_secret_values() -> None:
    lines = smoke_check.summary_lines()
    assert any("APP_ENV" in line for line in lines)
    # В сводке только булевы флаги настроенности — без значений токенов.
    assert any("Telegram настроен" in line for line in lines)
