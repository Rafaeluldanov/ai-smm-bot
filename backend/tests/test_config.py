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


def test_env_helper_properties() -> None:
    local = Settings(app_env="local")
    assert local.is_local is True
    assert local.is_production is False

    prod = Settings(app_env="production")
    assert prod.is_production is True
    assert prod.is_local is False


def test_database_is_sqlite() -> None:
    assert Settings(database_url="sqlite://").database_is_sqlite is True
    assert Settings(database_url="postgresql+psycopg2://x").database_is_sqlite is False


def test_integration_configured_flags() -> None:
    empty = Settings(
        telegram_bot_token="",
        telegram_default_channel_id="",
        vk_access_token="",
        vk_default_group_id="",
        yandex_disk_token="",
        ai_api_key="",
    )
    assert empty.telegram_configured is False
    assert empty.vk_configured is False
    assert empty.yandex_disk_configured is False
    assert empty.ai_configured is False

    configured = Settings(
        telegram_bot_token="token",
        telegram_default_channel_id="@channel",
        vk_access_token="token",
        vk_default_group_id="123",
        yandex_disk_token="token",
        ai_provider="openai",
        ai_api_key="token",
    )
    assert configured.telegram_configured is True
    assert configured.vk_configured is True
    assert configured.yandex_disk_configured is True
    assert configured.ai_configured is True


def test_ai_stub_not_configured() -> None:
    assert Settings(ai_provider="stub", ai_api_key="k").ai_configured is False
