"""Тесты публичного клиента Яндекс Диска (httpx.MockTransport, без сети, без токена)."""

from collections.abc import Callable

import httpx
import pytest

from app.integrations.yandex_disk.client import (
    YandexDiskError,
    YandexDiskNotFoundError,
    YandexDiskPublicClient,
    YandexDiskPublicResource,
)

BASE = "https://disk.example/v1/disk"


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/public/resources/download"):
        return httpx.Response(200, json={"href": "https://dl.example/file"})
    path = request.url.params.get("path")
    if path == "/missing":
        return httpx.Response(404, json={"message": "not found"})
    if path in (None, "/SMM"):
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {"name": "Тион", "path": "/SMM/Тион", "type": "dir"},
                        {
                            "name": "a.jpg",
                            "path": "/SMM/a.jpg",
                            "type": "file",
                            "media_type": "image",
                            "mime_type": "image/jpeg",
                        },
                    ]
                }
            },
        )
    if path == "/SMM/Тион":
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {
                            "name": "b.png",
                            "path": "/SMM/Тион/b.png",
                            "type": "file",
                            "media_type": "image",
                        },
                        {
                            "name": "c.mp4",
                            "path": "/SMM/Тион/c.mp4",
                            "type": "file",
                            "media_type": "video",
                        },
                    ]
                }
            },
        )
    return httpx.Response(200, json={"_embedded": {"items": []}})


def _client() -> YandexDiskPublicClient:
    return YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(_handler))


def test_list_public_resources_parses_embedded_items() -> None:
    resources = _client().list_public_resources("https://disk.yandex.ru/d/X", "/SMM")
    assert {r.name for r in resources} == {"Тион", "a.jpg"}
    image = next(r for r in resources if r.name == "a.jpg")
    assert image.is_file
    assert image.is_media


def test_recursive_returns_only_files() -> None:
    files = _client().list_public_files_recursive("pk", "/SMM", max_depth=5)
    assert sorted(f.name for f in files) == ["a.jpg", "b.png", "c.mp4"]
    assert all(f.is_file for f in files)


def test_download_url_parses_href() -> None:
    assert _client().get_public_download_url("pk", "/SMM/a.jpg") == "https://dl.example/file"


def test_not_found_raises() -> None:
    with pytest.raises(YandexDiskNotFoundError):
        _client().list_public_resources("pk", "/missing")


def test_no_oauth_token_required() -> None:
    seen = {"auth": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if any(key.lower() == "authorization" for key in request.headers):
            seen["auth"] = True
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    client.list_public_resources("pk", "/SMM")
    assert seen["auth"] is False


# --- Скачивание: фолбэк на прямую ссылку из метаданных, когда download 404 ---


def _fallback_handler(request: httpx.Request) -> httpx.Response:
    # На реальном публичном диске download-эндпоинт 404-ит для таких путей (HEIC).
    if request.url.path.endswith("/public/resources/download"):
        return httpx.Response(404, json={"message": "not found"})
    path = request.url.params.get("path")
    if path in ("/teeon", "teeon"):
        return httpx.Response(
            200,
            json={
                "_embedded": {
                    "items": [
                        {
                            "name": "IMG_5007.HEIC",
                            "path": "/teeon/IMG_5007.HEIC",
                            "type": "file",
                            "media_type": "image",
                            "file": "https://dl.example/heic-direct",
                        }
                    ]
                }
            },
        )
    return httpx.Response(200, json={"_embedded": {"items": []}})


def _fallback_client() -> YandexDiskPublicClient:
    return YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(_fallback_handler))


def test_from_api_maps_file_to_download_url() -> None:
    resource = YandexDiskPublicResource.from_api(
        {"name": "x.jpg", "path": "/x.jpg", "type": "file", "file": "https://dl/x"}
    )
    assert resource.download_url == "https://dl/x"
    assert resource.file == "https://dl/x"


def test_find_public_resource_by_path_locates_file_in_parent() -> None:
    resource = _fallback_client().find_public_resource_by_path("pk", "/teeon/IMG_5007.HEIC")
    assert resource.name == "IMG_5007.HEIC"
    assert resource.download_url == "https://dl.example/heic-direct"


def test_find_public_resource_by_path_handles_no_leading_slash() -> None:
    resource = _fallback_client().find_public_resource_by_path("pk", "teeon/IMG_5007.HEIC")
    assert resource.name == "IMG_5007.HEIC"


def test_find_public_resource_by_path_missing_raises() -> None:
    with pytest.raises(YandexDiskNotFoundError):
        _fallback_client().find_public_resource_by_path("pk", "/teeon/UNKNOWN.HEIC")


def test_download_url_falls_back_to_metadata_file_on_404() -> None:
    url = _fallback_client().get_public_download_url("pk", "/teeon/IMG_5007.HEIC")
    assert url == "https://dl.example/heic-direct"


