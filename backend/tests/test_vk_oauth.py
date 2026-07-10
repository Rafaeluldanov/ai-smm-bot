"""Тесты VK OAuth connect flow (offline; сеть подменяется httpx.MockTransport).

Проверяют: сборку URL авторизации, обмен code→token, подпись/валидацию state,
сохранение секрета в маске (токен не утекает), safe-check (users/groups/photos)
и безопасные ветки ошибок (error 27, отказ пользователя, нет конфигурации).
"""

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_vk_oauth_service
from app.main import app
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories.project_repository import create_project
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmSmmResourceCreate
from app.schemas.project import ProjectCreate
from app.services import crm_secret_service
from app.services.vk_oauth_service import (
    VkOAuthService,
    VkStateError,
    _normalize_group_id,
    sign_state,
    verify_state,
)

USER_TOKEN = "vk1USERtoken0987654321"  # длинный, чтобы проверить маску (tail=4321)
GROUP_ID = 240102732
REDIRECT = "https://app.teeon.ru/integrations/vk/oauth/callback"

FAKE_SETTINGS = SimpleNamespace(
    vk_app_id="APP123",
    vk_app_secret="APPSECRET",
    vk_oauth_redirect_uri=REDIRECT,
    vk_oauth_scope="wall,photos,groups,offline",
)


def _transport(
    *,
    access_token: str = USER_TOKEN,
    admin_ids: list[int] | None = None,
    photos_error: int | None = None,
    users_empty: bool = False,
    groups_error: int | None = None,
) -> httpx.MockTransport:
    admin_ids = [GROUP_ID] if admin_ids is None else admin_ids

    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        if host == "oauth.vk.com" and path == "/access_token":
            return httpx.Response(
                200, json={"access_token": access_token, "user_id": 111, "expires_in": 0}
            )
        if path == "/method/users.get":
            # Групповой токен: users.get -> response=[] (пользователь не распознан).
            users = (
                [] if users_empty else [{"id": 111, "first_name": "Иван", "last_name": "Петров"}]
            )
            return httpx.Response(200, json={"response": users})
        if path == "/method/groups.get":
            if groups_error is not None:
                return httpx.Response(
                    200, json={"error": {"error_code": groups_error, "error_msg": "x"}}
                )
            return httpx.Response(
                200, json={"response": {"count": len(admin_ids), "items": admin_ids}}
            )
        if path == "/method/photos.getWallUploadServer":
            if photos_error is not None:
                return httpx.Response(
                    200, json={"error": {"error_code": photos_error, "error_msg": "x"}}
                )
            return httpx.Response(200, json={"response": {"upload_url": "https://upload.vk/x"}})
        return httpx.Response(200, json={"error": {"error_code": 100, "error_msg": "unknown"}})

    return httpx.MockTransport(handler)


def _seed_vk_resource(db: Session, *, api_key: str | None = None, external_id: str = str(GROUP_ID)):
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    config = crm_repo.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name="TEEON")
    )
    resource = crm_repo.create_resource(
        db,
        CrmSmmResourceCreate(
            project_id=project.id,
            config_id=config.id,
            resource_type="vk",
            title="VK TEEON",
            external_id=external_id,
            api_key=api_key,
        ),
    )
    return project, resource


def _override(settings: SimpleNamespace, transport: httpx.MockTransport | None) -> None:
    app.dependency_overrides[get_vk_oauth_service] = lambda: VkOAuthService(settings, transport)


@pytest.fixture(autouse=True)
def _cleanup_overrides():
    yield
    app.dependency_overrides.pop(get_vk_oauth_service, None)


# --------------------------------------------------------------------------- #
# Юнит: state и утилиты                                                       #
# --------------------------------------------------------------------------- #


def test_sign_verify_state_roundtrip() -> None:
    data = {"a": 2, "p": 1, "r": 5, "c": "abcd"}
    assert verify_state(sign_state(data)) == data


def test_verify_state_rejects_tampered() -> None:
    state = sign_state({"a": 2, "p": 1, "r": 5, "c": "x"})
    body, _, sig = state.rpartition(".")
    tampered = f"{body}.{'0' * len(sig)}"
    with pytest.raises(VkStateError):
        verify_state(tampered)
    with pytest.raises(VkStateError):
        verify_state("garbage-no-dot")


def test_normalize_group_id() -> None:
    assert _normalize_group_id("240102732") == "240102732"
    assert _normalize_group_id("-240102732") == "240102732"
    assert _normalize_group_id("club240102732") == "240102732"
    assert _normalize_group_id(None) is None
    assert _normalize_group_id("") is None


