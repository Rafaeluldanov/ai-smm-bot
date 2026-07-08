"""Тесты фотоальбома Telegram-публикации (v0.1.15).

Вся сеть подменяется через ``httpx.MockTransport`` — реальных вызовов нет. Live
включается только внутри теста на замоканном транспорте; токен не печатается и не
попадает в ``raw``/ошибки.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.publishing import PublishError, PublishRequest
from app.integrations.telegram.client import TelegramPublishingClient
from app.integrations.vk.client import VKPublishingClient
from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest
from app.schemas.project import ProjectCreate
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry

TOKEN = "SECRET_TG_TOKEN_do_not_leak"
CHANNEL = "@teeon_merch"


class TgCapture:
    """Записывает вызовы Telegram Bot API и тела запросов (без токена)."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.bodies: list[str] = []

    @property
    def last_body(self) -> str:
        return self.bodies[-1] if self.bodies else ""

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        self.calls.append(method)
        self.bodies.append(request.content.decode("utf-8", "replace"))
        if method == "sendMediaGroup":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": [
                        {"message_id": 101, "chat": {"username": "teeon_merch"}},
                        {"message_id": 102},
                        {"message_id": 103},
                    ],
                },
            )
        if method == "sendPhoto":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"message_id": 201, "chat": {"username": "teeon_merch"}},
                },
            )
        if method == "sendMessage":
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"message_id": 301, "chat": {"username": "teeon_merch"}},
                },
            )
        return httpx.Response(404, json={"ok": False, "description": "unknown"})  # pragma: no cover


class FakeDownloader:
    """Публичный загрузчик медиа без сети (возвращает готовые байты)."""

    def __init__(self, content: bytes = b"heic-bytes") -> None:
        self.content = content
        self.calls: list[tuple[str, str]] = []

    def download_public_media(self, disk_path: str, file_name: str) -> SimpleNamespace:
        self.calls.append((disk_path, file_name))
        return SimpleNamespace(bytes=self.content, content_type="image/heic", file_name=file_name)


class FakeImageProcessor:
    """Фейковый конвертер HEIC→JPEG: не открывает файл, отдаёт готовые байты."""

    def __init__(self) -> None:
        self.calls: list[tuple[bytes, str]] = []

    def enhance_image_bytes(
        self, image_bytes: bytes, profile: str, operations: dict[str, bool] | None = None
    ) -> SimpleNamespace:
        self.calls.append((image_bytes, profile))
        return SimpleNamespace(output_bytes=b"\xff\xd8\xff\xe0converted-jpeg")


def _no_network(request: httpx.Request) -> httpx.Response:  # pragma: no cover
    raise AssertionError("сеть не должна вызываться")


def _client(
    *,
    live_enabled: bool,
    handler,  # type: ignore[no-untyped-def]
    downloader: FakeDownloader | None = None,
    processor: FakeImageProcessor | None = None,
    max_photos: int = 10,
) -> TelegramPublishingClient:
    return TelegramPublishingClient(
        token=TOKEN,
        default_target_id=CHANNEL,
        live_enabled=live_enabled,
        transport=httpx.MockTransport(handler),
        media_downloader=downloader,
        image_processor=processor,
        max_media_group_photos=max_photos,
    )


def _request(**payload: object) -> PublishRequest:
    text = str(payload.pop("text", "Пост про футболки"))
    return PublishRequest(platform="telegram", target_id=CHANNEL, text=text, payload=dict(payload))


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


# --------------------------------------------------------------------------- #
# Безопасность: без сети при выключенном live                                   #
# --------------------------------------------------------------------------- #


def test_live_disabled_does_not_touch_network(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")
    client = _client(live_enabled=False, handler=_no_network)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_items=[_image_item(1, str(jpg))], media_kind="image"))
    assert "disabled" in str(exc_info.value).lower()
    assert TOKEN not in str(exc_info.value)


# --------------------------------------------------------------------------- #
# sendPhoto / sendMediaGroup                                                    #
# --------------------------------------------------------------------------- #


