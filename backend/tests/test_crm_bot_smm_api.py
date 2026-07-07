"""Тесты REST API «CRM Bot SMM Configurator»."""

import copy
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as repo
from app.repositories import media_asset_repository
from app.schemas.media_asset import MediaAssetCreate

EXAMPLE_PATH = (
    Path(__file__).resolve().parent.parent / "examples" / "crm_bot_smm_onboarding_teeon.json"
)

SECRET_LITERAL = "PASTE_IN_CRM_SECRET_FIELD"


def _example() -> dict[str, Any]:
    return copy.deepcopy(json.loads(EXAMPLE_PATH.read_text(encoding="utf-8")))


def _create_draft(client: TestClient, payload: dict[str, Any]) -> int:
    response = client.post("/crm/bot-smm/onboarding-drafts", json={"payload": payload})
    assert response.status_code == 201
    return response.json()["id"]


# --------------------------------------------------------------------------- #
# Схема формы и черновики                                                      #
# --------------------------------------------------------------------------- #


def test_form_schema_endpoint(client: TestClient) -> None:
    response = client.get("/crm/bot-smm/form-schema")
    assert response.status_code == 200
    data = response.json()
    keys = {section["key"] for section in data["sections"]}
    assert {
        "project",
        "site_or_topics",
        "resources",
        "keywords",
        "content_sources",
        "promotion_categories",
        "publishing_plan",
    } <= keys


def test_draft_validate_endpoint(client: TestClient) -> None:
    draft_id = _create_draft(client, _example())
    response = client.post(f"/crm/bot-smm/onboarding-drafts/{draft_id}/validate")
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_draft_validate_reports_errors(client: TestClient) -> None:
    payload = _example()
    payload["publishing_plans"][0]["mode"] = "auto_publish"
    draft_id = _create_draft(client, payload)
    response = client.post(f"/crm/bot-smm/onboarding-drafts/{draft_id}/validate")
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    assert any("auto_publish" in err for err in body["errors"])


# --------------------------------------------------------------------------- #
# Превью и apply                                                               #
# --------------------------------------------------------------------------- #


