"""Статические + поведенческие проверки безопасности онбординга (v0.6.4).

Инварианты:
- онбординг НЕ включает и НЕ меняет глобальные live-флаги (READY, но LIVE=OFF);
- в представлении сессии нет секретов/токенов;
- финиш НЕ публикует (preview-first).
"""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.live_publish_attempt import LivePublishAttempt
from app.repositories import user_repository
from app.services.client_onboarding_service import ClientOnboardingService

_MODULES = (
    "app.services.client_onboarding_service",
    "app.repositories.onboarding_repository",
    "app.api.onboarding",
    "app.scripts.onboarding_start",
    "app.scripts.onboarding_status",
    "app.scripts.onboarding_demo",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def _svc() -> ClientOnboardingService:
    return ClientOnboardingService(
        settings=Settings(media_proxy_public_base_url="https://media.example.com")
    )


def test_service_does_not_mutate_global_live_flags() -> None:
    src = _source("app.services.client_onboarding_service").lower()
    for token in (
        "telegram_live_publishing_enabled =",
        "vk_live_publishing_enabled =",
        "instagram_live_publishing_enabled =",
        "payments_live_enabled =",
        "allow_real_send = true",
    ):
        assert token not in src, token


def test_no_publish_or_live_send_in_onboarding() -> None:
    src = _source("app.services.client_onboarding_service")
    # Онбординг НЕ публикует и НЕ включает live — только preview (create_first_draft_now).
    assert "publish_once_if_allowed" not in src
    assert "publish_post(" not in src
    assert "run_sync(" not in src  # media-профиль без сетевой синхронизации


def test_finish_does_not_send_live(db_session: Session) -> None:
    uid = user_repository.create_user(db_session, email="obsec@e.com", password_hash="x").id
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    sid = s["session_id"]
    svc.complete_business_step(db_session, sid, {"company_name": "T"}, uid)
    svc.complete_media_step(db_session, sid, {"yandex_disk_url": ""}, uid)
    svc.complete_platform_step(db_session, sid, {"telegram": True}, uid)
    svc.complete_goal_step(db_session, sid, {"goal": "sales", "frequency": "3_week"}, uid)
    result = svc.finish_onboarding(db_session, sid, uid)
    assert result["live_enabled"] is False
    assert (result["preview"] or {}).get("live_calls") is not True
    # Реальная live-отправка не выполнялась → нет published live-попыток.
    assert db_session.query(LivePublishAttempt).filter_by(status="published").count() == 0


def test_session_view_has_no_secrets(db_session: Session) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    uid = user_repository.create_user(db_session, email="obsec2@e.com", password_hash="x").id
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    sid = s["session_id"]
    svc.complete_business_step(db_session, sid, {"company_name": "T"}, uid)
    svc.complete_media_step(db_session, sid, {"yandex_disk_url": ""}, uid)
    # Подключаем telegram с секретом через onboarding platform step.
    svc.complete_platform_step(
        db_session,
        sid,
        {"telegram": {"api_key": "123456:SECRETxyz", "external_id": "@chan"}},
        uid,
    )
    view = svc.get_session(db_session, sid, user_id=uid)
    # Сырой токен не попадает в представление сессии.
    assert "123456:SECRETxyz" not in str(view)
    # Даже если платформа задана словарём — в session.platform_data только selected/connected.
    assert "api_key" not in str(view.get("platform_data", {}))
    _ = PlatformConnectionService  # noqa: F841
