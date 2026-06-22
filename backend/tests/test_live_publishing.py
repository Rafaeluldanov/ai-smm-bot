"""Тесты безопасной live-публикации: флаг, dry-run, предпочтение enhanced-копии.

Без реальной сети: Telegram/VK HTTP подменяются через httpx.MockTransport.
"""

from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session

from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    post_publication_repository,
    post_repository,
)
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import MediaAssetVariantCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest, PostScheduleRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _media(db: Session, project_id: int) -> int:
    return media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name="orig.HEIC",
            yandex_disk_path="public://yandex/teeon/teeon/orig.HEIC",
            source_type="internal",
            license_type="company_owned",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    ).id


def _post(
    db: Session, project_id: int, media_asset_id: int | None, status: str = "approved"
) -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=media_asset_id,
            title="Футболки",
            telegram_text="TG текст",
            vk_text="VK текст",
            instagram_text="IG",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status=status,
        ),
    ).id


def _approved_variant(db: Session, project_id: int, media_asset_id: int, output_path: str) -> int:
    return media_asset_variant_repository.create_variant(
        db,
        MediaAssetVariantCreate(
            media_asset_id=media_asset_id,
            project_id=project_id,
            variant_type="enhanced",
            status="approved",
            output_path=output_path,
        ),
    ).id


def _ok_handler(request: httpx.Request) -> httpx.Response:
    if "sendMessage" in request.url.path:
        return httpx.Response(
            200, json={"ok": True, "result": {"message_id": 7, "chat": {"username": "teeon"}}}
        )
    if "wall.post" in request.url.path:
        return httpx.Response(200, json={"response": {"post_id": 5}})
    return httpx.Response(404, json={"error": "unexpected"})  # pragma: no cover


def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("сеть не должна вызываться при выключенном live publishing")


def _service(
    *, live_enabled: bool, handler: Callable[[httpx.Request], httpx.Response]
) -> PostPublicationService:
    transport = httpx.MockTransport(handler)
    registry = PublicationPlatformRegistry(
        {
            "telegram": TelegramPublishingClient(
                token="T",
                default_target_id="@teeon",
                live_enabled=live_enabled,
                transport=transport,
            ),
            "vk": VKPublishingClient(
                token="V", default_target_id="-100", live_enabled=live_enabled, transport=transport
            ),
        }
    )
    return PostPublicationService(
        registry=registry, default_targets={"telegram": "@teeon", "vk": "-100"}
    )


# --- Предпочтение enhanced-копии в build_publish_request ---


def test_build_request_prefers_approved_enhanced_variant(db_session: Session) -> None:
    project_id = _project(db_session)
    media_id = _media(db_session, project_id)
    post_id = _post(db_session, project_id, media_id)
    _approved_variant(
        db_session, project_id, media_id, "backend/data/enhanced_media/001_x_social_safe.jpg"
    )
    service = _service(live_enabled=False, handler=_no_network)
    post = post_repository.get_post_by_id(db_session, post_id)
    assert post is not None

    request = service.build_publish_request(db_session, post, "telegram", "@teeon")
    assert request.text == "TG текст"
    assert request.media_path == "backend/data/enhanced_media/001_x_social_safe.jpg"
    assert request.payload["media_source"] == "enhanced_variant"


def test_build_request_falls_back_to_original_when_no_variant(db_session: Session) -> None:
    project_id = _project(db_session)
    media_id = _media(db_session, project_id)
    post_id = _post(db_session, project_id, media_id)
    service = _service(live_enabled=False, handler=_no_network)
    post = post_repository.get_post_by_id(db_session, post_id)
    assert post is not None

    request = service.build_publish_request(db_session, post, "vk", "-100")
    assert request.text == "VK текст"
    assert request.media_path is None
    assert request.payload["media_source"] == "original"
    assert request.payload["attachment"]["yandex_disk_path"].endswith("orig.HEIC")


