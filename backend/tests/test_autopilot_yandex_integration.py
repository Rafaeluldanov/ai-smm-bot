"""Тесты интеграции автопилота с авто-синхронизацией Яндекс Диска (v0.5.7). Без live-флагов."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.autopilot_service import AutopilotService
from app.services.yandex_auto_sync_service import YandexAutoSyncService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def test_no_yandex_profile_creates_blocker(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-nob")
    health = AutopilotService(settings=Settings()).run_health_check(db_session, project.id)
    assert "no_yandex_disk" in [b["type"] for b in health["blockers"]]


def test_sync_profile_url_clears_yandex_blocker(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-url")
    YandexAutoSyncService(settings=Settings()).configure_profile(
        db_session,
        project.id,
        {"public_url": "https://disk.yandex.ru/d/x", "root_folder": "SMM"},
        owner.id,
    )
    health = AutopilotService(settings=Settings()).run_health_check(db_session, project.id)
    assert "no_yandex_disk" not in [b["type"] for b in health["blockers"]]


def test_low_media_creates_blocker(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-low")
    YandexAutoSyncService(settings=Settings()).configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    health = AutopilotService(settings=Settings()).run_health_check(db_session, project.id)
    types = [b["type"] for b in health["blockers"]]
    # Нет медиа → no_media blocker.
    assert "no_media" in types


def test_enough_media_clears_media_blocker(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-ok")
    YandexAutoSyncService(settings=Settings()).configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    for i in range(6):
        db_session.add(
            MediaAsset(project_id=project.id, file_name=f"i{i}.jpg", yandex_disk_path=f"/i{i}.jpg")
        )
    db_session.commit()
    health = AutopilotService(settings=Settings()).run_health_check(db_session, project.id)
    types = [b["type"] for b in health["blockers"]]
    assert "no_media" not in types
    assert "no_yandex_disk" not in types


def test_dashboard_yandex_status_uses_sync_profile(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-dash")
    YandexAutoSyncService(settings=Settings()).configure_profile(
        db_session,
        project.id,
        {"public_url": "https://disk.yandex.ru/d/x", "root_folder": "SMM"},
        owner.id,
    )
    dashboard = AutopilotService(settings=Settings()).build_autopilot_dashboard(
        db_session, project.id
    )
    assert dashboard["yandex_disk_status"]["connected"] is True


def test_no_live_flags_changed(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "api-live")
    settings = Settings()
    YandexAutoSyncService(settings=settings).run_sync(db_session, project.id, dry_run=True)
    assert settings.telegram_live_publishing_enabled is False
    assert settings.vk_live_publishing_enabled is False
    assert settings.instagram_live_publishing_enabled is False
    assert settings.payments_live_enabled is False
