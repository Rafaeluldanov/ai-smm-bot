"""Тесты мультиплатформенного dry-run preview (offline, SQLite, без сети).

Проверяет решения capability-слоя по платформам для image_group / video / mixed
постов: куда медиа прикрепится, где предупреждение, где live не реализован.
"""

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.instagram.client import InstagramPublishingClient
from app.integrations.rutube.client import RuTubePublishingClient
from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.integrations.youtube.client import YouTubePublishingClient
from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry

ALL_PLATFORMS = ["telegram", "vk", "instagram", "youtube", "rutube"]


def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("сеть не должна вызываться в preview")


def _service() -> PostPublicationService:
    transport = httpx.MockTransport(_no_network)
    registry = PublicationPlatformRegistry(
        {
            "telegram": TelegramPublishingClient(
                token="T", default_target_id="@t", live_enabled=False, transport=transport
            ),
            "vk": VKPublishingClient(
                token="V", default_target_id="-100", live_enabled=False, transport=transport
            ),
            "instagram": InstagramPublishingClient(
                token="I", default_target_id="ig", live_enabled=False
            ),
            "youtube": YouTubePublishingClient(
                token="Y", default_target_id="yt", live_enabled=False
            ),
            "rutube": RuTubePublishingClient(token="R", default_target_id="rt", live_enabled=False),
        }
    )
    return PostPublicationService(
        registry=registry,
        default_targets={
            "telegram": "@t",
            "vk": "-100",
            "instagram": "ig",
            "youtube": "yt",
            "rutube": "rt",
        },
    )


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _group_post(db: Session, project_id: int, file_names: list[str]) -> int:
    ids: list[int] = []
    for file_name in file_names:
        is_video = file_name.lower().rsplit(".", 1)[-1] in {"mov", "mp4", "m4v"}
        media_id = media_asset_repository.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project_id,
                file_name=file_name,
                yandex_disk_path=f"public://yandex/teeon/teeon/{file_name}",
                source_type="internal",
                license_type="company_owned",
                status="approved_video" if is_video else "approved",
                tags={"products": ["футболка"]},
            ),
        ).id
        ids.append(media_id)
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=ids[0],
            title="T",
            telegram_text="TG",
            vk_text="VK",
            instagram_text="IG",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status="approved",
            generation_notes={"media_asset_ids": ids},
        ),
    ).id


def _preview_by_platform(db: Session, post_id: int) -> dict:
    service = _service()
    preview = service.preview_publication(db, post_id, PostPublishRequest(platforms=ALL_PLATFORMS))
    return {item.platform: item for item in preview.items}


# --------------------------------------------------------------------------- #
# image_group пост                                                             #
# --------------------------------------------------------------------------- #


def test_image_group_across_platforms(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["a.jpg", "b.jpg", "c.jpg"])
    by = _preview_by_platform(db_session, post_id)

    assert by["telegram"].would_attach_media is True
    assert by["vk"].would_attach_media is True

    assert by["instagram"].would_attach_media is True
    assert any("not implemented" in w.lower() for w in by["instagram"].media_warnings)

    for video_platform in ("youtube", "rutube"):
        item = by[video_platform]
        assert item.would_attach_media is False
        assert item.unsupported_media_reason is not None
        assert "фото" in item.unsupported_media_reason.lower()
        # Скалярные поля отражают медиа поста (даже если платформа их не прикрепит).
        assert item.media_kind == "image_group"
        assert item.media_count == 3
        assert len(item.media_asset_ids) == 3
        assert item.would_send is False

    # capabilities присутствуют и live_implemented корректен.
    assert by["telegram"].platform_capabilities is not None
    assert by["telegram"].platform_capabilities.live_implemented is True
    assert by["instagram"].platform_capabilities.live_implemented is False


# --------------------------------------------------------------------------- #
# video пост                                                                   #
# --------------------------------------------------------------------------- #


