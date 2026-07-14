"""Тесты сервиса клиентского онбординга (v0.6.4, offline).

Инварианты:
- новый клиент/проект/media-профиль/календарь создаются;
- live НЕ включается (после онбординга READY, но LIVE=OFF);
- незавершённый онбординг блокирует finish; tenant isolation; без секретов.
"""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.onboarding_session import OnboardingSession
from app.models.project import Project
from app.models.project_autopilot_profile import ProjectAutopilotProfile
from app.models.project_yandex_sync_profile import ProjectYandexSyncProfile
from app.repositories import user_repository
from app.services.client_onboarding_service import (
    ClientOnboardingError,
    ClientOnboardingService,
)
from app.services.live_readiness_service import LiveReadinessService


def _svc() -> ClientOnboardingService:
    return ClientOnboardingService(
        settings=Settings(media_proxy_public_base_url="https://media.example.com")
    )


def _user(db: Session, email: str) -> int:
    return user_repository.create_user(db, email=email, password_hash="x").id


def _full_flow(db: Session, svc: ClientOnboardingService, user_id: int) -> dict:  # noqa: ANN202
    s = svc.start_onboarding(db, user_id, company_name="TEEON")
    sid = s["session_id"]
    svc.complete_business_step(
        db, sid, {"company_name": "TEEON", "industry": "мерч", "description": "одежда"}, user_id
    )
    svc.complete_media_step(
        db, sid, {"yandex_disk_url": "https://disk.yandex.ru/d/abc", "folder": "SMM"}, user_id
    )
    svc.complete_platform_step(db, sid, {"telegram": True, "vk": True}, user_id)
    svc.complete_goal_step(db, sid, {"goal": "sales", "frequency": "3_week"}, user_id)
    return s


def test_start_creates_account_project_session(db_session: Session) -> None:
    uid = _user(db_session, "obs1@e.com")
    s = _svc().start_onboarding(db_session, uid, company_name="TEEON")
    assert s["session_id"] and s["project_id"] and s["current_step"] == 1
    assert db_session.query(OnboardingSession).count() == 1
    project = db_session.get(Project, s["project_id"])
    assert project is not None and project.account_id is not None
    # autopilot-профиль создан, но выключен.
    profile = (
        db_session.query(ProjectAutopilotProfile).filter_by(project_id=s["project_id"]).first()
    )
    assert profile is not None and profile.is_enabled is False


def test_start_is_idempotent_resumes(db_session: Session) -> None:
    uid = _user(db_session, "obs-resume@e.com")
    svc = _svc()
    a = svc.start_onboarding(db_session, uid, company_name="A")
    b = svc.start_onboarding(db_session, uid, company_name="B")
    assert a["session_id"] == b["session_id"] and b["resumed"] is True
    assert db_session.query(OnboardingSession).count() == 1


def test_finished_session_is_not_resumed_as_active(db_session: Session) -> None:
    """После финиша (ready) новый start создаёт НОВЫЙ онбординг, а не подхватывает завершённый."""
    uid = _user(db_session, "obs-restart@e.com")
    svc = _svc()
    s = _full_flow(db_session, svc, uid)
    svc.finish_onboarding(db_session, s["session_id"], uid)
    # Второй запуск после завершения — это новая сессия/проект, не resume.
    again = svc.start_onboarding(db_session, uid, company_name="Второй бизнес")
    assert again["resumed"] is False
    assert again["session_id"] != s["session_id"]
    assert again["project_id"] != s["project_id"]
    assert db_session.query(OnboardingSession).count() == 2


