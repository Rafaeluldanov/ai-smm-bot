"""Тесты конфигурации фонового scheduler-worker (defaults/safe/allowlist + env)."""

from pathlib import Path

from app.config import Settings

_ROOT = Path(__file__).resolve().parents[2]


def test_defaults_disabled_and_dry_run() -> None:
    s = Settings(_env_file=None)
    assert s.scheduler_worker_enabled is False
    assert s.scheduler_worker_enabled_effective is False
    assert s.scheduler_worker_dry_run is True
    assert s.scheduler_worker_create_drafts is True


def test_interval_safe_bounds() -> None:
    assert (
        Settings(
            _env_file=None, scheduler_worker_interval_seconds=1
        ).scheduler_worker_interval_seconds_safe
        == 10
    )
    assert (
        Settings(
            _env_file=None, scheduler_worker_interval_seconds=99999
        ).scheduler_worker_interval_seconds_safe
        == 3600
    )
    assert (
        Settings(
            _env_file=None, scheduler_worker_interval_seconds=120
        ).scheduler_worker_interval_seconds_safe
        == 120
    )


def test_platform_allowlist_parsing() -> None:
    s = Settings(_env_file=None, scheduler_worker_platform_allowlist="telegram, VK , instagram")
    assert s.scheduler_worker_platform_allowlist_list == ["telegram", "vk", "instagram"]
    assert Settings(_env_file=None).scheduler_worker_platform_allowlist_list == []


def test_account_allowlist_parsing() -> None:
    s = Settings(_env_file=None, scheduler_worker_account_allowlist="1, 2 ,x, 3")
    assert s.scheduler_worker_account_allowlist_list == [1, 2, 3]
    assert Settings(_env_file=None).scheduler_worker_account_allowlist_list == []


def test_no_live_flags_implied() -> None:
    s = Settings(_env_file=None, scheduler_worker_enabled=True)
    # Включённый worker не подразумевает никаких live-флагов.
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False
    assert s.payments_live_enabled is False


def test_env_examples_have_worker_flags() -> None:
    for name in (".env.example", ".env.production.example"):
        text = (_ROOT / name).read_text(encoding="utf-8")
        assert "SCHEDULER_WORKER_ENABLED=false" in text
        assert "SCHEDULER_WORKER_DRY_RUN=true" in text


def test_docker_compose_has_scheduler_service() -> None:
    text = (_ROOT / "docker-compose.prod.example.yml").read_text(encoding="utf-8")
    assert "scheduler-worker:" in text
    assert "scheduler_worker_loop" in text
