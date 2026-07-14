"""Статические + поведенческие проверки безопасности контент-стратега (v0.6.6).

Инварианты:
- стратегия НЕ включает/НЕ меняет глобальные live-флаги, НЕ публикует;
- apply меняет только content_rules/черновик календаря (не активный календарь, не live);
- auto_apply выключен по умолчанию; операции бесплатны (0 units); секретов нет.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.content_strategist_service import ContentStrategistService

_MODULES = (
    "app.services.content_strategist_service",
    "app.services.seo_strategy_adapter",
    "app.services.trend_strategy_adapter",
    "app.repositories.content_strategy_repository",
    "app.api.content_strategy",
    "app.scripts.content_strategy_analyze",
    "app.scripts.content_strategy_recommend",
    "app.scripts.content_strategy_apply",
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


def test_no_publish_or_external_calls() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_once_if_allowed" not in src, module
        assert "publish_post(" not in src, module
        # стратег НЕ применяет активный календарь (apply_calendar_to_project) автоматически
        assert "apply_calendar_to_project" not in src, module


def test_apply_only_creates_calendar_draft() -> None:
    # apply вызывает create_calendar_plan (черновик), а не apply_calendar_to_project.
    src = _source("app.services.content_strategist_service")
    assert "create_calendar_plan" in src
    assert "dry_run=False" in src  # черновик пишется, но это draft-план, не публикация


def test_config_auto_apply_off_by_default() -> None:
    fields = set(Settings.model_fields)
    assert not any("content_strategy" in f and "live" in f for f in fields)
    s = Settings(media_proxy_public_base_url="https://m.example.com")
    assert s.content_strategy_auto_apply_enabled is False
    assert s.content_strategy_auto_apply_enabled_effective is False
    assert s.content_strategy_enabled is True


def test_strategy_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_CONTENT_STRATEGY_ANALYSIS,
        billing_service.USAGE_CONTENT_STRATEGY_RECOMMENDATION,
        billing_service.USAGE_CONTENT_STRATEGY_APPLY,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_recommendation_view_has_no_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="cssec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="cssec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="cssec"))
    project.account_id = account.id
    db_session.commit()
    svc = ContentStrategistService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )
    recs = svc.generate_recommendations(db_session, project.id)
    strategy = svc.get_strategy(db_session, project.id)
    blob = str(recs) + str(strategy)
    for token in ("api_key", "token", "secret", "password"):
        assert token not in blob.lower()
