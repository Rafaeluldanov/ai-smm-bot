"""Тесты фото-вложения VK-публикации (v0.1.12).

Вся сеть подменяется через ``httpx.MockTransport`` — реальных вызовов нет. Live
включается только внутри теста на замоканном транспорте; токен не печатается.
"""

import json
import urllib.parse
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.publishing import PublishError, PublishRequest
from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.repositories import media_asset_repository, media_asset_variant_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.media_enhancement import MediaAssetVariantCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry

TOKEN = "SECRET_VK_TOKEN_do_not_leak"
UPLOAD_HOST = "upload.vk.test"


class VkCapture:
    """Записывает вызовы VK и параметр attachments у wall.post.

    ``error_on`` заставляет конкретный метод (``photos.getWallUploadServer`` /
    ``photos.saveWallPhoto``) вернуть VK-ошибку с кодом ``error_code``.
    """

    def __init__(self, *, error_on: str | None = None, error_code: int = 27) -> None:
        self.calls: list[str] = []
        self.wall_attachments: list[str | None] = []
        self._error_on = error_on
        self._error_code = error_code
        # Инкрементальные id фото: одиночная загрузка -> 4444, группа -> 4444,4445,...
        self._next_photo_id = 4444

    def _maybe_error(self, path: str) -> httpx.Response | None:
        if self._error_on and self._error_on in path:
            return httpx.Response(
                200,
                json={"error": {"error_code": self._error_code, "error_msg": "group auth failed"}},
            )
        return None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.calls.append(f"{request.url.host}{path}")
        if "photos.getWallUploadServer" in path:
            return self._maybe_error(path) or httpx.Response(
                200,
                json={"response": {"upload_url": f"https://{UPLOAD_HOST}/upload", "album_id": -14}},
            )
        if request.url.host == UPLOAD_HOST:
            return httpx.Response(200, json={"server": 1234, "photo": "[blob]", "hash": "h4sh"})
        if "photos.saveWallPhoto" in path:
            error = self._maybe_error(path)
            if error is not None:
                return error
            photo_id = self._next_photo_id
            self._next_photo_id += 1
            return httpx.Response(200, json={"response": [{"id": photo_id, "owner_id": -100}]})
        if "wall.post" in path:
            form = urllib.parse.parse_qs(request.content.decode())
            self.wall_attachments.append(form.get("attachments", [None])[0])
            return httpx.Response(200, json={"response": {"post_id": 5}})
        return httpx.Response(404, json={"error": {"error_code": 1, "error_msg": "unexpected"}})


class FakeDownloader:
    """Публичный загрузчик медиа без сети (возвращает готовые байты)."""

    def __init__(self, content: bytes = b"heic-bytes") -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    def download_public_media(self, disk_path: str, file_name: str) -> SimpleNamespace:
        self.calls.append((disk_path, file_name))
        return SimpleNamespace(bytes=self.content, content_type="image/heic", file_name=file_name)


def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("сеть не должна вызываться")


def _client(
    *,
    live_enabled: bool,
    handler,  # type: ignore[no-untyped-def]
    downloader: FakeDownloader | None = None,
) -> VKPublishingClient:
    return VKPublishingClient(
        token=TOKEN,
        default_target_id="-100",
        live_enabled=live_enabled,
        transport=httpx.MockTransport(handler),
        media_downloader=downloader,
    )


def _request(**payload: object) -> PublishRequest:
    media_path = payload.pop("media_path", None)
    return PublishRequest(
        platform="vk",
        target_id="-100",
        text="Пост",
        media_path=media_path,  # type: ignore[arg-type]
        payload=dict(payload),
    )


# --------------------------------------------------------------------------- #
# Безопасность: без сети при выключенном live и в dry-run                       #
# --------------------------------------------------------------------------- #


def test_live_disabled_does_not_touch_network() -> None:
    client = _client(live_enabled=False, handler=_no_network)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request())
    assert "disabled" in str(exc_info.value).lower()


# --------------------------------------------------------------------------- #
# Загрузка фото                                                                #
# --------------------------------------------------------------------------- #