def test_unapproved_variant_not_preferred(db_session: Session) -> None:
    project_id = _project(db_session)
    media_id = _media(db_session, project_id)
    post_id = _post(db_session, project_id, media_id)
    # вариант есть, но он НЕ approved (created) — берём оригинал.
    media_asset_variant_repository.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id,
            project_id=project_id,
            variant_type="enhanced",
            status="created",
            output_path="backend/data/enhanced_media/created.jpg",
        ),
    )
    service = _service(live_enabled=False, handler=_no_network)
    post = post_repository.get_post_by_id(db_session, post_id)
    assert post is not None

    request = service.build_publish_request(db_session, post, "telegram", "@teeon")
    assert request.media_path is None
    assert request.payload["media_source"] == "original"


def test_approved_variant_without_output_path_falls_back_to_original(db_session: Session) -> None:
    project_id = _project(db_session)
    media_id = _media(db_session, project_id)
    post_id = _post(db_session, project_id, media_id)
    # approved enhanced-вариант, но БЕЗ файла (output_path=None) — не годится.
    media_asset_variant_repository.create_variant(
        db_session,
        MediaAssetVariantCreate(
            media_asset_id=media_id,
            project_id=project_id,
            variant_type="enhanced",
            status="approved",
            output_path=None,
        ),
    )
    service = _service(live_enabled=False, handler=_no_network)
    post = post_repository.get_post_by_id(db_session, post_id)
    assert post is not None

    request = service.build_publish_request(db_session, post, "telegram", "@teeon")
    assert request.media_path is None
    assert request.payload["media_source"] == "original"


# --- Live disabled / enabled через сервис ---


def test_live_disabled_marks_failed_without_network(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, None)
    service = _service(live_enabled=False, handler=_no_network)
    service.schedule_post(db_session, post_id, PostScheduleRequest())

    result = service.publish_post(db_session, post_id, PostPublishRequest())

    assert result.failed_count == 2
    assert result.post_status != "published"
    publication = post_publication_repository.get_publication_by_post_and_platform(
        db_session, post_id, "telegram"
    )
    assert publication is not None
    assert publication.status == "failed"
    assert "Live publishing disabled by config" in (publication.error_message or "")


def test_live_enabled_publishes_via_mocked_transport(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, None)
    service = _service(live_enabled=True, handler=_ok_handler)
    service.schedule_post(db_session, post_id, PostScheduleRequest())

    result = service.publish_post(db_session, post_id, PostPublishRequest())

    assert result.published_count == 2
    assert result.post_status == "published"
    telegram = post_publication_repository.get_publication_by_post_and_platform(
        db_session, post_id, "telegram"
    )
    assert telegram is not None
    assert telegram.status == "published"
    assert telegram.external_post_id == "7"


def test_live_publish_idempotent_without_force(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post(db_session, project_id, None)
    service = _service(live_enabled=True, handler=_ok_handler)
    service.schedule_post(db_session, post_id, PostScheduleRequest())
    service.publish_post(db_session, post_id, PostPublishRequest())

    again = service.publish_post(db_session, post_id, PostPublishRequest())
    assert again.published_count == 0
    assert again.skipped_count == 2  # повтор без force не дублирует


def test_preview_does_not_send(db_session: Session) -> None:
    project_id = _project(db_session)
    media_id = _media(db_session, project_id)
    post_id = _post(db_session, project_id, media_id)
    _approved_variant(db_session, project_id, media_id, "backend/data/enhanced_media/p.jpg")
    # live disabled + транспорт, который упадёт при любом сетевом вызове.
    service = _service(live_enabled=False, handler=_no_network)

    preview = service.preview_publication(db_session, post_id, PostPublishRequest())

    assert preview.post_id == post_id
    assert {item.platform for item in preview.items} == {"telegram", "vk"}
    telegram_item = next(i for i in preview.items if i.platform == "telegram")
    assert telegram_item.text == "TG текст"
    assert telegram_item.preferred_media_path == "backend/data/enhanced_media/p.jpg"
    assert telegram_item.media_source == "enhanced_variant"
    assert telegram_item.live_enabled is False
    # Ничего не опубликовано — публикаций в БД нет.
    assert post_publication_repository.list_publications(db_session, post_id=post_id) == []
