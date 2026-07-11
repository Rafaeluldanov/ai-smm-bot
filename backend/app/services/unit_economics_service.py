"""Юнит-экономика Botfleet: расчёт стоимости действий в внутренних units.

Единый источник цен. Реальные тарифы провайдера (USD за 1M токенов), наценка и
курс USD→unit задаются в конфиге/``.env`` (см. ``Settings``), а НЕ хардкодятся в
логике — так цену можно менять без правок кода.

Формула генерации:
    себестоимость_usd = in_tokens/1_000_000 * in_price + out_tokens/1_000_000 * out_price
    цена_клиента_usd  = себестоимость_usd * markup_multiplier
    units             = max(min_units, ceil(цена_клиента_usd * usd_to_unit_rate))

Сервис только СЧИТАЕТ стоимость. Списание/идемпотентность/защита от ухода в минус —
в ``BillingService.reserve_or_debit`` (единая точка ledger + usage_events).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.config import Settings, get_settings

# Типы платных событий (пишутся в usage_events.event_type). Совпадают с
# терминологией биллинга; строковый столбец не ограничен enum.
USAGE_POST_GENERATION = "post_generation"
USAGE_POST_PUBLICATION = "post_publication"
USAGE_POST_ANALYTICS = "post_analytics"
USAGE_SCHEDULE_GENERATION = "schedule_generation"
USAGE_MEDIA_PROCESSING = "media_processing"

USAGE_TYPES: tuple[str, ...] = (
    USAGE_POST_GENERATION,
    USAGE_POST_PUBLICATION,
    USAGE_POST_ANALYTICS,
    USAGE_SCHEDULE_GENERATION,
    USAGE_MEDIA_PROCESSING,
)

# Базовая стоимость публикации (units) без учёта генерации текста.
PUBLICATION_TEXT_ONLY_UNITS = 2
PUBLICATION_WITH_MEDIA_UNITS = 3
PUBLICATION_INSTAGRAM_UNITS = 4  # Instagram публикует по публичному image_url

# Глубины отчёта аналитики (фиксированные цены за пост берутся из конфига).
ANALYTICS_DEPTHS: tuple[str, ...] = ("light", "standard", "deep")
ANALYTICS_DEPTH_TITLES: dict[str, str] = {
    "light": "Лёгкая",
    "standard": "Стандарт",
    "deep": "Глубокая",
}
# Ручной ввод метрик и dry-run/preview — бесплатны.
ANALYTICS_MANUAL_METRICS_UNITS = 0
ANALYTICS_PREVIEW_UNITS = 0

# --- Импорт метрик (v0.4.1) ---
# Реальный API-импорт платный по глубине (фиксированная цена за прогон проекта);
# demo/manual/estimated/internal — бесплатны. Пересчёт обучения — фикс. цена.
METRICS_IMPORT_SOURCES: tuple[str, ...] = ("internal", "manual", "estimated", "api", "demo")
METRICS_IMPORT_DEPTH_UNITS: dict[str, int] = {"light": 5, "standard": 10, "deep": 20}
# Источники, за которые НЕ списываем units (demo может стать платным через конфиг).
METRICS_FREE_SOURCES: tuple[str, ...] = ("manual", "estimated", "internal", "demo")
LEARNING_REBUILD_UNITS = 5

# Оценка токенов «по умолчанию» для генерации короткого поста (input/output).
DEFAULT_POST_INPUT_TOKENS = 2000
DEFAULT_POST_OUTPUT_TOKENS = 500
# Пересборка расписания: лёгкая генерация плана (меньше токенов, чем пост).
DEFAULT_SCHEDULE_INPUT_TOKENS = 800
DEFAULT_SCHEDULE_OUTPUT_TOKENS = 300


@dataclass(frozen=True)
class UnitCostBreakdown:
    """Разбор стоимости действия: себестоимость, наценка и итог в units."""

    usage_type: str
    provider_cost_usd: float
    client_price_usd: float
    units: int
    markup_percent: int
    details: str = ""


class UnitEconomicsService:
    """Считает стоимость действий бота в units по конфигурируемым ценам."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # --- Базовая формула генерации ---------------------------------------- #

    def _generation_breakdown(
        self,
        input_tokens: int,
        output_tokens: int,
        usage_type: str,
        min_units: int,
    ) -> UnitCostBreakdown:
        s = self._settings
        in_tokens = max(0, int(input_tokens))
        out_tokens = max(0, int(output_tokens))
        provider_usd = (
            in_tokens / 1_000_000 * s.ai_input_usd_per_1m
            + out_tokens / 1_000_000 * s.ai_output_usd_per_1m
        )
        client_usd = provider_usd * s.billing_markup_multiplier
        raw_units = math.ceil(client_usd * s.billing_usd_to_unit_rate)
        units = max(int(min_units), raw_units)
        markup_percent = max(0, round((s.billing_markup_multiplier - 1.0) * 100))
        return UnitCostBreakdown(
            usage_type=usage_type,
            provider_cost_usd=round(provider_usd, 6),
            client_price_usd=round(client_usd, 6),
            units=units,
            markup_percent=markup_percent,
            details=f"in={in_tokens}, out={out_tokens}, модель={s.ai_pricing_model}",
        )

    def estimate_generation_breakdown(
        self,
        input_tokens: int,
        output_tokens: int,
        action_type: str = USAGE_POST_GENERATION,
    ) -> UnitCostBreakdown:
        """Полный разбор стоимости генерации (себестоимость/наценка/units)."""
        min_units = self._settings.billing_min_post_units
        return self._generation_breakdown(input_tokens, output_tokens, action_type, min_units)

    def estimate_generation_units(
        self,
        input_tokens: int,
        output_tokens: int,
        action_type: str = USAGE_POST_GENERATION,
    ) -> int:
        """units за генерацию текста по токенам (с наценкой и min-порогом)."""
        return self.estimate_generation_breakdown(input_tokens, output_tokens, action_type).units

    # --- Публикация -------------------------------------------------------- #

    def estimate_publication_units(
        self,
        platform: str,
        media_count: int = 0,
        has_ai_generation: bool = False,
    ) -> int:
        """units за публикацию: базовая цена площадки + (опц.) генерация текста."""
        platform_slug = (platform or "").strip().lower()
        if platform_slug == "instagram":
            base = PUBLICATION_INSTAGRAM_UNITS
        elif int(media_count or 0) > 0:
            base = PUBLICATION_WITH_MEDIA_UNITS
        else:
            base = PUBLICATION_TEXT_ONLY_UNITS
        total = base
        if has_ai_generation:
            total += self.estimate_generation_units(
                DEFAULT_POST_INPUT_TOKENS, DEFAULT_POST_OUTPUT_TOKENS, USAGE_POST_GENERATION
            )
        return total

    # --- Аналитика --------------------------------------------------------- #

    def analytics_depth_price(self, depth: str) -> int:
        """Фиксированная цена аналитики за один пост по глубине (units)."""
        prices = {
            "light": self._settings.analytics_light_units,
            "standard": self._settings.analytics_standard_units,
            "deep": self._settings.analytics_deep_units,
        }
        depth_norm = (depth or "").strip().lower()
        if depth_norm not in prices:
            raise ValueError(
                f"Неизвестная глубина аналитики: {depth!r} (ожидается light|standard|deep)"
            )
        return prices[depth_norm]

    def estimate_analytics_units(self, depth: str = "light", post_count: int = 1) -> int:
        """units за аналитику: фиксированная цена глубины × число постов (min 1).

        Для MVP итог не ниже фиксированной цены глубины. Неизвестная глубина →
        ``ValueError``.
        """
        per_post = self.analytics_depth_price(depth)
        n = max(1, int(post_count or 1))
        return per_post * n

    def analytics_price_table(self) -> list[dict[str, object]]:
        """Цены аналитики по глубине (units за пост) — для UI/подсказок."""
        return [
            {
                "depth": d,
                "title": ANALYTICS_DEPTH_TITLES[d],
                "units": self.analytics_depth_price(d),
            }
            for d in ANALYTICS_DEPTHS
        ]

    # --- Импорт метрик и пересчёт обучения (v0.4.1) ----------------------- #

    def estimate_metrics_import_units(
        self, source: str, depth: str = "standard", publication_count: int = 1
    ) -> int:
        """units за импорт метрик: бесплатно для demo/manual/…; для api — цена по глубине.

        Цена api-импорта фиксирована за прогон проекта (не за пост). demo-импорт может
        стать платным при ``metrics_demo_import_paid=true`` (по умолчанию бесплатный).
        """
        src = (source or "demo").strip().lower()
        if src == "demo" and getattr(self._settings, "metrics_demo_import_paid", False):
            return METRICS_IMPORT_DEPTH_UNITS.get(depth, METRICS_IMPORT_DEPTH_UNITS["standard"])
        if src in METRICS_FREE_SOURCES:
            return 0
        if src == "api":
            return METRICS_IMPORT_DEPTH_UNITS.get(depth, METRICS_IMPORT_DEPTH_UNITS["standard"])
        return 0

    def estimate_learning_rebuild_units(self, depth: str = "standard") -> int:
        """units за явный пересчёт профиля обучения (dry-run — бесплатно на уровне сервиса)."""
        return LEARNING_REBUILD_UNITS

    def metrics_import_price_table(self) -> list[dict[str, object]]:
        """Таблица цен импорта метрик по глубине (для UI/подсказок)."""
        return [
            {
                "depth": d,
                "title": ANALYTICS_DEPTH_TITLES[d],
                "api_units": METRICS_IMPORT_DEPTH_UNITS[d],
            }
            for d in ANALYTICS_DEPTHS
        ]

    # --- Пересборка расписания -------------------------------------------- #

    def estimate_schedule_generation_units(self, plan_count: int = 1) -> int:
        """units за пересборку расписания (лёгкая генерация плана публикаций)."""
        per_plan = self.estimate_generation_units(
            DEFAULT_SCHEDULE_INPUT_TOKENS, DEFAULT_SCHEDULE_OUTPUT_TOKENS, USAGE_SCHEDULE_GENERATION
        )
        return per_plan * max(1, int(plan_count or 1))

    # --- Витрина цен (для UI «Тарифы») ------------------------------------ #

    def build_pricing_table(self) -> list[dict[str, object]]:
        """Понятная таблица цен для UI: действие → units + пояснение."""
        gen = self.estimate_generation_breakdown(
            DEFAULT_POST_INPUT_TOKENS, DEFAULT_POST_OUTPUT_TOKENS
        )
        return [
            {
                "key": "post_text_only",
                "title": "Пост text-only",
                "units": self.estimate_publication_units("telegram", 0, has_ai_generation=False),
                "note": "Публикация текста в Telegram/VK без медиа.",
            },
            {
                "key": "post_with_media",
                "title": "Пост с медиа",
                "units": self.estimate_publication_units("telegram", 1, has_ai_generation=False),
                "note": "Публикация с фото/медиа-группой.",
            },
            {
                "key": "post_instagram",
                "title": "Пост Instagram (image_url)",
                "units": self.estimate_publication_units("instagram", 1, has_ai_generation=False),
                "note": "Требует публичный HTTPS image_url.",
            },
            {
                "key": "post_generation",
                "title": "Генерация текста",
                "units": gen.units,
                "note": (
                    f"Модель {self._settings.ai_pricing_model}, наценка "
                    f"×{self._settings.billing_markup_multiplier:g}; минимум "
                    f"{self._settings.billing_min_post_units} units."
                ),
            },
            {
                "key": "analytics_light",
                "title": "Light analytics — за пост",
                "units": self.analytics_depth_price("light"),
                "note": "Базовые метрики и структура поста.",
            },
            {
                "key": "analytics_standard",
                "title": "Standard analytics — за пост",
                "units": self.analytics_depth_price("standard"),
                "note": "Метрики + оценка вовлечения и качества.",
            },
            {
                "key": "analytics_deep",
                "title": "Deep analytics — за пост",
                "units": self.analytics_depth_price("deep"),
                "note": "Рекомендации, лучшее время, теги, следующий пост.",
            },
            {
                "key": "analytics_manual",
                "title": "Ручной ввод метрик",
                "units": ANALYTICS_MANUAL_METRICS_UNITS,
                "note": "Сохранение метрик вручную — бесплатно.",
            },
            {
                "key": "schedule_generation",
                "title": "Пересборка расписания",
                "units": self.estimate_schedule_generation_units(1),
                "note": "Перегенерация плана публикаций.",
            },
        ]

    def pricing_config(self) -> dict[str, object]:
        """Текущие параметры юнит-экономики (для витрины/диагностики; без секретов)."""
        s = self._settings
        return {
            "ai_pricing_model": s.ai_pricing_model,
            "ai_input_usd_per_1m": s.ai_input_usd_per_1m,
            "ai_output_usd_per_1m": s.ai_output_usd_per_1m,
            "markup_multiplier": s.billing_markup_multiplier,
            "usd_to_unit_rate": s.billing_usd_to_unit_rate,
            "min_post_units": s.billing_min_post_units,
            "min_analytics_units": s.billing_min_analytics_units,
        }


def get_unit_economics_service() -> UnitEconomicsService:
    """DI-фабрика сервиса юнит-экономики (использует кешированные настройки)."""
    return UnitEconomicsService()
