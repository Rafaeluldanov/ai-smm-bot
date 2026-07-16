"""AIBusinessOSReportService — отчёт по E2E-прогону (v0.9.0).

Формирует «AI Business OS Test Report» из результата demo-сценария: PASS/FAIL по каждому
этапу пайплайна и общий score. Только чтение сохранённого прогона — ничего не выполняет.

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- только форматирование сохранённого результата; внешних действий/мутаций бизнеса нет;
- секретов нет; бесплатно (0 units); формирование отчёта → AuditLog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.logging import get_logger
from app.repositories import demo_testing_repository as repo
from app.services import audit_log_service as audit_actions
from app.services.ai_business_os_demo_service import AIBusinessOSDemoError
from app.services.ai_business_os_scenario_service import PIPELINE_STAGES

if TYPE_CHECKING:  # pragma: no cover
    from sqlalchemy.orm import Session

    from app.config import Settings
    from app.models.demo_scenario import DemoScenario
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)


class AIBusinessOSReportService:
    """Формирование AI Business OS Test Report из результата прогона."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit_svc = audit_service
        self._settings = settings

    def generate_report(
        self, db: Session, scenario_id: int, user_id: int | None = None
    ) -> dict[str, Any]:
        """Собрать отчёт по прогону: этапы PASS/FAIL + overall score."""
        scenario = self._require_scenario(db, scenario_id)
        result = dict(scenario.result_data or {})
        stage_results = {s.get("stage"): s for s in result.get("stages", []) if isinstance(s, dict)}
        stages = [
            {
                "stage": name,
                "result": "PASS" if stage_results.get(name, {}).get("status") == "pass" else "FAIL",
                "produced": bool(stage_results.get(name, {}).get("produced")),
                "detail": stage_results.get(name, {}).get("detail", "—"),
            }
            for name in PIPELINE_STAGES
        ]
        passed = sum(1 for s in stages if s["result"] == "PASS")
        overall_score = round(float(scenario.score or 0.0), 1)
        report = {
            "scenario_id": scenario.id,
            "scenario_type": scenario.scenario_type,
            "status": scenario.status,
            "title": f"AI Business OS Test Report — {scenario.scenario_type}",
            "stages": stages,
            "passed_stages": passed,
            "total_stages": len(stages),
            "overall_score": overall_score,
            "verdict": self._verdict(overall_score, passed, len(stages)),
        }
        workspace = repo.get_workspace(db, scenario.workspace_id)
        account_id = workspace.account_id if workspace is not None else None
        self._write_audit(
            db,
            audit_actions.ACTION_DEMO_REPORT_CREATED,
            account_id,
            user_id,
            scenario.id,
            {"overall_score": overall_score, "passed": passed},
        )
        return report

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _verdict(score: float, passed: int, total: int) -> str:
        if total and passed == total and score >= 90:
            return "MVP-READY: весь пайплайн проходит"
        if passed >= max(1, total - 1):
            return "PASS: пайплайн проходит с замечаниями"
        return "ATTENTION: есть падающие этапы — см. detail"

    def _require_scenario(self, db: Session, scenario_id: int) -> DemoScenario:
        scenario = repo.get_scenario(db, scenario_id)
        if scenario is None:
            raise AIBusinessOSDemoError("Demo-сценарий не найден")
        return scenario

    def _resolve_settings(self) -> Settings:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _write_audit(
        self,
        db: Session,
        action: str,
        account_id: int | None,
        user_id: int | None,
        entity_id: int | None,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit_svc is None:
            from app.services.audit_log_service import AuditLogService

            self._audit_svc = AuditLogService(self._resolve_settings())
        self._audit_svc.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=None,
            entity_type="demo_scenario",
            entity_id=entity_id,
            metadata=metadata,
        )


def get_ai_business_os_report_service() -> AIBusinessOSReportService:
    """DI-фабрика AI Business OS Report."""
    return AIBusinessOSReportService()
