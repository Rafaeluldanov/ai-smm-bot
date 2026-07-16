"""Тесты безопасности AI Business Pilot Release — v1.0.0 (Part 16).

Инварианты: pilot-release advisory — НЕ выполняет рекомендаций, НЕ меняет бизнес/CRM/финансы, НЕ
публикует, НЕ шлёт сообщений, НЕ создаёт платежей/списаний. Проверяем: auth (401); pilot_mode
disabled (403); tenant isolation (403/404); онбординг требует account_id; сервисы не создают
запрещённых сущностей; секретов нет; billing 0.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.models.billing import UsageEvent
from app.models.business_workflow import BusinessWorkflow
from app.models.crm_bot_smm import CrmSmmResource
from app.models.payment import PaymentInvoice
from app.models.post_publication import PostPublication
from app.repositories import account_repository, user_repository
from app.services import billing_service
from app.services.ai_ceo_daily_brief_service import AICEODailyBriefService
from app.services.ai_pilot_feedback_service import AIPilotFeedbackService
from app.services.ai_pilot_intelligence_report_service import AIPilotIntelligenceReportService
from app.services.ai_pilot_onboarding_service import AIPilotOnboardingService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access_key", "refresh")
_FORBIDDEN_MODELS = (
    PostPublication,  # публикации/сообщения
    CrmSmmResource,  # CRM
    BusinessWorkflow,  # workflow-исполнение
    PaymentInvoice,  # платежи
    UsageEvent,  # списания billing
)


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _pilot(db: Session, slug: str) -> tuple[int, int]:
    aid, uid = _account(db, slug)
    pilot = AIPilotOnboardingService(settings=_SETTINGS).create_company_pilot(
        db, aid, company_name="TEEON Pilot", user_id=uid
    )
    return pilot["workspace"]["id"], uid


def _forbidden_counts(db: Session) -> dict[str, int]:
    return {m.__name__: db.query(m).count() for m in _FORBIDDEN_MODELS}


# --------------------------------------------------------------------------- #
# Billing / free                                                              #
# --------------------------------------------------------------------------- #


def test_billing_pilot_release_is_free() -> None:
    costs = billing_service.ACTION_COSTS
    assert costs[billing_service.USAGE_PILOT_INTELLIGENCE] == 0
    assert costs[billing_service.USAGE_DAILY_BRIEF] == 0
    assert costs[billing_service.USAGE_FEEDBACK] == 0


# --------------------------------------------------------------------------- #
# Auth / gate                                                                 #
# --------------------------------------------------------------------------- #


def test_auth_required(client: TestClient) -> None:
    assert client.post("/pilot/onboarding", json={}).status_code == 401
    assert client.get("/pilot/1/intelligence").status_code == 401
    assert client.get("/pilot/1/daily-brief").status_code == 401
    assert client.post("/pilot/1/feedback", json={}).status_code == 401


def test_onboarding_requires_account_id(client: TestClient, db_session: Session) -> None:
    _aid, uid = _account(db_session, "prsec1")
    resp = client.post("/pilot/onboarding", headers=_h(uid), json={})
    assert resp.status_code == 400


def test_onboarding_non_numeric_account_id_400(client: TestClient, db_session: Session) -> None:
    """Нечисловой account_id → 400 (а не необработанный 500)."""
    _aid, uid = _account(db_session, "prsec1b")
    resp = client.post(
        "/pilot/onboarding", headers=_h(uid), json={"account_id": "abc", "company_name": "X"}
    )
    assert resp.status_code == 400


def test_onboarding_bad_kpi_number_400(client: TestClient, db_session: Session) -> None:
    """Нечисловое значение KPI → 400 и пилот не создаётся частично."""
    aid, uid = _account(db_session, "prsec1c")
    resp = client.post(
        "/pilot/onboarding",
        headers=_h(uid),
        json={"account_id": aid, "kpis": [{"name": "K", "current_value": "oops"}]},
    )
    assert resp.status_code == 400


def test_pilot_mode_disabled_403(client: TestClient, db_session: Session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from app.config import get_settings

    aid, uid = _account(db_session, "prsec2")
    settings = get_settings()
    monkeypatch.setattr(settings, "pilot_mode", False)
    resp = client.post(
        "/pilot/onboarding", headers=_h(uid), json={"account_id": aid, "company_name": "X"}
    )
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# Tenant isolation                                                            #
# --------------------------------------------------------------------------- #


def test_tenant_isolation_cross_account(client: TestClient, db_session: Session) -> None:
    """Пользователь аккаунта B не читает/не пишет пилот аккаунта A."""
    wid, _uid_a = _pilot(db_session, "prsec3a")
    _aid_b, uid_b = _account(db_session, "prsec3b")
    assert client.get(f"/pilot/{wid}/intelligence", headers=_h(uid_b)).status_code in (403, 404)
    assert client.get(f"/pilot/{wid}/daily-brief", headers=_h(uid_b)).status_code in (403, 404)
    assert client.post(
        f"/pilot/{wid}/goals", headers=_h(uid_b), json={"title": "X"}
    ).status_code in (
        403,
        404,
    )
    assert client.post(
        f"/pilot/{wid}/feedback", headers=_h(uid_b), json={"decision": "accepted"}
    ).status_code in (403, 404)


def test_onboarding_cross_account_forbidden(client: TestClient, db_session: Session) -> None:
    """Нельзя завести пилот под чужой аккаунт (доступ проверяется до сервиса)."""
    aid_a, _uid_a = _account(db_session, "prsec4a")
    _aid_b, uid_b = _account(db_session, "prsec4b")
    resp = client.post(
        "/pilot/onboarding", headers=_h(uid_b), json={"account_id": aid_a, "company_name": "X"}
    )
    assert resp.status_code in (403, 404)


# --------------------------------------------------------------------------- #
# No forbidden mutations / no secrets                                         #
# --------------------------------------------------------------------------- #


def test_full_flow_creates_no_forbidden_entities(db_session: Session) -> None:
    """Онбординг + intelligence + brief + feedback НЕ создают публикаций/CRM/workflow/платежей."""
    wid, uid = _pilot(db_session, "prsec5")
    before = _forbidden_counts(db_session)
    AIPilotIntelligenceReportService(settings=_SETTINGS).generate_intelligence_report(
        db_session, wid, user_id=uid
    )
    AICEODailyBriefService(settings=_SETTINGS).generate_daily_brief(db_session, wid, user_id=uid)
    AIPilotFeedbackService(settings=_SETTINGS).accept_recommendation(
        db_session, wid, recommendation_id=1, user_id=uid
    )
    assert _forbidden_counts(db_session) == before  # всё осталось как было (0)


def test_no_secrets_in_outputs(db_session: Session) -> None:
    wid, uid = _pilot(db_session, "prsec6")
    report = AIPilotIntelligenceReportService(settings=_SETTINGS).generate_intelligence_report(
        db_session, wid, user_id=uid
    )
    brief = AICEODailyBriefService(settings=_SETTINGS).generate_daily_brief(
        db_session, wid, user_id=uid
    )
    fb = AIPilotFeedbackService(settings=_SETTINGS).accept_recommendation(
        db_session, wid, user_id=uid
    )
    for blob in (repr(report).lower(), repr(brief).lower(), repr(fb).lower()):
        for hint in _SECRET_HINTS:
            assert hint not in blob