def test_enhanced_jpg_attached_as_attachment(tmp_path: Path) -> None:
    jpg = tmp_path / "enhanced.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0jpeg-bytes")
    capture = VkCapture()
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(
        _request(
            media_path=str(jpg),
            media_source="enhanced_variant",
            media_kind="image",
            attachment={
                "file_name": "orig.HEIC",
                "yandex_disk_path": "public://yandex/t/orig.HEIC",
            },
        )
    )

    assert response.external_post_id == "5"
    assert capture.wall_attachments == ["photo-100_4444"]
    assert response.raw["attached_photo"] == "photo-100_4444"
    assert any("photos.getWallUploadServer" in call for call in capture.calls)
    assert any(UPLOAD_HOST in call for call in capture.calls)


def test_public_yandex_heic_downloaded_and_attached() -> None:
    capture = VkCapture()
    downloader = FakeDownloader(content=b"heic-file-bytes")
    client = _client(live_enabled=True, handler=capture.handler, downloader=downloader)

    response = client.publish_post(
        _request(
            media_source="original",
            media_kind="image",
            attachment={
                "file_name": "orig.HEIC",
                "yandex_disk_path": "public://yandex/teeon/teeon/orig.HEIC",
            },
        )
    )

    assert downloader.calls == [("public://yandex/teeon/teeon/orig.HEIC", "orig.HEIC")]
    assert capture.wall_attachments == ["photo-100_4444"]
    assert response.external_post_id == "5"


def test_video_skipped_with_warning_and_text_only() -> None:
    capture = VkCapture()
    downloader = FakeDownloader()
    client = _client(live_enabled=True, handler=capture.handler, downloader=downloader)

    response = client.publish_post(
        _request(
            media_source="original",
            media_kind="video",
            attachment={
                "file_name": "clip.MOV",
                "yandex_disk_path": "public://yandex/teeon/clip.MOV",
            },
        )
    )

    # Текст опубликован, вложения нет.
    assert capture.wall_attachments == [None]
    assert response.external_post_id == "5"
    # Предупреждение в raw; загрузка не запускалась.
    assert response.raw["media_warnings"]
    assert "clip.MOV" in response.raw["media_warnings"][0]
    assert downloader.calls == []
    assert not any("getWallUploadServer" in call for call in capture.calls)


# --------------------------------------------------------------------------- #
# Безопасный фолбэк при VK error_code=27 (групповой токен)                      #
# --------------------------------------------------------------------------- #

_GROUP_AUTH_WARNING = (
    "VK photo upload skipped: group token cannot call "
    "photos.getWallUploadServer/photos.saveWallPhoto"
)


def test_error_27_on_get_upload_server_falls_back_to_text_only(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture(error_on="photos.getWallUploadServer", error_code=27)
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(_request(media_path=str(jpg), media_kind="image"))

    # wall.post успешен, вложения нет.
    assert response.external_post_id == "5"
    assert capture.wall_attachments == [None]
    # raw описывает пропуск загрузки фото.
    assert response.raw["media_upload_skipped"] is True
    assert response.raw["media_upload_error_code"] == 27
    assert response.raw["media_warnings"] == [_GROUP_AUTH_WARNING]
    # Токен не утёк.
    assert TOKEN not in json.dumps(response.raw)


def test_error_27_on_save_wall_photo_falls_back_to_text_only(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture(error_on="photos.saveWallPhoto", error_code=27)
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(_request(media_path=str(jpg), media_kind="image"))

    assert response.external_post_id == "5"
    assert capture.wall_attachments == [None]
    assert response.raw["media_upload_skipped"] is True
    assert response.raw["media_upload_error_code"] == 27
    assert response.raw["media_warnings"] == [_GROUP_AUTH_WARNING]


def test_non_27_error_on_get_upload_server_raises(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture(error_on="photos.getWallUploadServer", error_code=15)
    client = _client(live_enabled=True, handler=capture.handler)

    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_path=str(jpg), media_kind="image"))
    # wall.post не вызывался (ошибка до публикации).
    assert capture.wall_attachments == []
    assert TOKEN not in str(exc_info.value)


# --------------------------------------------------------------------------- #
# Ошибки VK API и отсутствие утечки токена                                     #
# --------------------------------------------------------------------------- #


def _error_handler(request: httpx.Request) -> httpx.Response:
    if "photos.getWallUploadServer" in request.url.path:
        return httpx.Response(200, json={"error": {"error_code": 15, "error_msg": "Access denied"}})
    return httpx.Response(200, json={"response": {"post_id": 5}})  # pragma: no cover


def test_vk_api_error_becomes_publish_error(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    client = _client(live_enabled=True, handler=_error_handler)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_path=str(jpg), media_kind="image"))
    assert "Access denied" in str(exc_info.value)
    # Токен не попадает в текст ошибки.
    assert TOKEN not in str(exc_info.value)


