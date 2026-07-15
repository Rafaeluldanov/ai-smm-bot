"""Статические + поведенческие проверки безопасности AI Campaign Manager (v0.6.7).

Инварианты:
- кампания НЕ публикует, НЕ включает/меняет глобальные live-флаги;
- НЕ меняет активный календарь (apply_calendar_to_project) и НЕ ходит во внешние рекламные API;
- auto_apply выключен по умолчанию; операции бесплатны (0 units); секретов нет.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_campaign_manager_service import AICampaignManagerService

_MODULES = (
    "app.services.ai_campaign_manager_service",
    "app.repositories.ai_campaign_repository",
    "app.api.ai_campaigns",
    "app.scripts.ai_campaign_create",
    "app.scripts.ai_campaign_plan",
    "app.scripts.ai_campaign_apply",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_no_global_live_flag_mutation() -> None:
    for module in _MODULES:
        src = _source(module).lower()
        for token in (
            "telegram_live_publishing_enabled =",
            "vk_live_publishing_enabled =",
            "instagram_live_publishing_enabled =",
            "allow_real_send = true",
        ):
            assert token not in src, f"{module}: {token}"


def test_no_publish_no_active_calendar_no_ads_api() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_once_if_allowed" not in src, module
        assert "publish_post(" not in src, module
        # НЕ активирует календарь и не трогает активное расписание.
        assert "apply_calendar_to_project" not in src, module
        # Никаких внешних рекламных API.
        for ads in ("ads.api", "adwords", "facebook_ads", "vk_ads", "yandex_direct"):
            assert ads not in src.lower(), f"{module}: {ads}"


def test_apply_only_creates_draft() -> None:
    src = _source("app.services.ai_campaign_manager_service")
    assert "create_calendar_plan" in src
    assert "dry_run=False" in src  # черновик (draft) при apply


def test_config_auto_apply_off_by_default() -> None:
    fields = set(Settings.model_fields)
    assert not any("ai_campaign" in f and "live" in f for f in fields)
    s = Settings(media_proxy_public_base_url="https://m.example.com")
    assert s.ai_campaign_auto_apply_enabled is False
    assert s.ai_campaign_auto_apply_enabled_effective is False
    assert s.ai_campaign_enabled is True


def test_campaign_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_AI_CAMPAIGN_CREATE,
        billing_service.USAGE_AI_CAMPAIGN_PLAN,
        billing_service.USAGE_AI_CAMPAIGN_APPLY,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_campaign_view_has_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="camsec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="camsec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="camsec"))
    project.account_id = account.id
    db_session.commit()
    svc = AICampaignManagerService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )
    cid = svc.create_campaign(
        db_session, project.id, name="C", goal="sales", product_context={"name": "Худи"}
    )["id"]
    svc.plan_campaign(db_session, cid)
    blob = str(svc.get_campaign(db_session, cid)) + str(svc.list_recommendations(db_session, cid))
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
