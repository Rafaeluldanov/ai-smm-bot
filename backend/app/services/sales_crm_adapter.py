"""Адаптер CRM для Sales Intelligence (v0.6.8) — ПОКА только интерфейс + mock.

Даёт стабильный интерфейс `create_lead` / `get_lead_status` для будущей интеграции с CRM,
но НЕ подключает реальную CRM и НЕ ходит в сеть. Это аналитический слой: он НИЧЕГО не
отправляет клиентам и не меняет CRM — mock-провайдер только эхо-регистрирует лид локально.
"""

from __future__ import annotations

from typing import Any

# Детерминированная последовательность статусов лида (mock-жизненный цикл).
_MOCK_STATUS_CYCLE: tuple[str, ...] = ("new", "contacted", "qualified", "converted")


class SalesCrmAdapter:
    """Mock-CRM: интерфейс create_lead/get_lead_status без сети и без реальной CRM."""

    def create_lead(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Зарегистрировать лид в mock-CRM. НЕ отправляет ничего наружу, без сети.

        Возвращает детерминированный «идентификатор» лида на основе входных данных —
        никакой реальной CRM/рассылки. Секреты в payload игнорируются.
        """
        project_id = int(payload.get("project_id") or 0)
        ref = str(payload.get("ref") or payload.get("post_id") or payload.get("campaign_id") or "0")
        lead_id = f"mock-{project_id}-{ref}"
        return {
            "provider": "mock",
            "lead_id": lead_id,
            "status": "new",
            "created": True,
            "note": "Mock CRM: лид зарегистрирован локально, наружу ничего не отправлено.",
        }

    def get_lead_status(self, lead_id: str) -> dict[str, Any]:
        """Статус лида в mock-CRM (детерминированный, без сети)."""
        # Детерминированный статус из хэша идентификатора (без внешних вызовов).
        idx = sum(ord(c) for c in str(lead_id)) % len(_MOCK_STATUS_CYCLE)
        return {"provider": "mock", "lead_id": str(lead_id), "status": _MOCK_STATUS_CYCLE[idx]}


def get_sales_crm_adapter() -> SalesCrmAdapter:
    """DI-фабрика mock-CRM адаптера."""
    return SalesCrmAdapter()
