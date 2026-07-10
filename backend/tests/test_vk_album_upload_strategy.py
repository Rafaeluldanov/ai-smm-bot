"""Тесты VK API album-стратегии загрузки фото (offline; httpx.MockTransport).

Проверяют wall/album/auto стратегии, fallback wall→album при error 27, создание
альбома, PublishError для обязательных media_group постов, безопасный text-only для
старых постов, отсутствие утечки токена, а также probe (read-only и upload без
``wall.post``). Реальной сети/публикаций нет.
"""

import json
import urllib.parse
from pathlib import Path

import httpx
import pytest

from app.integrations.publishing import PublishError, PublishRequest
from app.integrations.vk.client import VKPublishingClient

TOKEN = "SECRET_VK_TOKEN_do_not_leak"
UPLOAD_HOST = "upload.vk.test"
ALBUM_TITLE = "AI SMM Bot uploads"


def _resp(payload: dict, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload)


def _err(code: int, msg: str = "vk error") -> httpx.Response:
    return _resp({"error": {"error_code": code, "error_msg": msg}})


class VkApi:
    """Настраиваемый VK API (wall/album), фиксирует вызовы и attachments у wall.post."""

    def __init__(
        self,
        *,
        wall_error: int | None = None,
        album_get_upload_error: int | None = None,
        album_present: bool = True,
    ) -> None:
        self.calls: list[str] = []
        self.wall_attachments: list[str | None] = []
        self._wall_error = wall_error
        self._album_get_upload_error = album_get_upload_error
        self._album_present = album_present
        self._next_id = 4444

    def _id(self) -> int:
        value = self._next_id
        self._next_id += 1
        return value

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        host = request.url.host
        self.calls.append(f"{host}{path}")
        if "groups.getById" in path:
            return _resp({"response": [{"id": 100, "name": "TEEON"}]})
        if "photos.getWallUploadServer" in path:
            return (
                _err(self._wall_error)
                if self._wall_error
                else _resp({"response": {"upload_url": f"https://{UPLOAD_HOST}/wall"}})
            )
        if host == UPLOAD_HOST and path == "/wall":
            return _resp({"server": 1, "photo": "[blob]", "hash": "h"})
        if "photos.saveWallPhoto" in path:
            return _resp({"response": [{"id": self._id(), "owner_id": -100}]})
        if "photos.getAlbums" in path:
            items = [{"id": 555, "title": ALBUM_TITLE}] if self._album_present else []
            return _resp({"response": {"items": items}})
        if "photos.createAlbum" in path:
            return _resp({"response": {"id": 999}})
        if "photos.getUploadServer" in path:
            return (
                _err(self._album_get_upload_error)
                if self._album_get_upload_error
                else _resp({"response": {"upload_url": f"https://{UPLOAD_HOST}/album"}})
            )
        if host == UPLOAD_HOST and path == "/album":
            return _resp({"server": 2, "photos_list": "[{}]", "hash": "ah"})
        if "photos.save" in path:
            return _resp({"response": [{"id": self._id(), "owner_id": -100}]})
        if "wall.post" in path:
            form = urllib.parse.parse_qs(request.content.decode())
            self.wall_attachments.append(form.get("attachments", [None])[0])
            return _resp({"response": {"post_id": 5}})
        return _resp({"error": {"error_code": 1, "error_msg": f"unexpected {path}"}}, 404)


def _client(
    api: VkApi, *, strategy: str, live: bool = True, album_id: str | None = None
) -> VKPublishingClient:
    return VKPublishingClient(
        token=TOKEN,
        default_target_id="-100",
        live_enabled=live,
        transport=httpx.MockTransport(api.handler),
        photo_upload_strategy=strategy,
        photo_album_id=album_id,
        photo_album_title=ALBUM_TITLE,
    )


def _request(jpg: Path, **payload: object) -> PublishRequest:
    return PublishRequest(
        platform="vk", target_id="-100", text="Пост", media_path=str(jpg), payload=dict(payload)
    )


@pytest.fixture
def jpg(tmp_path: Path) -> Path:
    path = tmp_path / "e.jpg"
    path.write_bytes(b"\xff\xd8\xff\xe0jpeg")
    return path


# --------------------------------------------------------------------------- #
# wall / auto / album                                                         #
# --------------------------------------------------------------------------- #


def test_wall_strategy_happy_path(jpg: Path) -> None:
    api = VkApi()
    response = _client(api, strategy="wall").publish_post(_request(jpg, media_kind="image"))
    assert response.raw["attached_photo"] == "photo-100_4444"
    assert response.raw["upload_strategy"] == "wall"
    assert any("photos.getWallUploadServer" in c for c in api.calls)
    assert not any("photos.getUploadServer" in c for c in api.calls)  # album не трогали


