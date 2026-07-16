"""AIBusinessContextService — анализ контекста компании пилота (v1.0.0).

Собирает бизнес-контекст (отрасль/продукты/услуги/продажи/цели/KPI/ограничения) и выдаёт SWOT:
сильные/слабые стороны, возможности, риски. ТОЛЬКО аналитика уже собранных данных — ничего не
выполняет и бизнес не меняет.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- работает только при pilot_mode=true; всё advisory/read-only; внешних действий/мутаций бизнеса нет;
- секретов нет; бесплатно (0 units).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import pilot_repository as repo
from app.services.ai_business_pilot_service import (
    AIBusinessPilotError,
    AIBusinessPilotService,
    PilotModeDisabledError,
)

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.pilot_workspace import PilotWorkspace

logger = get_logger(__name__)


class AIBusinessContextService:
    """SWOT-анализ контекста компании пилота (read-only)."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    def analyze_company_context(self, db: Session, workspace_id: int) -> dict[str, Any]:
        """Собрать контекст и выдать SWOT: strengths/weaknesses/opportunities/risks (аналитика)."""
        self._require_pilot_mode()
        workspace = self._require_workspace(db, workspace_id)
        profile = repo.get_profile(db, workspace.id)
        goals = repo.list_goals(db, workspace.id)
        kpis = repo.list_kpis(db, workspace.id)
        health = AIBusinessPilotService(settings=self._resolve_settings()).get_business_health(
            db, workspace_id
        )

        strengths: list[str] = []
        weaknesses: list[str] = []
        opportunities: list[str] = []
        risks: list[str] = []

        if profile is not None:
            products = list(profile.products or [])
            channels = list(profile.sales_channels or [])
            current = float(profile.current_revenue or 0.0)
            target = float(profile.target_revenue or 0.0)
            if len(products) >= 2:
                strengths.append(f"Диверсифицированный портфель ({len(products)} продуктов)")
            if len(channels) >= 2:
                strengths.append(f"Несколько каналов продаж ({len(channels)})")
            if current > 0:
                strengths.append(f"Устойчивая база выручки ({current:.0f})")
            if len(channels) <= 1:
                weaknesses.append("Мало каналов продаж — зависимость от одного канала")
            if target > current > 0:
                opportunities.append(
                    f"Рост выручки до цели {target:.0f} (~{target / current:.1f}x)"
                )
                weaknesses.append(f"Разрыв до цели по выручке: {target - current:.0f}")

        # Здоровье бизнеса (Performance/Operations/Forecasting, read-only).
        risks.extend(health.get("risks", []))
        opportunities.extend(health.get("opportunities", []))

        # Цели/KPI ниже целевого — риски/слабости.
        for goal in goals:
            if float(goal.current_value or 0.0) < float(goal.target_value or 0.0):
                risks.append(
                    f"Цель «{goal.title}» не достигнута "
                    f"({goal.current_value:.0f}/{goal.target_value:.0f} {goal.unit})".strip()
                )
        for kpi in kpis:
            if float(kpi.current_value or 0.0) < float(kpi.target_value or 0.0):
                weaknesses.append(
                    f"KPI «{kpi.name}» ниже цели ({kpi.current_value:.0f}/{kpi.target_value:.0f})"
                )

        return {
            "workspace_id": workspace.id,
            "strengths": _dedup(strengths)[:8],
            "weaknesses": _dedup(weaknesses)[:8],
            "opportunities": _dedup(opportunities)[:8],
            "risks": _dedup(risks)[:8],
            "has_data": bool(profile is not None or health.get("has_data")),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    def _require_pilot_mode(self) -> None:
        if not self._resolve_settings().pilot_mode_effective:
            raise PilotModeDisabledError("PILOT-режим выключен (pilot_mode=false)")

    def _require_workspace(self, db: Session, workspace_id: int) -> PilotWorkspace:
        workspace = repo.get_workspace(db, workspace_id)
        if workspace is None:
            raise AIBusinessPilotError("Pilot-воркспейс не найден")
        return workspace

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings


def _dedup(items: list[str]) -> list[str]:
    """Убрать дубликаты, сохранив порядок."""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def get_ai_business_context_service() -> AIBusinessContextService:
    """DI-фабрика AI Business Context."""
    return AIBusinessContextService()