# --------------------------------------------------------------------------- #
# start: сборка OAuth URL                                                      #
# --------------------------------------------------------------------------- #


def test_start_builds_correct_oauth_url(client: TestClient, db_session: Session) -> None:
    project, resource = _seed_vk_resource(db_session)
    _override(FAKE_SETTINGS, _transport())

    response = client.get(
        f"/integrations/vk/oauth/start?account_id=7&project_id={project.id}&resource_id={resource.id}",
        follow_redirects=False,
    )
    assert response.status_code == 307
    location = response.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "oauth.vk.com" and parsed.path == "/authorize"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["APP123"]
    assert qs["redirect_uri"] == [REDIRECT]
    assert qs["scope"] == ["wall,photos,groups,offline"]
    assert qs["response_type"] == ["code"]
    assert qs["state"]  # подписанный state присутствует
    # state валиден и несёт resource_id.
    assert verify_state(qs["state"][0])["r"] == resource.id


def test_start_not_configured_returns_400(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session)
    _override(
        SimpleNamespace(
            vk_app_id="", vk_app_secret="", vk_oauth_redirect_uri="", vk_oauth_scope=""
        ),
        None,
    )
    response = client.get(
        f"/integrations/vk/oauth/start?account_id=1&project_id=1&resource_id={resource.id}",
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "не настро" in response.text.lower()


def test_start_rejects_non_vk_resource(client: TestClient, db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="XX", slug="xx-tg"))
    config = crm_repo.create_config(
        db_session, CrmBotProjectConfigCreate(project_id=project.id, display_name="XX")
    )
    tg = crm_repo.create_resource(
        db_session,
        CrmSmmResourceCreate(
            project_id=project.id, config_id=config.id, resource_type="telegram", title="TG"
        ),
    )
    _override(FAKE_SETTINGS, _transport())
    response = client.get(
        f"/integrations/vk/oauth/start?account_id=1&project_id={project.id}&resource_id={tg.id}",
        follow_redirects=False,
    )
    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# callback: обмен кода, сохранение секрета, safe-check                         #
# --------------------------------------------------------------------------- #


def test_callback_exchanges_saves_masked_and_not_leaked(
    client: TestClient, db_session: Session
) -> None:
    project, resource = _seed_vk_resource(db_session)
    _override(FAKE_SETTINGS, _transport())
    state = sign_state({"a": 7, "p": project.id, "r": resource.id, "c": "csrf"})

    response = client.get(f"/integrations/vk/oauth/callback?code=CODE123&state={state}")
    assert response.status_code == 200
    assert "VK подключён" in response.text
    assert "Можно закрыть окно и вернуться в проект" in response.text
    # Токен НЕ утёк в HTML.
    assert USER_TOKEN not in response.text
    assert "CODE123" not in response.text

    # Секрет сохранён в маске; расшифровка совпадает с токеном (внутренняя проверка).
    db_session.expire_all()
    saved = crm_repo.get_resource_by_id(db_session, resource.id)
    assert saved is not None
    assert crm_secret_service.is_encrypted(saved.api_key_encrypted)
    assert saved.api_key_masked and saved.api_key_masked.endswith("4321")
    assert crm_secret_service.decrypt_secret(saved.api_key_encrypted) == USER_TOKEN
    # safe-check прошёл (users/groups/photos) — статусы видны на странице.
    assert "аккаунт распознан" in response.text
    assert "загрузка фото доступна" in response.text


def test_callback_rejects_tampered_state(client: TestClient, db_session: Session) -> None:
    project, resource = _seed_vk_resource(db_session)
    _override(FAKE_SETTINGS, _transport())
    state = sign_state({"a": 7, "p": project.id, "r": resource.id, "c": "csrf"})
    bad = state[:-1] + ("0" if state[-1] != "0" else "1")
    response = client.get(f"/integrations/vk/oauth/callback?code=CODE&state={bad}")
    assert response.status_code == 400
    # Токен не сохранён.
    db_session.expire_all()
    saved = crm_repo.get_resource_by_id(db_session, resource.id)
    assert saved is not None and not crm_secret_service.is_encrypted(saved.api_key_encrypted)


def test_callback_user_denied_is_safe(client: TestClient, db_session: Session) -> None:
    _override(FAKE_SETTINGS, _transport())
    response = client.get(
        "/integrations/vk/oauth/callback?error=access_denied&error_description=denied"
    )
    assert response.status_code == 400
    assert "Доступ не выдан" in response.text


