"""Тесты media-proxy delivery layer v0.6.2 (offline): трансформации, лимиты, журнал, соц-URL.

Инварианты:
- в БД хранится только token_hash (raw-токен не хранится);
- истёкший/невалидный токен блокируется; лимит запросов enforced;
- resize работает; оригинал не отдаётся при ALLOW_ORIGINAL=false;
- URL/социальные ссылки/preview генерируются; tenant-изоляция;
- журнал обращений хранит только хеши IP/UA (не сами IP/UA); без секретов;
- интеграция подготовки в PostPublicationService НЕ публикует.
"""

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.security import make_dev_token
from app.models.media_asset import MediaAsset
from app.models.media_asset_variant import MediaAssetVariant
from app.models.media_proxy_access_log import MediaProxyAccessLog
from app.models.public_media_link import PublicMediaLink
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.media_proxy_service import (
    MediaProxyError,
    MediaProxyNotAvailableError,
    MediaProxyService,
)


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "media_proxy_public_base_url": "https://media.example.com",
        "media_proxy_cache_enabled": False,
    }
    base.update(kw)
    return Settings(**base)


def _seed(db: Session, slug: str, tmp_path=None):  # noqa: ANN001, ANN202
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name="P", slug=slug))
    project.account_id = account.id
    db.commit()
    asset = MediaAsset(
        project_id=project.id,
        file_name="pic.jpg",
        yandex_disk_path=f"public://yandex/{slug}/pic.jpg",
    )
    db.add(asset)
    db.commit()
    if tmp_path is not None:
        img_path = tmp_path / f"{slug}.jpg"
        Image.new("RGB", (2000, 1500), (100, 50, 25)).save(str(img_path), "JPEG")
        variant = MediaAssetVariant(
            media_asset_id=asset.id,
            project_id=project.id,
            variant_type="enhanced",
            status="approved",
            output_path=str(img_path),
        )
        db.add(variant)
        db.commit()
    return account, project, asset, owner


def _token(url: str) -> str:
    return url.rsplit("/", 1)[-1]


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


# --- Service --------------------------------------------------------------- #


def test_create_media_url_stores_only_hash(db_session: Session) -> None:
    _a, project, asset, _o = _seed(db_session, "mpd-hash")
    svc = MediaProxyService(settings=_settings())
    result = svc.create_media_url(db_session, project.id, asset.id, transform="width_1080")
    token = _token(result.url)
    link = db_session.query(PublicMediaLink).one()
    assert link.token_hash and token not in link.token_hash  # хранится хеш, не сам токен
    assert link.transform == "width_1080"
    db_session.refresh(asset)
    assert asset.proxy_ready is True and asset.last_proxy_generated_at is not None


def test_social_and_preview_urls(db_session: Session) -> None:
    _a, project, asset, _o = _seed(db_session, "mpd-social")
    svc = MediaProxyService(settings=_settings())
    ig = svc.build_social_media_url(db_session, project.id, asset.id, "instagram")
    tg = svc.build_social_media_url(db_session, project.id, asset.id, "telegram")
    assert ig.transform == "width_1080"
    assert tg.transform == "width_1080"  # original→1080 при allow_original=false
    assert svc.generate_preview_url(db_session, project.id, asset.id).transform == "social_preview"
    urls = svc.build_platform_urls(db_session, project.id, asset.id)
    assert set(urls["urls"]) == {"preview", "instagram", "vk", "telegram"}


def test_original_offered_only_when_allowed(db_session: Session) -> None:
    _a, project, asset, _o = _seed(db_session, "mpd-orig")
    off = MediaProxyService(settings=_settings()).build_platform_urls(
        db_session, project.id, asset.id
    )
    assert "original" not in off["urls"]
    on = MediaProxyService(settings=_settings(media_proxy_allow_original=True))
    assert "original" in on.build_platform_urls(db_session, project.id, asset.id)["urls"]


def test_tenant_isolation(db_session: Session) -> None:
    _a, project_a, _asset_a, _o = _seed(db_session, "mpd-ta")
    _b, _project_b, asset_b, _o2 = _seed(db_session, "mpd-tb")
    svc = MediaProxyService(settings=_settings())
    with pytest.raises(MediaProxyError):
        svc.create_media_url(db_session, project_a.id, asset_b.id, transform="width_640")


