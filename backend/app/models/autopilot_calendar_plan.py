"""Модель клиентского календаря автопостинга — v0.5.8.

Calendar Assistant: клиент выбирает цель и частоту — Botfleet строит календарь автопостинга и
сохраняет его как ``AutopilotCalendarPlan`` (понятный клиентский слой поверх ``CrmPublishingPlan``).
Применение календаря создаёт/обновляет ``CrmPublishingPlan``, но НЕ публикует и НЕ включает
live-флаги.

БЕЗОПАСНОСТЬ:
- секретов/сырых токенов не хранит; только простые правила календаря и оценки;
- применение календаря не запускает реальную публикацию.
"""

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, JSONType, TimestampMixin

# --- Термины (v0.5.8, Часть 1). --- #
AUTOPILOT_CALENDAR_STATUSES: tuple[str, ...] = (
    "draft",
    "preview",
    "active",
    "paused",
    "archived",
    "failed",
)
AUTOPILOT_CALENDAR_PRESETS: tuple[str, ...] = (
    "daily",
    "weekdays",
    "three_per_week",
    "two_per_week",
    "custom",
    "launch_campaign",
    "soft_presence",
    "intensive_month",
)
AUTOPILOT_CALENDAR_GOALS: tuple[str, ...] = (
    "sales",
    "leads",
    "reach",
    "trust",
    "expertise",
    "mixed",
)
AUTOPILOT_CALENDAR_TIME_STRATEGIES: tuple[str, ...] = (
    "fixed_time",
    "best_known_time",
    "platform_default",
    "spread_evenly",
    "client_custom",
)
AUTOPILOT_CALENDAR_RISKS: tuple[str, ...] = (
    "too_many_posts_for_media",
    "too_low_balance",
    "no_platforms",
    "no_media",
    "no_learning_data",
    "weekend_posts",
    "live_disabled",
    "timezone_missing",
)


class AutopilotCalendarPlan(Base, TimestampMixin):
    """Клиентский календарь автопостинга проекта (слой поверх CrmPublishingPlan)."""

    __tablename__ = "autopilot_calendar_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        ForeignKey("accounts.id", ondelete="CASCADE"), index=True, default=None
    )
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=False
    )
    autopilot_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_autopilot_profiles.id", ondelete="SET NULL"), index=True, default=None
    )

    status: Mapped[str] = mapped_column(String(16), index=True, default="draft", nullable=False)
    preset: Mapped[str] = mapped_column(
        String(24), index=True, default="three_per_week", nullable=False
    )
    goal: Mapped[str] = mapped_column(String(16), index=True, default="mixed", nullable=False)

    platforms: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    weekdays: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    publish_times: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)
    posts_per_day: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow", nullable=False)
    start_date: Mapped[str | None] = mapped_column(String(32), default=None)
    end_date: Mapped[str | None] = mapped_column(String(32), default=None)
    time_strategy: Mapped[str] = mapped_column(
        String(24), default="platform_default", nullable=False
    )

    generated_rules: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    source_signals: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)
    risk_flags: Mapped[list[Any]] = mapped_column(JSONType, default=list, nullable=False)

    estimated_posts_per_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_units_per_month: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_media_needed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    linked_publishing_plan_ids: Mapped[list[Any]] = mapped_column(
        JSONType, default=list, nullable=False
    )
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    updated_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
    plan_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict, nullable=False)


# Определения пресетов (weekdays 0=Пн..6=Вс). Используются сервисом Calendar Assistant.
CALENDAR_PRESET_DEFS: dict[str, dict[str, Any]] = {
    "daily": {
        "label": "Каждый день",
        "description": "Публикуем каждый день — максимальное присутствие.",
        "weekdays": [0, 1, 2, 3, 4, 5, 6],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "охваты, присутствие",
    },
    "weekdays": {
        "label": "По будням",
        "description": "Публикуем в рабочие дни (Пн–Пт).",
        "weekdays": [0, 1, 2, 3, 4],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "B2B, экспертность",
    },
    "three_per_week": {
        "label": "3 раза в неделю",
        "description": "Пн/Ср/Пт — сбалансированный ритм.",
        "weekdays": [0, 2, 4],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "старт, устойчивый ритм",
    },
    "two_per_week": {
        "label": "2 раза в неделю",
        "description": "Вт/Пт — лёгкое присутствие.",
        "weekdays": [1, 4],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "мало медиа, старт",
    },
    "soft_presence": {
        "label": "Мягкое присутствие",
        "description": "Вт/Пт в 11:00 — ненавязчиво.",
        "weekdays": [1, 4],
        "publish_times": ["11:00"],
        "posts_per_day": 1,
        "best_for": "доверие, спокойный тон",
    },
    "launch_campaign": {
        "label": "Запуск кампании",
        "description": "Будни, интенсивно — для запуска продукта/акции.",
        "weekdays": [0, 1, 2, 3, 4],
        "publish_times": ["10:00", "16:00"],
        "posts_per_day": 2,
        "best_for": "продажи, запуск",
    },
    "intensive_month": {
        "label": "Интенсивный месяц",
        "description": "Пн–Сб — максимальная активность на месяц.",
        "weekdays": [0, 1, 2, 3, 4, 5],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "быстрый рост охватов",
    },
    "custom": {
        "label": "Свой график",
        "description": "Выберите дни и время сами.",
        "weekdays": [0, 2, 4],
        "publish_times": ["10:00"],
        "posts_per_day": 1,
        "best_for": "точная настройка",
    },
}
