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
    # Публичная папка Яндекс Диска (альтернатива OAuth-токену). Если
    # yandex_disk_public_mode=true — sync-media работает по публичной ссылке.
    yandex_disk_public_smm_url: str = ""
    yandex_disk_public_mode: bool = False
    yandex_disk_public_root_folder: str = "SMM"
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

    # --- Улучшение медиа (Media Enhancement) ---
    # Локальная обработка изображений (brightness/contrast, resize, конвертация).
    # Оригиналы НЕ изменяются — создаются производные копии (MediaAssetVariant).
    media_enhancement_enabled: bool = False
    media_enhancement_storage_dir: str = "backend/data/enhanced_media"
    media_enhancement_max_image_mb: int = 25
    media_enhancement_default_profile: str = "social_safe"
    media_enhancement_output_format: str = "jpg"
    media_enhancement_jpeg_quality: int = 92

    # --- Производные свойства (готовность к боевому запуску) ---

    @property
    def is_production(self) -> bool:
        """Запущено ли приложение в production-окружении."""
        return self.app_env.strip().lower() in {"production", "prod"}

    @property
    def is_local(self) -> bool:
        """Локальное/тестовое окружение."""
        return self.app_env.strip().lower() in {"local", "dev", "development", "test"}

    @property
    def database_is_sqlite(self) -> bool:
        """Использует ли БД SQLite (для prod ожидается PostgreSQL)."""
        return self.database_url.strip().lower().startswith("sqlite")

    @property
    def telegram_configured(self) -> bool:
        """Готов ли Telegram к публикации (есть токен и канал по умолчанию)."""
        return bool(self.telegram_bot_token and self.telegram_default_channel_id)

    @property
    def vk_configured(self) -> bool:
        """Готов ли VK к публикации (есть токен и группа по умолчанию)."""
        return bool(self.vk_access_token and self.vk_default_group_id)

    @property
    def yandex_disk_configured(self) -> bool:
        """Задан ли токен Яндекс Диска (приватный OAuth-режим)."""
        return bool(self.yandex_disk_token)

    @property
    def yandex_disk_public_configured(self) -> bool:
        """Задана ли публичная ссылка на папку SMM (публичный режим)."""
        return bool(self.yandex_disk_public_smm_url)

    @property
    def ai_configured(self) -> bool:
        """Подключён ли реальный AI-провайдер (не заглушка и есть ключ)."""
        return self.ai_provider.strip().lower() != "stub" and bool(self.ai_api_key)

    @property
    def media_enhancement_configured(self) -> bool:
        """Готово ли локальное улучшение медиа (задана папка для копий).

        Внешние ключи не нужны: обработка идёт локально через Pillow.
        """
        return bool(self.media_enhancement_storage_dir.strip())


@lru_cache
def get_settings() -> Settings:
    """Вернуть кешированный экземпляр настроек."""
    return Settings()
