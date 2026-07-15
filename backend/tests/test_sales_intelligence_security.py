"""Статические + поведенческие проверки безопасности AI Sales Intelligence (v0.6.8).

Инварианты:
- НЕ отправляет сообщения клиентам, НЕ меняет CRM, НЕ продаёт, НЕ включает live;
- НЕ ходит во внешние рекламные/CRM API (CRM-адаптер mock, без сети);
- операции бесплатны (0 units); секретов нет; reset не удаляет события лидов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService

_MODULES = (
    "app.services.ai_sales_intelligence_service",
    "app.services.sales_crm_adapter",
    "app.repositories.ai_sales_intelligence_repository",
    "app.api.sales_intelligence",
    "app.scripts.sales_intelligence_analyze",
    "app.scripts.sales_intelligence_report",
    "app.scripts.sales_intelligence_lead",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_publish_no_live_no_send() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_once_if_allowed" not in src, module
        assert "publish_post(" not in src, module
        assert "live_publishing_enabled =" not in src.lower(), module
        # Аналитический слой не рассылает и не активирует автопилот.
        assert "send_message" not in src.lower(), module


def test_no_external_ads_or_crm_calls() -> None:
    for module in _MODULES:
        src = _source(module).lower()
        for token in ("httpx", "requests.get", "requests.post", "aiohttp", "ads.api", "crm.api"):
            assert token not in src, f"{module}: {token}"


def test_crm_adapter_is_mock() -> None:
    from app.services.sales_crm_adapter import SalesCrmAdapter

    adapter = SalesCrmAdapter()
    lead = adapter.create_lead({"project_id": 1, "ref": "x"})
    # Mock: локально, без сети, ничего наружу.
    assert lead["provider"] == "mock"
    assert lead["created"] is True
    status = adapter.get_lead_status(lead["lead_id"])
    assert status["provider"] == "mock"


def test_config_has_no_live_flag_enabled_default() -> None:
    fields = set(Settings.model_fields)
    assert not any("sales_intelligence" in f and "live" in f for f in fields)
    s = Settings(media_proxy_public_base_url="https://m.example.com")
    assert s.sales_intelligence_enabled is True


def test_sales_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_SALES_INTELLIGENCE_ANALYSIS,
        billing_service.USAGE_SALES_INTELLIGENCE_REPORT,
        billing_service.USAGE_SALES_INTELLIGENCE_LEAD,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_have_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="ssec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="ssec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="ssec"))
    project.account_id = account.id
    db_session.commit()
    svc = AISalesIntelligenceService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )
    # Пытаемся протащить секрет в метаданные события.
    out = svc.record_lead_event(
        db_session,
        project.id,
        event_type="lead_created",
        metadata={"api_key": "123456:SECRETxyz", "note": "ok"},
    )
    blob = str(svc.get_intelligence(db_session, project.id)) + str(
        svc.get_revenue(db_session, project.id)
    )
    assert "123456:SECRETxyz" not in blob
    assert "api_key" not in blob.lower()
    # Санитизация реально сработала на СТРОКЕ в БД (а не только в представлении).
    from app.models.ai_lead_event import AILeadEvent

    row = db_session.get(AILeadEvent, out["id"])
    assert "123456:SECRETxyz" not in str(row.event_metadata)