def test_preview_is_dry_run_and_writes_nothing(client: TestClient, db_session: Session) -> None:
    draft_id = _create_draft(client, _example())
    response = client.post(f"/crm/bot-smm/onboarding-drafts/{draft_id}/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["applied"] is False
    # Ничего не создано в БД.
    assert repo.list_configs(db_session) == []


def test_apply_dry_run_writes_nothing(client: TestClient, db_session: Session) -> None:
    draft_id = _create_draft(client, _example())
    response = client.post(
        f"/crm/bot-smm/onboarding-drafts/{draft_id}/apply", params={"dry_run": True}
    )
    assert response.status_code == 200
    assert response.json()["applied"] is False
    assert repo.list_configs(db_session) == []


def test_apply_real_creates_records_live_false(client: TestClient, db_session: Session) -> None:
    draft_id = _create_draft(client, _example())
    response = client.post(
        f"/crm/bot-smm/onboarding-drafts/{draft_id}/apply", params={"dry_run": False}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is True
    config_id = body["config_id"]
    assert config_id is not None

    resources = repo.list_resources_by_config(db_session, config_id)
    assert resources
    assert all(not r.live_enabled for r in resources)
    assert repo.list_keywords_by_config(db_session, config_id)
    categories = repo.list_categories_by_config(db_session, config_id)
    assert categories
    assert repo.list_plans_by_category(db_session, categories[0].id)

    # Секрет не утёк в ответ apply.
    assert SECRET_LITERAL not in response.text

    # Черновик помечен как applied.
    draft = client.get(f"/crm/bot-smm/onboarding-drafts/{draft_id}").json()
    assert draft["status"] == "applied"


def test_apply_invalid_payload_422(client: TestClient) -> None:
    payload = _example()
    payload["resources"] = []
    draft_id = _create_draft(client, payload)
    response = client.post(
        f"/crm/bot-smm/onboarding-drafts/{draft_id}/apply", params={"dry_run": False}
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- #
# Конфигурация проекта                                                         #
# --------------------------------------------------------------------------- #


def _apply_real(client: TestClient) -> int:
    draft_id = _create_draft(client, _example())
    body = client.post(
        f"/crm/bot-smm/onboarding-drafts/{draft_id}/apply", params={"dry_run": False}
    ).json()
    return body["config_id"]


def test_project_config_get_and_patch(client: TestClient, db_session: Session) -> None:
    config_id = _apply_real(client)
    config = repo.get_config_by_id(db_session, config_id)
    assert config is not None
    project_id = config.project_id

    response = client.get(f"/crm/bot-smm/projects/{project_id}/config")
    assert response.status_code == 200
    assert response.json()["has_website"] is True

    patched = client.patch(
        f"/crm/bot-smm/projects/{project_id}/config", json={"brand_tone": "новый тон"}
    )
    assert patched.status_code == 200
    assert patched.json()["brand_tone"] == "новый тон"


def test_project_config_404(client: TestClient) -> None:
    assert client.get("/crm/bot-smm/projects/999/config").status_code == 404


# --------------------------------------------------------------------------- #
# Тест подключения ресурса                                                     #
# --------------------------------------------------------------------------- #


def test_resource_test_connection_safe_no_secret(client: TestClient, db_session: Session) -> None:
    config_id = _apply_real(client)
    vk = next(
        r for r in repo.list_resources_by_config(db_session, config_id) if r.resource_type == "vk"
    )
    response = client.post(
        f"/crm/bot-smm/resources/{vk.id}/test-connection", json={"test_connection": True}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["performed"] is False  # сеть не вызывается
    assert body["ok"] is True
    assert body["api_key_present"] is True
    # Секрет не печатается ни в каком виде.
    assert SECRET_LITERAL not in response.text
    assert "api_key_encrypted" not in body


def test_resource_test_connection_404(client: TestClient) -> None:
    assert client.post("/crm/bot-smm/resources/999/test-connection", json={}).status_code == 404


# --------------------------------------------------------------------------- #
# Категории: контент-план и безопасные прогоны                                 #
# --------------------------------------------------------------------------- #


def test_preview_plan_endpoint(client: TestClient, db_session: Session) -> None:
    config_id = _apply_real(client)
    category = repo.list_categories_by_config(db_session, config_id)[0]
    response = client.post(
        f"/crm/bot-smm/categories/{category.id}/preview-plan", params={"days": 30}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 30
    assert all(item["site_url"] for item in data["items"])


def test_run_dry_creates_no_posts(client: TestClient, db_session: Session) -> None:
    config_id = _apply_real(client)
    category = repo.list_categories_by_config(db_session, config_id)[0]
    response = client.post(f"/crm/bot-smm/categories/{category.id}/run-dry")
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["published_publications"] == 0
    assert client.get("/posts").json() == []


def test_run_semi_auto_no_publish(client: TestClient, db_session: Session) -> None:
    config_id = _apply_real(client)
    config = repo.get_config_by_id(db_session, config_id)
    assert config is not None
    media_asset_repository.create_media_asset(
        db_session,
        MediaAssetCreate(
            project_id=config.project_id,
            file_name="m.jpg",
            yandex_disk_path="disk:/m.jpg",
            status="approved",
            tags={"products": ["футболка", "худи"], "technologies": ["dtf", "вышивка"]},
        ),
    )
    category = repo.list_categories_by_config(db_session, config_id)[0]
    response = client.post(f"/crm/bot-smm/categories/{category.id}/run-semi-auto")
    assert response.status_code == 200
    body = response.json()
    assert body["published_publications"] == 0
    # Ни одна публикация не создана (нет опубликованных постов).
    posts = client.get("/posts", params={"project_id": config.project_id}).json()
    statuses = {p["status"] for p in posts}
    assert "published" not in statuses


def test_category_endpoints_404(client: TestClient) -> None:
    assert client.post("/crm/bot-smm/categories/999/run-dry").status_code == 404
    assert client.post("/crm/bot-smm/categories/999/preview-plan").status_code == 404


# --------------------------------------------------------------------------- #
# Совместимость                                                                #
# --------------------------------------------------------------------------- #


def test_existing_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/seo/project/teeon/profile").status_code == 200