def test_callback_missing_app_secret_clear_error(client: TestClient, db_session: Session) -> None:
    project, resource = _seed_vk_resource(db_session)
    # app_id + redirect есть, но VK_APP_SECRET пуст → понятная ошибка, токен не сохранён.
    no_secret = SimpleNamespace(
        vk_app_id="APP123", vk_app_secret="", vk_oauth_redirect_uri=REDIRECT, vk_oauth_scope="wall"
    )
    _override(no_secret, _transport())
    state = sign_state({"a": 7, "p": project.id, "r": resource.id, "c": "csrf"})
    response = client.get(f"/integrations/vk/oauth/callback?code=CODE&state={state}")
    assert response.status_code == 400
    assert "не настро" in response.text.lower()
    db_session.expire_all()
    saved = crm_repo.get_resource_by_id(db_session, resource.id)
    assert saved is not None and not crm_secret_service.is_encrypted(saved.api_key_encrypted)


# --------------------------------------------------------------------------- #
# status / check                                                              #
# --------------------------------------------------------------------------- #


def test_status_reflects_saved_token(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session, api_key=USER_TOKEN)
    _override(FAKE_SETTINGS, None)
    response = client.get(f"/integrations/vk/status?resource_id={resource.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["connected"] is True and body["api_key_present"] is True
    assert body["api_key_masked"] and USER_TOKEN not in response.text


def test_status_exposes_public_config(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session)
    _override(FAKE_SETTINGS, None)
    body = client.get(f"/integrations/vk/status?resource_id={resource.id}").json()
    # Публичные (не секретные) поля VK-конфига доступны UI.
    assert body["app_id"] == "APP123"
    assert body["redirect_uri"] == REDIRECT
    assert body["configured"] is True
    assert body["group_id"] == str(GROUP_ID)
    # Секрет приложения наружу не отдаётся.
    assert "APPSECRET" not in client.get(f"/integrations/vk/status?resource_id={resource.id}").text


def test_status_404_for_missing_resource(client: TestClient) -> None:
    _override(FAKE_SETTINGS, None)
    assert client.get("/integrations/vk/status?resource_id=99999").status_code == 404


def test_check_reports_all_ok(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session, api_key=USER_TOKEN)
    _override(FAKE_SETTINGS, _transport())
    response = client.post(f"/integrations/vk/oauth/check?resource_id={resource.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["user_ok"] is True
    assert body["user_name"] == "Иван Петров"
    assert body["group_visible"] is True
    assert body["photo_upload_ok"] is True
    assert USER_TOKEN not in response.text


def test_check_photos_error_27_message(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session, api_key=USER_TOKEN)
    _override(FAKE_SETTINGS, _transport(photos_error=27))
    response = client.post(f"/integrations/vk/oauth/check?resource_id={resource.id}")
    assert response.status_code == 200
    body = response.json()
    assert body["photo_upload_ok"] is False
    assert body["error_code"] == 27
    assert body["message"] == (
        "Токен не пользовательский или аккаунт не имеет прав администратора/редактора группы."
    )


def test_check_distinguishes_group_token(client: TestClient, db_session: Session) -> None:
    # Community/group token: users.get=[], groups.get error 27, photos error 27 → всё False.
    _project, resource = _seed_vk_resource(db_session, api_key=USER_TOKEN)
    _override(FAKE_SETTINGS, _transport(users_empty=True, groups_error=27, photos_error=27))
    body = client.post(f"/integrations/vk/oauth/check?resource_id={resource.id}").json()
    assert body["user_ok"] is False  # не пользовательский токен
    assert body["group_visible"] is False
    assert body["photo_upload_ok"] is False
    assert body["message"] == (
        "Токен не пользовательский или аккаунт не имеет прав администратора/редактора группы."
    )
    assert USER_TOKEN not in str(body)  # токен не утёк


def test_check_group_not_admin(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session, api_key=USER_TOKEN)
    _override(FAKE_SETTINGS, _transport(admin_ids=[111111]))  # другой group id
    response = client.post(f"/integrations/vk/oauth/check?resource_id={resource.id}")
    body = response.json()
    assert body["group_visible"] is False
    assert body["user_ok"] is True


def test_check_without_token_reports_not_connected(client: TestClient, db_session: Session) -> None:
    _project, resource = _seed_vk_resource(db_session)  # без api_key
    _override(FAKE_SETTINGS, _transport())
    response = client.post(f"/integrations/vk/oauth/check?resource_id={resource.id}")
    body = response.json()
    assert body["connected"] is False and body["api_key_present"] is False