def test_single_image_uses_send_photo(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")
    capture = TgCapture()
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(
        _request(
            media_items=[_image_item(1, str(jpg))],
            media_kind="image",
            media_count=1,
            media_source="enhanced_variant",
        )
    )

    assert capture.calls == ["sendPhoto"]
    body = capture.last_body
    assert 'name="photo"' in body
    assert "a.jpg" in body
    assert "Пост про футболки" in body  # caption передан
    assert response.external_post_id == "201"
    assert response.raw["attached_photos_count"] == 1
    assert response.raw["media_kind"] == "image"
    assert response.raw["media_source"] == "enhanced_variant"
    assert response.raw["media_count"] == 1
    assert TOKEN not in json.dumps(response.raw)


def test_image_group_uses_send_media_group_with_single_caption(tmp_path: Path) -> None:
    jpgs = [tmp_path / f"e{index}.jpg" for index in range(3)]
    for jpg in jpgs:
        jpg.write_bytes(b"jpeg")
    capture = TgCapture()
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(
        _request(
            media_items=[_image_item(index + 1, str(jpgs[index])) for index in range(3)],
            media_kind="image_group",
            media_count=3,
            text="Подборка футболок",
        )
    )

    assert capture.calls == ["sendMediaGroup"]
    body = capture.last_body
    assert "attach://photo0" in body
    assert "attach://photo1" in body
    assert "attach://photo2" in body
    # caption — только у первого элемента альбома.
    assert body.count('"caption"') == 1
    assert "Подборка футболок" in body
    assert response.external_post_id == "101"
    assert response.raw["media_kind"] == "image_group"
    assert response.raw["attached_photos_count"] == 3
    assert TOKEN not in json.dumps(response.raw)


def test_heic_public_downloaded_and_converted_before_upload() -> None:
    capture = TgCapture()
    downloader = FakeDownloader(content=b"fake-heic")
    processor = FakeImageProcessor()
    client = _client(
        live_enabled=True, handler=capture.handler, downloader=downloader, processor=processor
    )

    response = client.publish_post(
        _request(
            media_items=[
                {
                    "id": 1,
                    "file_name": "orig.heic",
                    "yandex_disk_path": "public://yandex/teeon/teeon/orig.heic",
                    "media_kind": "image",
                }
            ],
            media_kind="image",
            media_count=1,
        )
    )

    assert downloader.calls == [("public://yandex/teeon/teeon/orig.heic", "orig.heic")]
    # Конвертация вызвана на HEIC-байтах оригинала (оригинал не перезаписан).
    assert processor.calls and processor.calls[0][0] == b"fake-heic"
    assert capture.calls == ["sendPhoto"]
    # В аплоад ушли именно сконвертированные JPEG-байты под .jpg-именем (не HEIC).
    body = capture.last_body
    assert "converted-jpeg" in body
    assert "orig.jpg" in body
    assert "orig.heic" not in body
    assert response.raw["attached_photos_count"] == 1


def test_video_in_media_items_skipped_photos_sent(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")
    capture = TgCapture()
    downloader = FakeDownloader()
    client = _client(live_enabled=True, handler=capture.handler, downloader=downloader)

    response = client.publish_post(
        _request(
            media_items=[_image_item(1, str(jpg)), _video_item(2, "clip.MOV")],
            media_kind="mixed",
            media_count=2,
        )
    )

    assert capture.calls == ["sendPhoto"]  # фото ушло, видео пропущено
    assert response.raw["attached_photos_count"] == 1
    assert any(
        "Telegram video upload is not implemented; video skipped" in w
        for w in response.raw["media_warnings"]
    )
    assert downloader.calls == []  # видео не скачивалось


def test_group_respects_max_media_group_photos(tmp_path: Path) -> None:
    jpgs = [tmp_path / f"e{index}.jpg" for index in range(4)]
    for jpg in jpgs:
        jpg.write_bytes(b"jpeg")
    capture = TgCapture()
    client = _client(live_enabled=True, handler=capture.handler, max_photos=2)

    response = client.publish_post(
        _request(
            media_items=[_image_item(index + 1, str(jpgs[index])) for index in range(4)],
            media_kind="image_group",
            media_count=4,
        )
    )

    assert capture.calls == ["sendMediaGroup"]
    assert response.raw["attached_photos_count"] == 2
    assert any("лимит альбома" in w.lower() for w in response.raw["media_warnings"])


# --------------------------------------------------------------------------- #
# Фолбэки и ошибки                                                             #
# --------------------------------------------------------------------------- #


def test_all_images_unavailable_falls_back_to_text(tmp_path: Path) -> None:
    capture = TgCapture()
    # media_path указывает на несуществующий файл, загрузчик не задан.
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(
        _request(
            media_items=[_image_item(1, str(tmp_path / "missing.jpg"))],
            media_kind="image",
            media_count=1,
        )
    )

    assert capture.calls == ["sendMessage"]
    assert response.raw["media_upload_skipped"] is True
    assert response.raw["attached_photos_count"] == 0
    assert response.raw["media_warnings"]
    assert response.external_post_id == "301"


def test_api_error_ok_false_raises_publish_error(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "description": "chat not found"})

    client = _client(live_enabled=True, handler=handler)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_items=[_image_item(1, str(jpg))], media_kind="image"))
    assert TOKEN not in str(exc_info.value)


