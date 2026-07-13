"""Тесты воркера авто-синхронизации Яндекс Диска (v0.5.7). Offline; без сети/записи/live."""

import importlib
import inspect

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.services.yandex_auto_sync_service import YandexAutoSyncService


def _seed(db: Session, slug: str):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="П", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


from app.schemas.project import ProjectCreate  # noqa: E402


def test_worker_disabled_no_runs(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysw-off")
    svc = YandexAutoSyncService(settings=Settings())  # worker disabled by default
    result = svc.run_worker_tick(db_session, dry_run=True)
    assert result["enabled"] is False
    assert result["runs_created"] == 0


def test_worker_enabled_dry_run_no_writes(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ysw-dry")
    for i in range(3):
        db_session.add(
            MediaAsset(project_id=project.id, file_name=f"i{i}.jpg", yandex_disk_path=f"/i{i}.jpg")
        )
    db_session.commit()
    # Включаем worker, но dry-run → превью, без записи медиа.
    svc = YandexAutoSyncService(settings=Settings(yandex_auto_sync_worker_enabled=True))
    # profile должен существовать и быть due (next_sync_at is None).
    svc.get_or_create_profile(db_session, project.id)
    before = db_session.query(MediaAsset).count()
    result = svc.run_worker_tick(db_session, dry_run=True)
    assert result["enabled"] is True
    assert result["dry_run"] is True
    assert db_session.query(MediaAsset).count() == before


def test_scheduler_worker_tick_has_yandex_fields(db_session: Session) -> None:
    from app.services.scheduler_worker_service import SchedulerWorkerService

    result = SchedulerWorkerService(settings=Settings()).tick(db_session, force=True, dry_run=True)
    d = result.as_dict()
    assert d["yandex_auto_sync_enabled"] is False  # worker off by default
    assert "yandex_sync_media_imported" in d


def test_no_publish_due_import_or_call() -> None:
    src = inspect.getsource(importlib.import_module("app.services.yandex_auto_sync_service"))
    for token in ("scripts.publish_due", "publish_due(", "import publish_due"):
        assert token not in src


def test_no_live_publish_in_worker() -> None:
    src = inspect.getsource(
        importlib.import_module("app.services.scheduler_worker_service")
    ).lower()
    # yandex-sync hook не включает live-флаги публикации.
    assert "telegram_live_publishing_enabled =" not in src
    assert "vk_live_publishing_enabled =" not in src