def test_download_url_uses_metadata_when_endpoint_returns_no_href() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(200, json={})  # 200, но без href
        path = request.url.params.get("path")
        if path in ("/teeon", "teeon"):
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "items": [
                            {
                                "name": "IMG.HEIC",
                                "path": "/teeon/IMG.HEIC",
                                "type": "file",
                                "file": "https://dl.example/from-meta",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    assert client.get_public_download_url("pk", "/teeon/IMG.HEIC") == "https://dl.example/from-meta"


def test_download_url_raises_when_no_href_and_no_metadata() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(404, json={})
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    with pytest.raises(YandexDiskNotFoundError):
        client.get_public_download_url("pk", "/teeon/IMG_5007.HEIC")


def test_download_url_retries_download_endpoint_without_leading_slash() -> None:
    # Лидирующий «/» 404-ит, вариант без «/» отдаёт href — без фолбэка на метаданные.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            requested = request.url.params.get("path")
            if requested and requested.startswith("/"):
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json={"href": "https://dl.example/noslash"})
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    assert (
        client.get_public_download_url("pk", "/teeon/IMG_5007.HEIC") == "https://dl.example/noslash"
    )


def test_download_url_falls_back_to_metadata_on_non_404_error() -> None:
    # Яндекс часто отдаёт 400 (DiskPathFormatError) на download-эндпоинте для
    # «неудобных» путей — фолбэк на метаданные всё равно должен сработать.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(400, json={"message": "DiskPathFormatError"})
        path = request.url.params.get("path")
        if path in ("/teeon", "teeon"):
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "items": [
                            {
                                "name": "IMG.HEIC",
                                "path": "/teeon/IMG.HEIC",
                                "type": "file",
                                "file": "https://dl.example/heic-400",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    assert client.get_public_download_url("pk", "/teeon/IMG.HEIC") == "https://dl.example/heic-400"


def test_download_url_paginates_parent_listing_to_find_file() -> None:
    # Папка с сотнями файлов: целевой файл лежит НЕ на первой странице листинга.
    # Download-эндпоинт 404-ит, поэтому фолбэк обязан долистать до нужной страницы.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(404, json={"message": "not found"})
        offset = int(request.url.params.get("offset", "0"))
        if offset == 0:
            items = [
                {
                    "name": f"OTHER_{i}.HEIC",
                    "path": f"/teeon/OTHER_{i}.HEIC",
                    "type": "file",
                    "file": f"https://dl.example/{i}",
                }
                for i in range(100)
            ]
            return httpx.Response(200, json={"_embedded": {"items": items}})
        if offset == 100:
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "items": [
                            {
                                "name": "TARGET.HEIC",
                                "path": "/teeon/TARGET.HEIC",
                                "type": "file",
                                "file": "https://dl.example/target",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    assert client.get_public_download_url("pk", "/teeon/TARGET.HEIC") == "https://dl.example/target"


def test_find_and_download_for_file_at_root() -> None:
    # Файл прямо в корне публичного ресурса (parent пустой) — тоже должен находиться.
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/public/resources/download"):
            return httpx.Response(404, json={"message": "not found"})
        path = request.url.params.get("path")
        if path in (None, "/", ""):
            return httpx.Response(
                200,
                json={
                    "_embedded": {
                        "items": [
                            {
                                "name": "ROOT.HEIC",
                                "path": "/ROOT.HEIC",
                                "type": "file",
                                "file": "https://dl.example/root",
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"_embedded": {"items": []}})

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    resource = client.find_public_resource_by_path("pk", "/ROOT.HEIC")
    assert resource.name == "ROOT.HEIC"
    assert client.get_public_download_url("pk", "/ROOT.HEIC") == "https://dl.example/root"


# --- Пагинация больших папок и обработка таймаутов ---


def _paginated_files_handler(total: int) -> Callable[[httpx.Request], httpx.Response]:
    """Хэндлер /public/resources, отдающий `total` файлов страницами (limit/offset)."""

    def handler(request: httpx.Request) -> httpx.Response:
        limit = int(request.url.params.get("limit", "100"))
        offset = int(request.url.params.get("offset", "0"))
        items = [
            {
                "name": f"f{i}.jpg",
                "path": f"/big/f{i}.jpg",
                "type": "file",
                "media_type": "image",
            }
            for i in range(offset, min(offset + limit, total))
        ]
        return httpx.Response(200, json={"_embedded": {"items": items}})

    return handler


def test_list_all_single_page() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(30))
    )
    items = client.list_all_public_resources("pk", "/big")
    assert len(items) == 30


def test_list_all_two_pages_preserves_order() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(150))
    )
    items = client.list_all_public_resources("pk", "/big", page_size=100)
    assert len(items) == 150
    assert [r.name for r in items[:3]] == ["f0.jpg", "f1.jpg", "f2.jpg"]


def test_list_all_empty_folder() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(0))
    )
    assert client.list_all_public_resources("pk", "/big") == []


def test_list_all_respects_max_pages() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(1000))
    )
    items = client.list_all_public_resources("pk", "/big", page_size=10, max_pages=3)
    assert len(items) == 30  # 3 страницы по 10, цикл ограничен max_pages


def test_list_all_validates_arguments() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(1))
    )
    with pytest.raises(ValueError):
        client.list_all_public_resources("pk", "/big", page_size=0)
    with pytest.raises(ValueError):
        client.list_all_public_resources("pk", "/big", max_pages=0)


def test_recursive_listing_sees_files_on_second_page() -> None:
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(150))
    )
    files = client.list_public_files_recursive("pk", "/big", max_depth=2)
    assert len(files) == 150


def test_find_resource_sees_file_on_second_page() -> None:
    # Целевой файл f140.jpg лежит на второй странице листинга родителя.
    client = YandexDiskPublicClient(
        base_url=BASE, transport=httpx.MockTransport(_paginated_files_handler(150))
    )
    resource = client.find_public_resource_by_path("pk", "/big/f140.jpg")
    assert resource.name == "f140.jpg"


def test_network_timeout_wrapped_in_yandex_disk_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    client = YandexDiskPublicClient(base_url=BASE, transport=httpx.MockTransport(handler))
    with pytest.raises(YandexDiskError):
        client.list_public_resources("pk", "/big")