def test_http_error_raises_publish_error(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"ok": False})

    client = _client(live_enabled=True, handler=handler)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_items=[_image_item(1, str(jpg))], media_kind="image"))
    assert TOKEN not in str(exc_info.value)


def test_send_photo_malformed_result_raises_publish_error(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        # sendPhoto вернул список вместо Message-объекта — ждём PublishError, не AttributeError.
        return httpx.Response(200, json={"ok": True, "result": [{"message_id": 42}]})

    client = _client(live_enabled=True, handler=handler)
    with pytest.raises(PublishError):
        client.publish_post(_request(media_items=[_image_item(1, str(jpg))], media_kind="image"))


def test_network_error_raises_without_leaking_token(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")

    def handler(request: httpx.Request) -> httpx.Response:
        # Транспортная ошибка — единственная ветка, где URL с токеном мог бы утечь.
        raise httpx.ConnectError("connection failed", request=request)

    client = _client(live_enabled=True, handler=handler)
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(media_items=[_image_item(1, str(jpg))], media_kind="image"))
    assert TOKEN not in str(exc_info.value)
    assert "connection failed" not in str(exc_info.value)  # текст исключения не подставляется


def test_token_not_leaked_in_raw_or_url(tmp_path: Path) -> None:
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"jpeg")
    capture = TgCapture()
    client = _client(live_enabled=True, handler=capture.handler)

    response = client.publish_post(
        _request(media_items=[_image_item(1, str(jpg))], media_kind="image")
    )
    assert TOKEN not in json.dumps(response.raw)
    assert TOKEN not in (response.external_url or "")


# --------------------------------------------------------------------------- #
# Dry-run preview через сервис: видно image_group/count/would_attach, без сети  #
# --------------------------------------------------------------------------- #


def _service(*, live_enabled: bool) -> PostPublicationService:
    transport = httpx.MockTransport(_no_network)
    registry = PublicationPlatformRegistry(
        {
            "telegram": TelegramPublishingClient(
                token=TOKEN,
                default_target_id=CHANNEL,
                live_enabled=live_enabled,
                transport=transport,
            ),
            "vk": VKPublishingClient(
                token="V", default_target_id="-100", live_enabled=live_enabled, transport=transport
            ),
        }
    )
    return PostPublicationService(
        registry=registry, default_targets={"telegram": CHANNEL, "vk": "-100"}
    )


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


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
            telegram_text="TG текст",
            vk_text="VK",
            instagram_text="IG",
            hashtags=["#teeon"],
            seo_keywords=["футболки"],
            status="approved",
            generation_notes={"media_asset_ids": ids},
        ),
    ).id
    return post_id, ids


def test_preview_telegram_image_group_without_network(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id, ids = _group_post(
        db_session, project_id, ["a.jpg", "b.jpg", "c.jpg", "d.jpg", "e.jpg"]
    )
    service = _service(live_enabled=False)

    preview = service.preview_publication(
        db_session, post_id, PostPublishRequest(platforms=["telegram"])
    )
    item = next(i for i in preview.items if i.platform == "telegram")
    assert item.media_kind == "image_group"
    assert item.media_count == 5
    assert item.would_attach_media is True
    assert set(item.media_asset_ids) == set(ids)
    assert item.live_enabled is False


def test_preview_telegram_mixed_marks_video_warning(db_session: Session) -> None:
    project_id = _project(db_session)
    post_id, _ids = _group_post(db_session, project_id, ["a.jpg", "clip.MOV"])
    service = _service(live_enabled=False)

    preview = service.preview_publication(
        db_session, post_id, PostPublishRequest(platforms=["telegram"])
    )
    item = next(i for i in preview.items if i.platform == "telegram")
    assert item.media_kind == "mixed"
    assert item.would_attach_media is True
    assert any(
        "Telegram video upload is not implemented; video skipped" in w for w in preview.warnings
    )