def test_video_across_platforms(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["clip1.MOV", "clip2.MOV"])
    by = _preview_by_platform(db_session, post_id)

    assert by["youtube"].would_attach_media is True
    assert by["rutube"].would_attach_media is True

    # Скалярные поля видео-платформ отражают медиа поста, live не реализован.
    for video_platform in ("youtube", "rutube"):
        item = by[video_platform]
        assert item.media_kind == "video"
        assert item.media_count == 2
        assert len(item.media_asset_ids) == 2
        assert item.would_send is False  # live не реализован

    # Instagram reels: видео поддержано в preview, но live не реализован.
    assert by["instagram"].would_attach_media is True
    assert by["instagram"].would_send is False
    assert any("not implemented" in w.lower() for w in by["instagram"].media_warnings)

    assert by["telegram"].would_attach_media is False
    assert any("video" in w.lower() for w in by["telegram"].media_warnings)
    assert by["vk"].would_attach_media is False
    assert any("video skipped" in w for w in by["vk"].media_warnings)


# --------------------------------------------------------------------------- #
# mixed пост (фото + видео)                                                    #
# --------------------------------------------------------------------------- #


def test_mixed_across_platforms(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["a.jpg", "b.jpg", "clip.MOV"])
    by = _preview_by_platform(db_session, post_id)

    # Фото-платформы отправляют фото, видео пропускают.
    assert by["telegram"].would_attach_media is True
    assert any("video" in w.lower() for w in by["telegram"].media_warnings)
    assert by["vk"].would_attach_media is True
    assert any("video skipped" in w for w in by["vk"].media_warnings)

    # Видео-платформы выбирают видео.
    for video_platform in ("youtube", "rutube"):
        assert by[video_platform].would_attach_media is True

    # Instagram видит фото (carousel) + предупреждение про смешанное/видео.
    assert by["instagram"].would_attach_media is True
    assert by["instagram"].media_warnings


def test_single_image_telegram_reports_reason_not_silent(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["solo.jpg"])  # одиночное фото, не группа
    by = _preview_by_platform(db_session, post_id)

    telegram = by["telegram"]
    assert telegram.media_kind == "image"
    assert telegram.media_count == 1
    # Telegram не прикрепляет одиночное фото — но dry-run объясняет почему (не молча).
    assert telegram.would_attach_media is False
    assert telegram.unsupported_media_reason is not None
    assert "одиночное фото" in telegram.unsupported_media_reason
    assert any("одиночное фото" in w for w in telegram.media_warnings)
    # VK одиночное фото прикрепляет.
    assert by["vk"].would_attach_media is True


def test_vk_over_limit_truncation_surfaced_in_preview(db_session: Session) -> None:
    project_id = _project(db_session)
    files = [f"p{i}.jpg" for i in range(7)]  # VK max_images = 5
    post_id = _group_post(db_session, project_id, files)
    by = _preview_by_platform(db_session, post_id)

    vk = by["vk"]
    assert vk.would_attach_media is True
    assert vk.media_count == 7
    assert any("лимит" in w.lower() for w in vk.media_warnings)


def test_preview_does_not_send_anything(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["a.jpg", "b.jpg"])
    # _no_network transport упадёт при любом сетевом вызове; preview не должен слать.
    _preview_by_platform(db_session, post_id)
    from app.repositories import post_publication_repository

    assert post_publication_repository.list_publications(db_session, post_id=post_id) == []


def test_capabilities_listing_offline() -> None:
    service = _service()
    caps = service.list_platform_capabilities()
    by_platform = {c.platform: c for c in caps}
    assert set(by_platform) == set(ALL_PLATFORMS)
    assert by_platform["vk"].live_implemented is True
    assert by_platform["youtube"].live_implemented is False


@pytest.mark.parametrize("platform", ALL_PLATFORMS)
def test_every_platform_has_capabilities_in_preview(db_session: Session, platform: str) -> None:
    project_id = _project(db_session)
    post_id = _group_post(db_session, project_id, ["a.jpg", "b.jpg"])
    by = _preview_by_platform(db_session, post_id)
    assert by[platform].platform_capabilities is not None
    assert by[platform].platform_capabilities.platform == platform
