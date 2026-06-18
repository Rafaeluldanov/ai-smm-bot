"""Конфигурация приложения на базе Pydantic Settings.

Все значения читаются из переменных окружения (или файла ``.env``).
Секреты и токены НИКОГДА не хранятся в коде — только в окружении.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Настройки приложения.

    Имена полей сопоставляются с переменными окружения без учёта регистра,
    поэтому поле ``app_name`` читается из переменной ``APP_NAME`` и т. д.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Приложение ---
    app_name: str = "ai-smm-bot"
    app_env: str = "local"

    # --- Хранилища ---
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/ai_smm_bot"
    redis_url: str = "redis://localhost:6379/0"

    # --- Внешние интеграции (заполняются на соответствующих этапах) ---
    yandex_disk_token: str | None = None
    yandex_disk_base_url: str = "https://cloud-api.yandex.net/v1/disk"
    yandex_disk_root_path: str = "/SMM_BOT"
    # Токены автопостинга (Этап 7). Пустые значения трактуются как «не задано»:
    # реальная публикация выдаст понятную ошибку, но API и тесты работают без них.
    telegram_bot_token: str = ""
    telegram_default_channel_id: str | None = None
    vk_access_token: str = ""
    vk_default_group_id: str | None = None
    instagram_access_token: str = ""

    # --- AI-провайдер ---
    ai_provider: str = "stub"
    ai_api_key: str = ""


@lru_cache
def get_settings() -> Settings:
    """Вернуть кешированный экземпляр настроек."""
    return Settings()