def test_auto_wall27_falls_back_to_album(jpg: Path) -> None:
    api = VkApi(wall_error=27)
    response = _client(api, strategy="auto").publish_post(_request(jpg, media_kind="image"))
    assert response.raw["attached_photo"] == "photo-100_4444"
    assert response.raw["upload_strategy"] == "album"
    # album flow: getAlbums → getUploadServer → save → wall.post attachment.
    assert any("photos.getAlbums" in c for c in api.calls)
    assert any("photos.getUploadServer" in c for c in api.calls)
    assert any("photos.save" in c and "saveWallPhoto" not in c for c in api.calls)
    assert api.wall_attachments == ["photo-100_4444"]
    assert TOKEN not in json.dumps(response.raw)


def test_album_strategy_uses_existing_album(jpg: Path) -> None:
    api = VkApi()
    response = _client(api, strategy="album").publish_post(_request(jpg, media_kind="image"))
    assert response.raw["upload_strategy"] == "album"
    assert response.raw["attached_photo"] == "photo-100_4444"
    # Альбом найден по названию → createAlbum НЕ вызывался.
    assert any("photos.getAlbums" in c for c in api.calls)
    assert not any("photos.createAlbum" in c for c in api.calls)


def test_album_strategy_creates_album_if_missing(jpg: Path) -> None:
    api = VkApi(album_present=False)
    response = _client(api, strategy="album").publish_post(_request(jpg, media_kind="image"))
    assert response.raw["upload_strategy"] == "album"
    assert any("photos.createAlbum" in c for c in api.calls)


def test_album_id_from_config_skips_getalbums(jpg: Path) -> None:
    api = VkApi()
    client = _client(api, strategy="album", album_id="12345")
    client.publish_post(_request(jpg, media_kind="image"))
    assert not any("photos.getAlbums" in c for c in api.calls)  # album_id задан явно


def test_album_error27_required_media_raises(jpg: Path) -> None:
    api = VkApi(album_get_upload_error=27)
    client = _client(api, strategy="album")
    with pytest.raises(PublishError) as exc_info:
        client.publish_post(_request(jpg, media_kind="image", media_policy="media_group"))
    # Обязательный media_group пост НЕ уходит text-only; wall.post не вызывался.
    assert api.wall_attachments == []
    assert "album" in str(exc_info.value)
    assert TOKEN not in str(exc_info.value)


def test_old_post_without_media_policy_falls_back_text_only(jpg: Path) -> None:
    # auto: wall 27 → album 27 → нет media_policy → безопасный text-only.
    api = VkApi(wall_error=27, album_get_upload_error=27)
    response = _client(api, strategy="auto").publish_post(_request(jpg, media_kind="image"))
    assert response.raw["media_upload_skipped"] is True
    assert response.raw["media_upload_error_code"] == 27
    assert api.wall_attachments == [None]  # текст без вложения
    assert TOKEN not in json.dumps(response.raw)


def test_token_not_leaked_in_album_flow(jpg: Path) -> None:
    api = VkApi(wall_error=27)
    response = _client(api, strategy="auto").publish_post(_request(jpg, media_kind="image"))
    assert TOKEN not in json.dumps(response.raw)
    assert TOKEN not in (response.external_url or "")


# --------------------------------------------------------------------------- #
# probe                                                                       #
# --------------------------------------------------------------------------- #


def test_probe_readonly_does_not_upload() -> None:
    api = VkApi(wall_error=27)  # community token: wall недоступен
    client = _client(api, strategy="auto", live=False)
    result = client.probe_photo_strategies(allow_upload=False)
    assert result["wall"]["ok"] is False and result["wall"]["error_code"] == 27
    assert result["album"]["ok"] is True  # getAlbums доступен
    assert result["recommended_strategy"] == "album"
    # Файл не загружался, wall.post не вызывался.
    assert not any(UPLOAD_HOST in c for c in api.calls)
    assert not any("wall.post" in c for c in api.calls)
    assert not any("saveWallPhoto" in c or "photos.save" in c for c in api.calls)


def test_probe_allow_upload_uploads_without_wall_post() -> None:
    api = VkApi(wall_error=27)
    client = _client(api, strategy="auto", live=False)
    result = client.probe_photo_strategies(allow_upload=True)
    assert result["wall"]["ok"] is False  # wall 27
    assert result["album"]["ok"] is True and result["album"]["attachment"].startswith("photo")
    assert result["recommended_strategy"] == "album"
    # Реальная загрузка в альбом была, НО wall.post — нет.
    assert any(f"{UPLOAD_HOST}/album" in c for c in api.calls)
    assert not any("wall.post" in c for c in api.calls)


def test_probe_never_leaks_token() -> None:
    api = VkApi()
    client = _client(api, strategy="auto", live=False)
    result = client.probe_photo_strategies(allow_upload=True)
    assert TOKEN not in json.dumps(result)
