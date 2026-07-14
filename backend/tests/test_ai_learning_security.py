"""Статические + поведенческие проверки безопасности AI Learning Loop (v0.6.5).

Инварианты:
- обучение НЕ включает/НЕ меняет глобальные live-флаги;
- обучение НЕ публикует и НЕ вызывает внешние API;
- стратегия НЕ применяется автоматически (config default);
- обучение бесплатно (0 units); в представлениях нет секретов.
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services import billing_service
from app.services.ai_learning_service import AILearningService

_MODULES = (
    "app.services.ai_learning_service",
    "app.services.learning_context_builder",
    "app.services.post_performance_learning_service",
    "app.services.content_strategy_service",
    "app.repositories.ai_learning_repository",
    "app.api.ai_learning",
    "app.scripts.ai_learning_profile",
    "app.scripts.ai_learning_analyze",
    "app.scripts.ai_learning_recommend",
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
        assert "run_sync(" not in src, module


def test_config_has_no_ai_learning_live_flag() -> None:
    fields = set(Settings.model_fields)
    # У обучения нет собственного live-флага.
    assert not any("ai_learning" in f and "live" in f for f in fields)
    # Автоприменение стратегии выключено по умолчанию.
    s = Settings(media_proxy_public_base_url="https://m.example.com")
    assert s.ai_learning_auto_apply_strategy_enabled is False
    assert s.ai_learning_auto_apply_strategy_enabled_effective is False
    assert s.ai_learning_enabled is True


def test_learning_actions_are_free() -> None:
    svc = billing_service.BillingService()
    for action in (
        billing_service.USAGE_AI_LEARNING_ANALYZE,
        billing_service.USAGE_AI_LEARNING_RECOMMEND,
        billing_service.USAGE_AI_LEARNING_FEEDBACK,
        billing_service.USAGE_AI_LEARNING_RESET,
    ):
        assert svc.estimate_action_cost(action) == 0


def test_views_do_not_leak_secrets(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="aisec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="s", slug="aisec", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="s", slug="aisec"))
    project.account_id = account.id
    db_session.commit()
    svc = AILearningService(settings=Settings(media_proxy_public_base_url="https://m.example.com"))
    # Пытаемся протащить секрет в метаданные события.
    svc.record_event(
        db_session,
        project.id,
        entity="post",
        event="manual_feedback",
        source="client",
        metadata={"api_key": "123456:SECRETxyz", "note": "ok"},
    )
    summary = svc.get_summary(db_session, project.id)
    assert "123456:SECRETxyz" not in str(summary)
    # Публичное представление события не отдаёт метаданные наружу.
    for ev in summary["recent_events"]:
        assert "event_metadata" not in ev
        assert "api_key" not in str(ev)
