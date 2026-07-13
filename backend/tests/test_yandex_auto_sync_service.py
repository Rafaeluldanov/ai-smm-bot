"""Тесты сервиса авто-синхронизации Яндекс Диска (v0.5.7). Offline; без сети/удаления/live."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import yandex_auto_sync_repository as sync_repo
from app.schemas.project import ProjectCreate
from app.services.yandex_auto_sync_service import YandexAutoSyncService


def _seed(db: Session, slug: str = "ys"):  # noqa: ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x", full_name="И")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="Проект", slug=slug))
    project.account_id = account.id
    db.commit()
    return account, project, owner


def _svc() -> YandexAutoSyncService:
    return YandexAutoSyncService(settings=Settings())


def _add_media(db: Session, project_id: int, images: int = 6, videos: int = 1) -> None:
    for i in range(images):
        db.add(
            MediaAsset(
                project_id=project_id, file_name=f"img{i}.jpg", yandex_disk_path=f"/SMM/img{i}.jpg"
            )
        )
    for i in range(videos):
        db.add(
            MediaAsset(
                project_id=project_id, file_name=f"v{i}.mp4", yandex_disk_path=f"/SMM/v{i}.mp4"
            )
        )
    db.commit()


def test_get_or_create_profile(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-prof")
    profile = _svc().get_or_create_profile(db_session, project.id, owner.id)
    assert profile.status == "ready"
    assert profile.is_enabled is True
    again = _svc().get_or_create_profile(db_session, project.id)
    assert again.id == profile.id


def test_configure_profile(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-cfg")
    view = _svc().configure_profile(
        db_session,
        project.id,
        {
            "public_url": "https://disk.yandex.ru/d/abc",
            "root_folder": "Media",
            "default_tags": ["t"],
            "sync_frequency_minutes": 30,
        },
        owner.id,
    )
    assert view["has_public_url"] is True
    assert view["root_folder"] == "Media"
    assert view["sync_frequency_minutes"] == 30


def test_health_check_missing_url(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-nourl")
    result = _svc().health_check(db_session, project.id)
    assert "no_yandex_disk" in [b["type"] for b in result["blockers"]]


def test_health_check_low_media(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-low")
    _svc().configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    _add_media(db_session, project.id, images=2, videos=0)
    result = _svc().health_check(db_session, project.id)
    assert "too_few_media" in [b["type"] for b in result["blockers"]]


def test_preview_no_writes(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-prev")
    _add_media(db_session, project.id)
    before = db_session.query(MediaAsset).count()
    result = _svc().preview_sync(db_session, project.id)
    assert result["writes"] is False
    assert db_session.query(MediaAsset).count() == before


def test_run_dry_no_media_writes(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-dry")
    _add_media(db_session, project.id)
    before = db_session.query(MediaAsset).count()
    run = _svc().run_sync(db_session, project.id, dry_run=True)
    assert run["status"] == "preview"
    assert db_session.query(MediaAsset).count() == before


def test_run_network_disabled_blocked_safely(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-net")
    _add_media(db_session, project.id)
    before = db_session.query(MediaAsset).count()
    # network off + dry_run=false → безопасно блокируется, без сети/записи.
    run = _svc().run_sync(db_session, project.id, dry_run=False)
    assert run["status"] == "blocked"
    assert "network_disabled" in [b["type"] for b in run["blockers"]]
    assert db_session.query(MediaAsset).count() == before


def test_run_updates_profile_summary(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-sum")
    _svc().configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    _add_media(db_session, project.id)
    _svc().run_sync(db_session, project.id, dry_run=True)
    profile = sync_repo.get_profile_by_project_id(db_session, project.id)
    assert profile.last_sync_at is not None
    assert profile.media_count == 7
    assert profile.image_count == 6
    assert profile.video_count == 1


def test_no_delete_method_exists() -> None:
    # Сервис не имеет методов удаления/скрытия файлов.
    for name in dir(YandexAutoSyncService):
        assert "delete" not in name.lower()
        assert "hide" not in name.lower()


def test_public_view_no_raw_url_or_paths(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-safe")
    _svc().configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/SECRETPATH123"}, owner.id
    )
    dashboard = _svc().build_dashboard(db_session, project.id)
    blob = str(dashboard)
    assert "/d/SECRETPATH123" not in blob
    assert "/SMM/img" not in blob  # внутренние пути не утекают


def test_pause_resume(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-pr")
    assert _svc().pause_sync(db_session, project.id, owner.id)["status"] == "paused"
    assert _svc().resume_sync(db_session, project.id, owner.id)["status"] == "ready"


def test_client_summary(db_session: Session) -> None:
    account, project, owner = _seed(db_session, "ys-cs")
    _svc().configure_profile(
        db_session, project.id, {"public_url": "https://disk.yandex.ru/d/x"}, owner.id
    )
    _add_media(db_session, project.id)
    summary = _svc().build_client_summary(db_session, project.id)
    assert "Медиа готово" in summary["headline"]
