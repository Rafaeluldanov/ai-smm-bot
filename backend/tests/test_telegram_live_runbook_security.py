"""Статические + поведенческие проверки безопасности Telegram runbook (v0.6.3).

Инварианты:
- runbook НЕ включает и НЕ меняет глобальные live-флаги; реальная отправка делегируется гейтам;
- безопасные дефолты настроек; в дашборде/попытках нет сырого токена/секретов;
- payload preview хранит только маскированный media_url (без raw-токена).
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService
from app.services.telegram_live_runbook_service import TelegramLiveRunbookService

_MODULES = (
    "app.services.telegram_live_runbook_service",
    "app.repositories.telegram_live_runbook_repository",
    "app.api.telegram_live_runbook",
    "app.scripts.telegram_live_runbook_check",
    "app.scripts.telegram_live_runbook_preview",
    "app.scripts.telegram_live_runbook_publish_test",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.telegram_runbook_enabled is True
    assert s.telegram_runbook_dry_run is True
    assert s.telegram_runbook_enabled_effective is True
    assert s.telegram_runbook_dry_run_effective is True
    # runbook не подразумевает включённой реальной публикации.
    assert s.telegram_live_publishing_enabled is False
    assert s.telegram_live_rollout_allow_real_send is False


def test_service_does_not_mutate_global_flags() -> None:
    src = _source("app.services.telegram_live_runbook_service").lower()
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "payments_live_enabled =",
        "allow_real_send = true",
    ):
        assert token not in src, token


def test_service_delegates_publishing_to_gated_rollout() -> None:
    src = _source("app.services.telegram_live_runbook_service")
    # Реальная публикация делегируется gated rollout-сервису, не переизобретается.
    assert "publish_once_if_allowed" in src
    assert "build_effective_telegram_live_status" in src


def test_no_publish_due_anywhere() -> None:
    for module in _MODULES:
        src = _source(module)
        assert "publish_due(" not in src, module


def test_no_secrets_in_dashboard(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="rbs@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="rbs", slug="rbs", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="P", slug="rbs"))
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": "123456:SECRETxyz", "external_id": "@chan"}
    )
    BillingService().manual_topup(db_session, account.id, 500, idempotency_key="rbs")
    post_repository.create_post(
        db_session,
        PostCreate(project_id=project.id, title="T", status="approved", telegram_text="hi"),
    )
    db_session.commit()
    svc = TelegramLiveRunbookService(
        settings=Settings(media_proxy_public_base_url="https://media.example.com")
    )
    dash = svc.build_dashboard(db_session, project.id)
    prev = svc.prepare_test_post(db_session, project.id)
    # Сырой бот-токен не утекает в дашборд/preview; media_url — только маскированный.
    assert "123456:SECRETxyz" not in str(dash)
    payload = prev["attempt"]["payload_preview"]
    media = payload.get("media_url_masked") or ""
    assert "media_url" not in payload  # сырого поля с полным токеном нет
    assert "…••••" in media or media == ""  # если ссылка есть — она маскирована
