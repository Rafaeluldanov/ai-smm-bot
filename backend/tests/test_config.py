"""Тесты конфигурации приложения."""

from app.config import Settings, get_settings


def test_settings_load_defaults() -> None:
    settings = Settings()
    assert settings.app_name == "ai-smm-bot"
    assert settings.ai_provider == "stub"
    assert settings.database_url.startswith("postgresql")
    assert settings.redis_url.startswith("redis")


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
