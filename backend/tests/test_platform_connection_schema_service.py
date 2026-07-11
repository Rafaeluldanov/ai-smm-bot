"""Тесты схем форм подключения платформ (декларативное описание, без сети)."""

from app.services.platform_connection_schema_service import (
    PlatformConnectionSchemaService,
)

SVC = PlatformConnectionSchemaService()


def _field(schema, name):  # noqa: ANN001, ANN202
    return next((f for f in schema.fields if f.name == name), None)


def test_telegram_schema_fields() -> None:
    s = SVC.get_connection_schema("telegram")
    names = {f.name for f in s.fields}
    assert {"api_key", "external_id", "title"} <= names
    assert _field(s, "api_key").secret is True
    assert _field(s, "api_key").required is True
    assert any("getMe" in step for step in s.test_steps)
    assert s.live_supported is True


def test_vk_schema_fields() -> None:
    s = SVC.get_connection_schema("vk")
    names = {f.name for f in s.fields}
    assert {"api_key", "external_id", "app_id", "app_secret", "redirect_uri"} <= names
    assert _field(s, "app_secret").secret is True
    assert any("groups.getById" in step for step in s.test_steps)
    assert any("27" in w for w in s.warnings)


def test_instagram_schema_fields() -> None:
    s = SVC.get_connection_schema("instagram")
    names = {f.name for f in s.fields}
    assert {"api_key", "external_id"} <= names
    assert any("image_url" in w for w in s.warnings)


def test_yandex_schema_fields() -> None:
    s = SVC.get_connection_schema("yandex_disk")
    names = {f.name for f in s.fields}
    assert "url" in names and "root_folder" in names
    assert _field(s, "url").required is True


def test_website_schema_fields() -> None:
    s = SVC.get_connection_schema("website")
    assert _field(s, "url").type == "url"


def test_planned_platform_schema_disabled() -> None:
    s = SVC.get_connection_schema("tiktok")
    assert s.support_level in ("planned", "research")
    assert s.live_supported is False


def test_secret_fields_marked_secret() -> None:
    for platform in ("telegram", "vk", "instagram"):
        s = SVC.get_connection_schema(platform)
        for f in s.fields:
            if f.name in ("api_key", "app_secret"):
                assert f.secret is True and f.masked is True
            if not f.secret:
                assert f.name not in ("api_key", "app_secret")


def test_schema_as_dict_serializable() -> None:
    data = SVC.get_connection_schema("telegram").as_dict()
    assert data["platform_key"] == "telegram"
    assert isinstance(data["fields"], list)
    assert data["fields"][0]["name"]