def test_validate_token_states(db_session: Session) -> None:
    _a, project, asset, _o = _seed(db_session, "mpd-validate")
    svc = MediaProxyService(settings=_settings())
    token = _token(
        svc.create_media_url(db_session, project.id, asset.id, transform="width_640").url
    )
    assert svc.validate_token(db_session, token)["valid"] is True
    assert svc.validate_token(db_session, "garbage")["valid"] is False
    link = db_session.query(PublicMediaLink).one()
    link.expires_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()
    v = svc.validate_token(db_session, token)
    assert v["valid"] is False and v["blocker"] == "expired_token" and v["status"] == 410


def test_resize_and_access_log_hashes_only(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    _a, project, asset, _o = _seed(db_session, "mpd-resize", tmp_path)
    svc = MediaProxyService(settings=_settings())
    result = svc.create_media_url(db_session, project.id, asset.id, transform="width_640")
    resolved = svc.get_media_response(
        db_session, _token(result.url), request_ip="1.2.3.4", user_agent="Mozilla"
    )
    assert Image.open(BytesIO(resolved.content)).size[0] == 640
    log = db_session.query(MediaProxyAccessLog).one()
    assert log.status == 200
    assert log.request_ip_hash and log.request_ip_hash != "1.2.3.4"
    assert log.user_agent_hash and log.user_agent_hash != "Mozilla"  # UA-хеш реально записан
    assert "1.2.3.4" not in str(log.__dict__) and "Mozilla" not in str(log.__dict__)


def test_all_transforms_geometry(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    """Каждая трансформация даёт корректную геометрию (источник 2000x1500)."""
    _a, project, asset, _o = _seed(db_session, "mpd-geom", tmp_path)
    svc = MediaProxyService(settings=_settings())
    cases = {
        "width_1080": lambda w, h: w == 1080,
        "width_640": lambda w, h: w == 640,
        "square": lambda w, h: w == h,
        "social_preview": lambda w, h: w == h and w <= 1080,
    }
    for transform, check in cases.items():
        result = svc.create_media_url(db_session, project.id, asset.id, transform=transform)
        served = svc.get_media_response(db_session, _token(result.url))
        w, h = Image.open(BytesIO(served.content)).size
        assert check(w, h), f"{transform}: {w}x{h}"


def test_transform_cache_hit_serves_identical_bytes(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    """С включённым кешем повторная отдача той же трансформы даёт идентичные байты + файл кеша."""
    _a, project, asset, _o = _seed(db_session, "mpd-cache", tmp_path)
    cache_dir = tmp_path / "cache"
    svc = MediaProxyService(
        settings=_settings(media_proxy_cache_enabled=True, media_proxy_cache_dir=str(cache_dir))
    )
    result = svc.create_media_url(db_session, project.id, asset.id, transform="width_640")
    token = _token(result.url)
    first = svc.get_media_response(db_session, token).content
    second = svc.get_media_response(db_session, token).content
    assert first == second and Image.open(BytesIO(first)).size[0] == 640
    # Кеш реально создал файл (ключ по исходным байтам) — значит кеш живой.
    assert cache_dir.is_dir() and any(cache_dir.iterdir())


def test_original_blocked_and_logged(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    _a, project, asset, _o = _seed(db_session, "mpd-noorig", tmp_path)
    svc = MediaProxyService(settings=_settings())
    result = svc.create_media_url(db_session, project.id, asset.id, transform="original")
    with pytest.raises(MediaProxyNotAvailableError) as exc:
        svc.get_media_response(db_session, _token(result.url), request_ip="9.9.9.9")
    assert exc.value.status == 403 and exc.value.blocker == "original_not_allowed"
    assert db_session.query(MediaProxyAccessLog).one().status == 403


def test_request_limit_enforced(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    _a, project, asset, _o = _seed(db_session, "mpd-limit", tmp_path)
    svc = MediaProxyService(settings=_settings())
    token = _token(
        svc.create_media_url(
            db_session, project.id, asset.id, transform="width_640", max_requests=1
        ).url
    )
    svc.get_media_response(db_session, token)
    with pytest.raises(MediaProxyNotAvailableError) as exc:
        svc.get_media_response(db_session, token)
    assert exc.value.status == 403 and exc.value.blocker == "request_limit_reached"


def test_prepare_media_delivery_no_publish(db_session: Session) -> None:
    """PostPublicationService.prepare_media_delivery готовит URL, но НЕ публикует."""
    from app.models.post import Post
    from app.repositories import post_repository
    from app.schemas.post import PostCreate
    from app.services.post_publication_service import PostPublicationService
    from app.services.publication_platform_registry import PublicationPlatformRegistry

    _a, project, asset, _o = _seed(db_session, "mpd-prepare")
    post = post_repository.create_post(
        db_session, PostCreate(project_id=project.id, title="t", body_text="b")
    )
    post.media_asset_id = asset.id
    db_session.commit()
    svc = PostPublicationService(
        registry=PublicationPlatformRegistry({}),
        media_proxy_service=MediaProxyService(settings=_settings()),
    )
    url = svc.prepare_media_delivery(db_session, post, "instagram")
    assert url and url.startswith("https://media.example.com/media/")
    # Никаких публикаций — только подготовка ссылки (создан токен), но НЕ строка публикации.
    assert db_session.query(PublicMediaLink).count() == 1
    assert isinstance(post, Post)
    assert post_repository.get_post_by_id(db_session, post.id).status != "published"
    from app.repositories import post_publication_repository

    assert (
        post_publication_repository.get_publication_by_post_and_platform(
            db_session, post.id, "instagram"
        )
        is None
    )


# --- API ------------------------------------------------------------------- #


def test_api_generate_and_serve(client: TestClient, db_session: Session, tmp_path) -> None:  # noqa: ANN001
    from app.services.media_proxy_service import get_media_proxy_service as _get_mp

    _a, project, asset, owner = _seed(db_session, "mpd-apiserve", tmp_path)
    # Внедряем сервис с корректным base URL + без кеша.
    client.app.dependency_overrides[_get_mp] = lambda: MediaProxyService(settings=_settings())
    try:
        r = client.post(
            f"/media-proxy/projects/{project.id}/assets/{asset.id}/generate",
            headers=_h(owner.id),
            json={"transform": "width_640"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["transform"] == "width_640"
        token = _token(body["url"])
        served = client.get(f"/media/{token}")
        assert served.status_code == 200
        assert served.headers["content-type"].startswith("image/")
        # Трансформа реально применена: источник 2000x1500 → отдано 640 по ширине.
        assert Image.open(BytesIO(served.content)).size[0] == 640
        # Cache-Control приватный (не public) — отзыв не обходится shared-кешами.
        assert "public" not in served.headers.get("cache-control", "").lower()
        assert (
            "X-Content-Type-Options" in served.headers or "x-content-type-options" in served.headers
        )
    finally:
        client.app.dependency_overrides.pop(_get_mp, None)


def test_api_platform_urls_and_delete_token(client: TestClient, db_session: Session) -> None:
    from app.services.media_proxy_service import get_media_proxy_service as _get_mp

    _a, project, asset, owner = _seed(db_session, "mpd-apitok")
    client.app.dependency_overrides[_get_mp] = lambda: MediaProxyService(settings=_settings())
    try:
        r = client.post(
            f"/media-proxy/projects/{project.id}/assets/{asset.id}/platform-urls",
            headers=_h(owner.id),
        )
        assert r.status_code == 200
        link_id = r.json()["urls"]["instagram"]["link_id"]
        # Отключить токен по id (под гардом).
        d = client.delete(f"/media-proxy/tokens/{link_id}", headers=_h(owner.id))
        assert d.status_code == 200 and d.json()["disabled"] is True
    finally:
        client.app.dependency_overrides.pop(_get_mp, None)


def test_api_delete_token_cross_tenant_404(client: TestClient, db_session: Session) -> None:
    from app.services.media_proxy_service import get_media_proxy_service as _get_mp

    _a, project_a, asset_a, owner_a = _seed(db_session, "mpd-xa")
    _b, _project_b, _asset_b, owner_b = _seed(db_session, "mpd-xb")
    client.app.dependency_overrides[_get_mp] = lambda: MediaProxyService(settings=_settings())
    try:
        link_id = client.post(
            f"/media-proxy/projects/{project_a.id}/assets/{asset_a.id}/generate",
            headers=_h(owner_a.id),
            json={"transform": "width_640"},
        ).json()["id"]
        # Владелец B не может отключить токен проекта A.
        d = client.delete(f"/media-proxy/tokens/{link_id}", headers=_h(owner_b.id))
        assert d.status_code == 404
    finally:
        client.app.dependency_overrides.pop(_get_mp, None)
