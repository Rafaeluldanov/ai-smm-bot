"""Тесты: публикация проекта использует креды подключения из БД (не глобальный .env)."""

import pytest
from sqlalchemy.orm import Session

from app.config import Settings
from app.integrations.publishing import FakePublishingClient
from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublishRequest
from app.schemas.project import ProjectCreate
from app.services import platform_connection_service as pcs_module
from app.services.platform_connection_service import (
    PlatformConnectionService,
    PlatformCredentialsMissingError,
)
from app.services.post_publication_service import PostPublicationService
from app.services.publication_platform_registry import PublicationPlatformRegistry

CONN = PlatformConnectionService()
_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _project(db: Session, slug: str = "teeon") -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug=slug)).id


def _post(db: Session, project_id: int) -> int:
    return post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id, title="Пост", telegram_text="tg", vk_text="vk", status="approved"
        ),
    ).id


def _service() -> PostPublicationService:
    registry = PublicationPlatformRegistry(
        {"telegram": FakePublishingClient("telegram"), "vk": FakePublishingClient("vk")}
    )
    return PostPublicationService(registry=registry)


def test_project_connection_is_used(db_session: Session) -> None:
    pid = _project(db_session)
    CONN.upsert_connection(
        db_session, pid, "telegram", {"api_key": _TOKEN, "external_id": "@teeon"}
    )
    creds = CONN.resolve_publish_credentials(db_session, pid, "telegram")
    assert creds.source == "project_connection"
    assert creds.token_present is True
    assert creds.external_id == "@teeon"
    assert creds.token == _TOKEN  # внутреннее использование


def test_missing_credentials_helpful_error(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    pid = _project(db_session)
    # Токен-less local: без подключения и без env-токена → missing.
    clean = Settings(_env_file=None, app_env="local")
    monkeypatch.setattr(pcs_module, "get_settings", lambda: clean)
    creds = CONN.resolve_publish_credentials(db_session, pid, "telegram")
    assert creds.source == "missing"
    assert "не подключена" in creds.message.lower()
    with pytest.raises(PlatformCredentialsMissingError):
        CONN.require_publish_credentials(db_session, pid, "telegram")


def test_token_not_in_preview(db_session: Session) -> None:
    pid = _project(db_session)
    CONN.upsert_connection(
        db_session, pid, "telegram", {"api_key": _TOKEN, "external_id": "@teeon"}
    )
    post_id = _post(db_session, pid)
    preview = _service().preview_publication(
        db_session, post_id, PostPublishRequest(platforms=["telegram"])
    )
    blob = preview.model_dump_json()
    assert _TOKEN not in blob
    item = next(i for i in preview.items if i.platform == "telegram")
    assert item.credentials_source == "project_connection"
    assert item.token_present is True


def test_public_dict_has_no_token(db_session: Session) -> None:
    pid = _project(db_session)
    CONN.upsert_connection(db_session, pid, "telegram", {"api_key": _TOKEN})
    creds = CONN.resolve_publish_credentials(db_session, pid, "telegram")
    assert _TOKEN not in str(creds.as_public_dict())
    assert "token" not in creds.as_public_dict()  # только credentials_source/token_present


def test_project_a_cannot_use_project_b_connection(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    clean = Settings(_env_file=None, app_env="local")  # без env-fallback
    monkeypatch.setattr(pcs_module, "get_settings", lambda: clean)
    pid_a = _project(db_session, "acc-a")
    pid_b = _project(db_session, "acc-b")
    CONN.upsert_connection(db_session, pid_a, "telegram", {"api_key": _TOKEN, "external_id": "@a"})
    creds_b = CONN.resolve_publish_credentials(db_session, pid_b, "telegram")
    # Проект B не получает креды/токен проекта A.
    assert creds_b.source == "missing"
    assert creds_b.token is None
    assert creds_b.token != _TOKEN


def test_env_fallback_only_local(db_session: Session, monkeypatch) -> None:  # noqa: ANN001
    pid = _project(db_session)  # без подключения проекта

    local = Settings(
        _env_file=None,
        app_env="local",
        telegram_bot_token=_TOKEN,
        telegram_default_channel_id="@envchan",
    )
    monkeypatch.setattr(pcs_module, "get_settings", lambda: local)
    creds_local = CONN.resolve_publish_credentials(db_session, pid, "telegram")
    assert creds_local.source == "env_fallback"
    assert creds_local.external_id == "@envchan"

    prod = Settings(
        _env_file=None,
        app_env="production",
        telegram_bot_token=_TOKEN,
        telegram_default_channel_id="@envchan",
    )
    monkeypatch.setattr(pcs_module, "get_settings", lambda: prod)
    creds_prod = CONN.resolve_publish_credentials(db_session, pid, "telegram")
    assert creds_prod.source == "missing"  # в production env-fallback выключен
