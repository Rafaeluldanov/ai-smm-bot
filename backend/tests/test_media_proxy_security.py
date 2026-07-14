"""Статические + поведенческие проверки безопасности media-proxy delivery (v0.6.2).

Инварианты:
- raw-токен не хранится (только token_hash); в ответах/представлениях сырого токена нет;
- IP/User-Agent не хранятся (только их хеши);
- внутренние пути (Яндекс Диск/файлы) не раскрываются в ответах;
- безопасные дефолты настроек (allow_original off, resize on);
- никаких реальных внешних запросов / изменения глобальных live-флагов.
"""

import importlib
import inspect

from PIL import Image
from sqlalchemy.orm import Session

from app.config import Settings
from app.models.media_asset import MediaAsset
from app.models.media_asset_variant import MediaAssetVariant
from app.models.public_media_link import PublicMediaLink
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.media_proxy_service import MediaProxyService

_MODULES = (
    "app.services.media_proxy_service",
    "app.repositories.media_proxy_repository",
    "app.models.media_proxy_access_log",
    "app.api.media_proxy",
    "app.scripts.media_proxy_generate",
    "app.scripts.media_proxy_check",
)


def _source(module_name: str) -> str:
    return inspect.getsource(importlib.import_module(module_name))


def test_config_defaults_safe() -> None:
    s = Settings()
    assert s.media_proxy_allow_original is False
    assert s.media_proxy_allow_original_effective is False
    assert s.media_proxy_enable_resize is True
    assert s.media_proxy_resize_enabled_effective is True
    # media-proxy не включает глобальные live-флаги.
    assert s.instagram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.telegram_live_publishing_enabled is False


def test_config_new_defaults_and_clamps() -> None:
    s = Settings()
    assert s.media_proxy_max_requests == 10000
    assert s.media_proxy_max_requests_safe == 10000
    assert s.media_proxy_cache_seconds == 86400
    assert s.media_proxy_cache_seconds_safe == 86400
    # Клампы границ.
    assert Settings(media_proxy_max_requests=-5).media_proxy_max_requests_safe == 0
    assert Settings(media_proxy_cache_seconds=10_000_000).media_proxy_cache_seconds_safe == 604800
    assert Settings(media_proxy_cache_seconds=-1).media_proxy_cache_seconds_safe == 0


def test_ip_hash_uses_pepper_when_set() -> None:
    """С MEDIA_PROXY_SECRET_KEY хеш IP/UA — HMAC (перец), не «голый» sha256 (не перебираем)."""
    import hashlib

    plain = MediaProxyService(settings=Settings())._hash_optional("1.2.3.4")
    peppered = MediaProxyService(
        settings=Settings(media_proxy_secret_key="pepper-xyz")
    )._hash_optional("1.2.3.4")
    assert plain == hashlib.sha256(b"1.2.3.4").hexdigest()
    assert peppered != plain  # перец меняет хеш → перебор по IPv4 не вскрывает значение


def test_access_log_model_has_only_hashes() -> None:
    cols = {
        c.name
        for c in __import__(
            "app.models.media_proxy_access_log", fromlist=["MediaProxyAccessLog"]
        ).MediaProxyAccessLog.__table__.columns
    }
    # Только хеши IP/UA — не сырые значения.
    assert "request_ip_hash" in cols and "user_agent_hash" in cols
    assert "request_ip" not in cols and "user_agent" not in cols and "ip" not in cols


def test_service_does_not_mutate_global_live_flags() -> None:
    src = _source("app.services.media_proxy_service").lower()
    for token in (
        "live_publishing_enabled =",
        "payments_live_enabled =",
        "instagram_live_publishing_enabled=true",
    ):
        assert token not in src, token


def test_service_stores_only_token_hash() -> None:
    src = _source("app.services.media_proxy_service")
    # Токен хешируется перед записью; token_hash кладётся в create_link.
    assert "_hash_token(token)" in src
    assert "token_hash=self._hash_token(token)" in src


def test_no_raw_token_or_path_in_serialized_views(db_session: Session, tmp_path) -> None:  # noqa: ANN001
    owner = user_repository.create_user(db_session, email="mps@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="mps", slug="mps", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="P", slug="mps"))
    project.account_id = account.id
    db_session.commit()
    asset = MediaAsset(
        project_id=project.id,
        file_name="pic.jpg",
        yandex_disk_path="public://yandex/mps/SECRET_INTERNAL_PATH.jpg",
    )
    db_session.add(asset)
    db_session.commit()
    img = tmp_path / "v.jpg"
    Image.new("RGB", (800, 600), (10, 20, 30)).save(str(img), "JPEG")
    variant = MediaAssetVariant(
        media_asset_id=asset.id,
        project_id=project.id,
        variant_type="enhanced",
        status="approved",
        output_path=str(img),
    )
    db_session.add(variant)
    db_session.commit()

    svc = MediaProxyService(
        settings=Settings(
            media_proxy_public_base_url="https://media.example.com", media_proxy_cache_enabled=False
        )
    )
    result = svc.create_media_url(db_session, project.id, asset.id, transform="width_640")
    token = result.url.rsplit("/", 1)[-1]
    delivery = svc.list_asset_delivery(db_session, project.id, asset.id)
    # Ни сырого токена, ни внутреннего пути диска, ни пути файла в безопасном представлении.
    assert token not in str(delivery)
    assert "SECRET_INTERNAL_PATH" not in str(delivery)
    assert str(img) not in str(delivery)


def test_no_path_leak_in_error_response(db_session: Session) -> None:
    """При сбое отдачи (файла нет) ошибка НЕ раскрывает внутренний путь диска/файла."""
    from app.services.media_proxy_service import MediaProxyNotAvailableError

    owner = user_repository.create_user(db_session, email="mpe@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="mpe", slug="mpe", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="P", slug="mpe"))
    project.account_id = account.id
    db_session.commit()
    # Внешний источник → скачать нельзя; путь секретный.
    asset = MediaAsset(
        project_id=project.id,
        file_name="pic.jpg",
        yandex_disk_path="external://SECRET_INTERNAL_PATH/pic.jpg",
    )
    db_session.add(asset)
    db_session.commit()
    svc = MediaProxyService(
        settings=Settings(
            media_proxy_public_base_url="https://media.example.com", media_proxy_cache_enabled=False
        )
    )
    token = svc.create_media_url(
        db_session, project.id, asset.id, transform="width_640"
    ).url.rsplit("/", 1)[-1]
    try:
        svc.get_media_response(db_session, token)
        raise AssertionError("ожидалась ошибка недоступности медиа")
    except MediaProxyNotAvailableError as exc:
        assert "SECRET_INTERNAL_PATH" not in str(exc)


def test_token_hash_not_reversible_in_db(db_session: Session) -> None:
    owner = user_repository.create_user(db_session, email="mph@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="mph", slug="mph", owner_user_id=owner.id
    )
    project = project_repository.create_project(db_session, ProjectCreate(name="P", slug="mph"))
    project.account_id = account.id
    db_session.commit()
    asset = MediaAsset(
        project_id=project.id, file_name="pic.jpg", yandex_disk_path="public://yandex/mph/pic.jpg"
    )
    db_session.add(asset)
    db_session.commit()
    svc = MediaProxyService(
        settings=Settings(media_proxy_public_base_url="https://media.example.com")
    )
    result = svc.create_media_url(db_session, project.id, asset.id, transform="width_1080")
    token = result.url.rsplit("/", 1)[-1]
    link = db_session.query(PublicMediaLink).one()
    assert token != link.token_hash and token not in link.token_hash
    assert len(link.token_hash) == 64  # sha256 hex
