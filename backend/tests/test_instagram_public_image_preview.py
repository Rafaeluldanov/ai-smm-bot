"""Тесты интеграции Instagram preview с media-proxy (needs_public_image_url, warnings)."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.publishing import FakePublishingClient
from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest
from app.schemas.project import ProjectCreate
from app.services import post_publication_service as pps_module
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry


def _service() -> PostPublicationService:
    reg = PublicationPlatformRegistry(
        {
            "telegram": FakePublishingClient("telegram"),
            "vk": FakePublishingClient("vk"),
            "instagram": FakePublishingClient("instagram"),
        }
    )
    return PostPublicationService(registry=reg)


def _post_with_image(db: Session):  # noqa: ANN202
    project = create_project(db, ProjectCreate(name="T", slug="teeon"))
    asset = media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project.id, file_name="a.jpg", yandex_disk_path="public://yandex/SMM/a.jpg"
        ),
    )
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="P",
            instagram_text="ig",
            vk_text="vk",
            telegram_text="tg",
            status="approved",
            media_asset_id=asset.id,
        ),
    )


def test_instagram_needs_public_image_url(db_session: Session) -> None:
    post = _post_with_image(db_session)
    preview = _service().preview_publication(
        db_session, post.id, PostPublishRequest(platforms=["instagram"])
    )
    item = preview.items[0]
    assert item.needs_public_image_url is True
    assert item.would_prepare_public_image_url is True
    assert item.media_proxy_enabled is True
    # Live-публикация не выполняется.
    assert item.would_send is False


def test_telegram_vk_do_not_need_public_image_url(db_session: Session) -> None:
    post = _post_with_image(db_session)
    preview = _service().preview_publication(
        db_session, post.id, PostPublishRequest(platforms=["telegram", "vk"])
    )
    for item in preview.items:
        assert item.needs_public_image_url is False
        assert item.would_prepare_public_image_url is False


def test_warning_when_base_url_not_https(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    post = _post_with_image(db_session)
    http_settings = Settings(
        _env_file=None, app_env="local", public_app_url="http://127.0.0.1:8000"
    )
    monkeypatch.setattr(pps_module, "get_settings", lambda: http_settings)
    preview = _service().preview_publication(
        db_session, post.id, PostPublishRequest(platforms=["instagram"])
    )
    item = preview.items[0]
    assert item.public_media_base_url_ready is False
    assert item.public_media_warning
    assert any("HTTPS" in w for w in item.media_warnings)


def test_https_ready_no_warning(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    post = _post_with_image(db_session)
    https_settings = Settings(
        _env_file=None, app_env="local", public_app_url="https://app.teeon.ru"
    )
    monkeypatch.setattr(pps_module, "get_settings", lambda: https_settings)
    preview = _service().preview_publication(
        db_session, post.id, PostPublishRequest(platforms=["instagram"])
    )
    item = preview.items[0]
    assert item.public_media_base_url_ready is True
    assert item.public_media_warning is None