def test_media_step_creates_profile_without_sync(db_session: Session) -> None:
    uid = _user(db_session, "obs-media@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    svc.complete_business_step(db_session, s["session_id"], {"company_name": "T"}, uid)
    svc.complete_media_step(
        db_session,
        s["session_id"],
        {"yandex_disk_url": "https://disk.yandex.ru/d/xyz", "folder": "SMM"},
        uid,
    )
    prof = db_session.query(ProjectYandexSyncProfile).filter_by(project_id=s["project_id"]).first()
    assert prof is not None and prof.public_url == "https://disk.yandex.ru/d/xyz"
    # media-профиль создан, но синхронизация не запускалась (нет счётчиков синка).
    assert prof.last_sync_at is None


def test_full_flow_ready_but_live_off(db_session: Session) -> None:
    uid = _user(db_session, "obs-full@e.com")
    svc = _svc()
    s = _full_flow(db_session, svc, uid)
    result = svc.finish_onboarding(db_session, s["session_id"], uid)
    assert result["status"] == "ready"
    assert result["live_enabled"] is False
    assert result["next_action"] == "Создать первый пост"
    # Ключевой инвариант: live-публикация выключена.
    gate = LiveReadinessService(settings=svc._settings).build_effective_live_gate(
        db_session, s["project_id"], "telegram"
    )
    assert gate["can_publish_live"] is False
    # Изолируем эффект онбординга от дефолта глобального флага: онбординг НЕ включает
    # ни один project/platform/full_auto live-переключатель.
    assert gate["project_live_enabled"] is False
    assert gate["platform_live_enabled"] is False
    assert gate["full_auto_live_enabled"] is False
    assert "project_live_disabled" in gate["blocked_reasons"]


def test_finish_blocked_when_incomplete(db_session: Session) -> None:
    uid = _user(db_session, "obs-incomplete@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    svc.complete_business_step(db_session, s["session_id"], {"company_name": "T"}, uid)
    with pytest.raises(ClientOnboardingError):
        svc.finish_onboarding(db_session, s["session_id"], uid)  # цель ещё не выбрана


def test_finish_blocked_when_steps_skipped(db_session: Session) -> None:
    """Нельзя проскочить из старта сразу в цель→финиш, минуя бизнес/площадки."""
    uid = _user(db_session, "obs-skip@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    # Прыжок сразу к цели (без шагов бизнес/площадки) — статус станет goal_completed.
    svc.complete_goal_step(
        db_session, s["session_id"], {"goal": "sales", "frequency": "3_week"}, uid
    )
    with pytest.raises(ClientOnboardingError):
        svc.finish_onboarding(db_session, s["session_id"], uid)


def test_business_requires_company_name(db_session: Session) -> None:
    uid = _user(db_session, "obs-noname@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="")
    with pytest.raises(ClientOnboardingError):
        svc.complete_business_step(db_session, s["session_id"], {"company_name": ""}, uid)


def test_platforms_requires_selection(db_session: Session) -> None:
    uid = _user(db_session, "obs-noplat@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    svc.complete_business_step(db_session, s["session_id"], {"company_name": "T"}, uid)
    svc.complete_media_step(db_session, s["session_id"], {"yandex_disk_url": ""}, uid)
    with pytest.raises(ClientOnboardingError):
        svc.complete_platform_step(db_session, s["session_id"], {}, uid)


def test_tenant_isolation(db_session: Session) -> None:
    uid_a = _user(db_session, "obs-a@e.com")
    uid_b = _user(db_session, "obs-b@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid_a, company_name="A")
    # Пользователь B не может трогать сессию A.
    with pytest.raises(ClientOnboardingError):
        svc.get_session(db_session, s["session_id"], user_id=uid_b)
    with pytest.raises(ClientOnboardingError):
        svc.complete_business_step(db_session, s["session_id"], {"company_name": "X"}, uid_b)


def test_goal_creates_calendar_and_content_rules(db_session: Session) -> None:
    from app.models.autopilot_calendar_plan import AutopilotCalendarPlan

    uid = _user(db_session, "obs-goal@e.com")
    svc = _svc()
    _full_flow(db_session, svc, uid)
    project_id = db_session.query(OnboardingSession).one().project_id
    # AutopilotCalendarPlan создан ассистентом.
    assert db_session.query(AutopilotCalendarPlan).filter_by(project_id=project_id).count() >= 1
    # Цель записана в content_rules автопилота.
    profile = db_session.query(ProjectAutopilotProfile).filter_by(project_id=project_id).first()
    assert profile is not None
    assert (profile.content_rules or {}).get("business_goal") == "sales"


def test_goal_creates_real_publishing_plan(db_session: Session) -> None:
    """Шаг цели создаёт РЕАЛЬНОЕ расписание (CrmPublishingPlan) — на нём работает автопилот."""
    from app.models.crm_bot_smm import CrmPublishingPlan

    uid = _user(db_session, "obs-plan@e.com")
    svc = _svc()
    _full_flow(db_session, svc, uid)
    project_id = db_session.query(OnboardingSession).one().project_id
    plans = db_session.query(CrmPublishingPlan).filter_by(project_id=project_id).all()
    assert len(plans) >= 1
    assert any(p.is_active for p in plans)
    # Признак реального расписания попал в goal_data (для checklist финиша).
    session = db_session.query(OnboardingSession).one()
    assert session.goal_data.get("calendar_ready") is True


def test_platform_step_creates_connection_live_off(db_session: Session) -> None:
    """Шаг площадок реально создаёт подключение платформы, но live_enabled=False."""
    from app.models.crm_bot_smm import CrmSmmResource

    uid = _user(db_session, "obs-conn@e.com")
    svc = _svc()
    s = svc.start_onboarding(db_session, uid, company_name="T")
    svc.complete_business_step(db_session, s["session_id"], {"company_name": "T"}, uid)
    svc.complete_media_step(db_session, s["session_id"], {"yandex_disk_url": ""}, uid)
    svc.complete_platform_step(db_session, s["session_id"], {"telegram": True}, uid)
    conn = (
        db_session.query(CrmSmmResource)
        .filter_by(project_id=s["project_id"], resource_type="telegram")
        .first()
    )
    assert conn is not None
    assert conn.live_enabled is False


def test_finish_populates_readiness_and_preview(db_session: Session) -> None:
    """Финиш реально прогоняет readiness (dry-run) и создаёт preview (needs_review), без live."""
    uid = _user(db_session, "obs-fin@e.com")
    svc = _svc()
    s = _full_flow(db_session, svc, uid)
    result = svc.finish_onboarding(db_session, s["session_id"], uid)
    # readiness реально отработал — статус не остался «unknown».
    assert result["readiness"]["status"] != "unknown"
    # preview реально создан как needs_review, без live-вызовов.
    assert result["preview"].get("status") == "needs_review"
    assert result["preview"].get("live_calls") is False