def test_token_not_printed_in_response_or_error(tmp_path: Path) -> None:
    jpg = tmp_path / "ok.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture()
    client = _client(live_enabled=True, handler=capture.handler)
    response = client.publish_post(_request(media_path=str(jpg), media_kind="image"))
    assert TOKEN not in json.dumps(response.raw)
    assert TOKEN not in (response.external_url or "")

    disabled = _client(live_enabled=False, handler=_no_network)
    with pytest.raises(PublishError) as exc_info:
        disabled.publish_post(_request())
    assert TOKEN not in str(exc_info.value)


# --------------------------------------------------------------------------- #
# Dry-run preview через сервис: видно media_source/kind/attachment, без сети     #
# --------------------------------------------------------------------------- #


def _service(*, live_enabled: bool) -> PostPublicationService:
    transport = httpx.MockTransport(_no_network)
    registry = PublicationPlatformRegistry(
        {
            "telegram": TelegramPublishingClient(
                token="T", default_target_id="@t", live_enabled=live_enabled, transport=transport
            ),
            "vk": VKPublishingClient(
                token=TOKEN,
                default_target_id="-100",
                live_enabled=live_enabled,
                transport=transport,
            ),
        }
    )
    return PostPublicationService(
        registry=registry, default_targets={"telegram": "@t", "vk": "-100"}
    )


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _post_with_media(db: Session, project_id: int, file_name: str, *, variant: str | None) -> int:
    media_id = media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"public://yandex/teeon/teeon/{file_name}",
            source_type="internal",
            license_type="company_owned",
            status="approved",
            tags={"products": ["футболка"]},
        ),
    ).id
    if variant is not None:
        media_asset_variant_repository.create_variant(
            db,
            MediaAssetVariantCreate(
                media_asset_id=media_id,
                project_id=project_id,
                variant_type="enhanced",
                status="approved",
                output_path=variant,
            ),
        )
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            media_asset_id=media_id,
            title="T",
            telegram_text="TG",
            vk_text="VK",
            instagram_text="IG",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status="approved",
        ),
    ).id


