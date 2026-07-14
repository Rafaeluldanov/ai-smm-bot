"""Тесты настроек мониторинга live-автопилота (v0.6.1). Безопасные дефолты + effective-свойства."""

from app.config import Settings


def test_defaults_safe() -> None:
    s = Settings()
    assert s.live_autopilot_monitoring_enabled is True
    assert s.live_autopilot_monitoring_dry_run is True
    assert s.live_autopilot_monitoring_worker_enabled is False
    assert s.live_autopilot_incidents_enabled is True
    assert s.live_autopilot_kill_switch_enabled is True
    assert s.live_autopilot_kill_switch_require_confirmation is True


def test_auto_pause_off_by_default() -> None:
    s = Settings()
    assert s.live_autopilot_auto_pause_enabled is False
    assert s.live_autopilot_auto_pause_enabled_effective is False


def test_effective_properties() -> None:
    s = Settings()
    assert s.live_autopilot_monitoring_enabled_effective is True
    assert s.live_autopilot_monitoring_dry_run_effective is True
    # worker effective требует и общий флаг мониторинга, и worker-флаг:
    assert s.live_autopilot_monitoring_worker_enabled_effective is False
    assert s.live_autopilot_incidents_enabled_effective is True
    assert s.live_autopilot_kill_switch_enabled_effective is True


def test_worker_requires_monitoring_enabled() -> None:
    s = Settings(
        live_autopilot_monitoring_enabled=False, live_autopilot_monitoring_worker_enabled=True
    )
    # Общий флаг выключен → worker и инциденты недоступны, несмотря на их собственные флаги.
    assert s.live_autopilot_monitoring_worker_enabled_effective is False
    assert s.live_autopilot_incidents_enabled_effective is False


def test_window_and_dedup_seconds_bounds() -> None:
    s = Settings(live_autopilot_monitoring_window_hours=24, live_autopilot_incident_dedup_hours=24)
    assert s.live_autopilot_monitoring_window_seconds == 24 * 3600
    assert s.live_autopilot_incident_dedup_seconds == 24 * 3600
    # Границы: 0 трактуется как «не задано» → дефолт 24 ч; слишком большое клампится к 168 ч.
    assert (
        Settings(live_autopilot_monitoring_window_hours=0).live_autopilot_monitoring_window_seconds
        == 24 * 3600
    )
    assert (
        Settings(
            live_autopilot_monitoring_window_hours=9999
        ).live_autopilot_monitoring_window_seconds
        == 168 * 3600
    )


def test_confirmation_texts_safe() -> None:
    s = Settings()
    assert s.live_autopilot_pause_confirmation_text_safe == "PAUSE_AUTOPILOT"
    assert s.live_autopilot_resume_confirmation_text_safe == "RESUME_AUTOPILOT"
    # Пустой текст подтверждения не должен «отключить» подтверждение — есть безопасный дефолт.
    blanked = Settings(
        live_autopilot_pause_confirmation_text="  ", live_autopilot_resume_confirmation_text=""
    )
    assert blanked.live_autopilot_pause_confirmation_text_safe == "PAUSE_AUTOPILOT"
    assert blanked.live_autopilot_resume_confirmation_text_safe == "RESUME_AUTOPILOT"


def test_no_global_live_implied() -> None:
    s = Settings()
    # Мониторинг НЕ включает глобальные live-флаги.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False