def test_preview_shows_image_attachment_without_network(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post_with_media(
        db_session, project_id, "orig.HEIC", variant="backend/data/enhanced_media/e.jpg"
    )
    service = _service(live_enabled=False)

    preview = service.preview_publication(db_session, post_id, PostPublishRequest())
    vk_item = next(i for i in preview.items if i.platform == "vk")
    assert vk_item.media_source == "enhanced_variant"
    assert vk_item.preferred_media_path == "backend/data/enhanced_media/e.jpg"
    assert vk_item.media_kind == "image"
    assert vk_item.would_attach_media is True
    assert vk_item.live_enabled is False


def test_preview_marks_video_not_attached(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id = _post_with_media(db_session, project_id, "clip.MOV", variant=None)
    service = _service(live_enabled=False)

    preview = service.preview_publication(db_session, post_id, PostPublishRequest())
    vk_item = next(i for i in preview.items if i.platform == "vk")
    assert vk_item.media_kind == "video"
    assert vk_item.would_attach_media is False
    assert any("Видео" in w for w in preview.warnings)


# --------------------------------------------------------------------------- #
# Группа медиа (v0.1.14): несколько фото одним постом, видео пропускается        #
# --------------------------------------------------------------------------- #


class FakeImageProcessor:
    """Фейковый конвертер HEIC→JPEG: не открывает файл, отдаёт готовые байты."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def enhance_image_bytes(
        self, image_bytes: bytes, profile: str, operations: dict[str, bool] | None = None
    ) -> SimpleNamespace:
        self.calls.append((image_bytes, profile))
        return SimpleNamespace(output_bytes=b"\xff\xd8\xff\xe0converted-jpeg")


def _image_item(media_id: int, media_path: str) -> dict[str, object]:
    return {
        "id": media_id,
        "file_name": Path(media_path).name,
        "media_path": media_path,
        "media_kind": "image",
    }


def _video_item(media_id: int, file_name: str) -> dict[str, object]:
    return {
        "id": media_id,
        "file_name": file_name,
        "yandex_disk_path": f"public://yandex/teeon/{file_name}",
        "media_kind": "video",
    }


def test_image_group_uploads_all_photos(tmp_path: Path) -> None:
    jpgs = [tmp_path / f"e{index}.jpg" for index in range(3)]
    for jpg in jpgs:
        jpg.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    capture = VkCapture()
    client = _client(live_enabled=True, handler=capture.handler)

    media_items = [_image_item(index + 1, str(jpgs[index])) for index in range(3)]
    response = client.publish_post(_request(media_items=media_items, media_kind="image_group"))

    assert response.external_post_id == "5"
    attachments = capture.wall_attachments[0]
    assert attachments is not None
    assert attachments.split(",") == ["photo-100_4444", "photo-100_4445", "photo-100_4446"]
    assert sum("photos.getWallUploadServer" in call for call in capture.calls) == 3
    assert sum("photos.saveWallPhoto" in call for call in capture.calls) == 3
    assert response.raw["attached_photos"] == [
        "photo-100_4444",
        "photo-100_4445",
        "photo-100_4446",
    ]
    assert TOKEN not in json.dumps(response.raw)


def test_mixed_group_uploads_image_and_skips_video(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture()
    downloader = FakeDownloader()
    client = _client(live_enabled=True, handler=capture.handler, downloader=downloader)

    media_items = [_image_item(1, str(jpg)), _video_item(2, "clip.MOV")]
    response = client.publish_post(_request(media_items=media_items, media_kind="mixed"))

    # Только фото прикреплено; видео пропущено с предупреждением, скачивание видео не шло.
    assert capture.wall_attachments == ["photo-100_4444"]
    assert response.external_post_id == "5"
    warnings = response.raw["media_warnings"]
    assert any("VK video upload is not implemented; video skipped" in w for w in warnings)
    assert downloader.calls == []


def test_video_only_group_text_only_with_warning() -> None:
    capture = VkCapture()
    downloader = FakeDownloader()
    client = _client(live_enabled=True, handler=capture.handler, downloader=downloader)

    media_items = [_video_item(1, "clip.MOV")]
    response = client.publish_post(_request(media_items=media_items, media_kind="video"))

    assert capture.wall_attachments == [None]
    assert response.external_post_id == "5"
    assert any(
        "VK video upload is not implemented; video skipped" in w
        for w in response.raw["media_warnings"]
    )
    assert not any("getWallUploadServer" in call for call in capture.calls)
    assert downloader.calls == []


def test_group_error_27_falls_back_to_text_only(tmp_path: Path) -> None:
    jpgs = [tmp_path / f"e{index}.jpg" for index in range(2)]
    for jpg in jpgs:
        jpg.write_bytes(b"jpeg")
    capture = VkCapture(error_on="photos.getWallUploadServer", error_code=27)
    client = _client(live_enabled=True, handler=capture.handler)

    media_items = [_image_item(index + 1, str(jpgs[index])) for index in range(2)]
    response = client.publish_post(_request(media_items=media_items, media_kind="image_group"))

    assert response.external_post_id == "5"
    assert capture.wall_attachments == [None]
    assert response.raw["media_upload_skipped"] is True
    assert response.raw["media_upload_error_code"] == 27
    assert _GROUP_AUTH_WARNING in response.raw["media_warnings"]
    assert TOKEN not in json.dumps(response.raw)


def test_group_non_27_error_raises_publish_error(tmp_path: Path) -> None:
    jpg = tmp_path / "e.jpg"
    jpg.write_bytes(b"jpeg")
    capture = VkCapture(error_on="photos.getWallUploadServer", error_code=15)
    client = _client(live_enabled=True, handler=capture.handler)

    media_items = [_image_item(1, str(jpg))]
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_items=media_items, media_kind="image"))
    # wall.post не вызывался, токен не в тексте ошибки.
    assert capture.wall_attachments == []
    assert TOKEN not in str(exc_info.value)


def test_group_respects_max_group_photos(tmp_path: Path) -> None:
    jpgs = [tmp_path / f"e{index}.jpg" for index in range(4)]
    for jpg in jpgs:
        jpg.write_bytes(b"jpeg")
    capture = VkCapture()
    client = VKPublishingClient(
        token=TOKEN,
        default_target_id="-100",
        live_enabled=True,
        transport=httpx.MockTransport(capture.handler),
        max_group_photos=2,
    )

    media_items = [_image_item(index + 1, str(jpgs[index])) for index in range(4)]
    response = client.publish_post(_request(media_items=media_items, media_kind="image_group"))

    attachments = capture.wall_attachments[0]
    assert attachments is not None
    assert len(attachments.split(",")) == 2
    assert any("лимит вложений" in w.lower() for w in response.raw["media_warnings"])


def test_heic_group_item_converted_in_memory_before_upload(tmp_path: Path) -> None:
    heic = tmp_path / "orig.heic"
    heic.write_bytes(b"fake-heic-bytes")
    capture = VkCapture()
    processor = FakeImageProcessor()
    client = VKPublishingClient(
        token=TOKEN,
        default_target_id="-100",
        live_enabled=True,
        transport=httpx.MockTransport(capture.handler),
        image_processor=processor,
    )

    media_items = [_image_item(1, str(heic))]
    response = client.publish_post(_request(media_items=media_items, media_kind="image"))

    assert response.external_post_id == "5"
    assert capture.wall_attachments == ["photo-100_4444"]
    # Конвертация вызвана на HEIC-байтах оригинала (оригинал не перезаписан).
    assert processor.calls
    assert processor.calls[0][0] == b"fake-heic-bytes"
    assert heic.read_bytes() == b"fake-heic-bytes"


# --------------------------------------------------------------------------- #
# Dry-run preview группы медиа через сервис (без сети)                          #
# --------------------------------------------------------------------------- #


def _group_post(db: Session, project_id: int, file_names: list[str]) -> tuple[int, list[int]]:
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
    post_id = post_repository.create_post(
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
    return post_id, ids


def test_preview_image_group_without_network(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id, ids = _group_post(db_session, project_id, ["a.jpg", "b.jpg", "c.jpg"])
    service = _service(live_enabled=False)

    preview = service.preview_publication(db_session, post_id, PostPublishRequest())
    vk_item = next(i for i in preview.items if i.platform == "vk")
    assert vk_item.media_kind == "image_group"
    assert vk_item.media_count == 3
    assert vk_item.would_attach_media is True
    assert set(vk_item.media_asset_ids) == set(ids)


def test_preview_mixed_group_marks_video_warning(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id, _ids = _group_post(db_session, project_id, ["a.jpg", "clip.MOV"])
    service = _service(live_enabled=False)

    preview = service.preview_publication(db_session, post_id, PostPublishRequest())
    vk_item = next(i for i in preview.items if i.platform == "vk")
    assert vk_item.media_kind == "mixed"
    assert vk_item.media_count == 2
    assert vk_item.would_attach_media is True
    assert any("video skipped" in w for w in preview.warnings)
