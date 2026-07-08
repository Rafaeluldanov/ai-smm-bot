"""Тесты SaaS/auth/billing REST API (offline, TestClient, без сети)."""

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as crm_repo


def _register(client: TestClient, email: str, account_name: str = "WS") -> dict[str, Any]:
    response = client.post(
        "/auth/register",
        json={
            "email": email,
            "password": "password123",
            "full_name": "U",
            "account_name": account_name,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _saas_payload(account_id: int, project_slug: str = "teeon-saas") -> dict[str, Any]:
    return {
        "account_id": account_id,
        "payload": {
            "company": {
                "company_name": "TEEON",
                "has_website": True,
                "website_url": "https://teeon.ru",
            },
            "project": {"project_slug": project_slug, "project_name": "TEEON"},
            "keywords": [{"query": "футболки с логотипом", "product": "футболка"}],
            "media_sources": [
                {"source_type": "yandex_disk", "title": "Диск", "url": "https://disk.yandex.ru/x"}
            ],
            "platforms": [
                {
                    "platform_type": "telegram",
                    "title": "TG",
                    "external_id": "@teeon",
                    "api_key": "SECRET_TOKEN",
                }
            ],
            "promotion_categories": [
                {
                    "title": "Футболки",
                    "keyword_queries": ["футболки с логотипом"],
                    "product_priorities": {"футболка": 5},
                }
            ],
            "publishing_plans": [
                {"category_title": "Футболки", "platforms": ["telegram"], "mode": "semi_auto"}
            ],
            "billing": {"starting_topup_amount": 100, "accept_terms": True},
        },
    }


# --------------------------------------------------------------------------- #
# Auth                                                                        #
# --------------------------------------------------------------------------- #


def test_register_login_me(client: TestClient) -> None:
    body = _register(client, "api@example.com")
    token = body["token"]
    assert body["user"]["email"] == "api@example.com"
    assert "password" not in body["user"]
    assert len(body["accounts"]) == 1

    login = client.post("/auth/login", json={"email": "api@example.com", "password": "password123"})
    assert login.status_code == 200

    me = client.get("/auth/me", headers={"Authorization": token})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "api@example.com"

    assert client.get("/auth/me").status_code == 401


def test_duplicate_register_conflict(client: TestClient) -> None:
    _register(client, "dup@example.com")
    dup = client.post(
        "/auth/register", json={"email": "dup@example.com", "password": "password123"}
    )
    assert dup.status_code == 409


def test_login_wrong_password_401(client: TestClient) -> None:
    _register(client, "wrong@example.com")
    resp = client.post("/auth/login", json={"email": "wrong@example.com", "password": "nope-nope"})
    assert resp.status_code == 401


# --------------------------------------------------------------------------- #
# SaaS onboarding + dashboard                                                 #
# --------------------------------------------------------------------------- #


def test_onboarding_preview_apply_dashboard(client: TestClient) -> None:
    account_id = _register(client, "own@example.com")["accounts"][0]["id"]
    payload = _saas_payload(account_id)

    assert client.get("/saas/onboarding/form-schema").status_code == 200

    preview = client.post("/saas/onboarding/preview", json=payload)
    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True

    applied = client.post("/saas/onboarding/apply", json=payload)
    assert applied.status_code == 200
    project_id = applied.json()["project_id"]
    assert project_id is not None
    # Секрет платформы не возвращается в ответе.
    assert "SECRET_TOKEN" not in applied.text

    projects = client.get(f"/saas/accounts/{account_id}/projects")
    assert projects.status_code == 200
    assert len(projects.json()) == 1

    dashboard = client.get(f"/saas/projects/{project_id}/dashboard")
    assert dashboard.status_code == 200
    body = dashboard.json()
    assert body["platforms_count"] == 1
    assert body["billing_balance_units"] == 100


def test_saas_run_dry_and_semi_auto_402(client: TestClient, db_session: Session) -> None:
    account_id = _register(client, "runapi@example.com")["accounts"][0]["id"]
    payload = _saas_payload(account_id, project_slug="run-api")
    payload["payload"]["billing"]["starting_topup_amount"] = 0  # без баланса
    applied = client.post("/saas/onboarding/apply", json=payload)
    project_id = applied.json()["project_id"]

    config = crm_repo.get_config_by_project_id(db_session, project_id)
    assert config is not None
    category_id = crm_repo.list_categories_by_config(db_session, config.id)[0].id
    run_body = {"account_id": account_id, "category_id": category_id}

    # Dry-run — только оценка (200), без списания.
    dry = client.post(f"/saas/projects/{project_id}/run-dry", json=run_body)
    assert dry.status_code == 200
    assert dry.json()["debited_units"] == 0
    assert dry.json()["estimated_units"] > 0

    # Semi-auto без баланса — 402 (действие не выполняется).
    semi = client.post(f"/saas/projects/{project_id}/run-semi-auto", json=run_body)
    assert semi.status_code == 402


def test_onboarding_invalid_payload_422(client: TestClient) -> None:
    account_id = _register(client, "bad@example.com")["accounts"][0]["id"]
    payload = _saas_payload(account_id)
    payload["payload"]["platforms"] = []  # без ресурсов CRM-валидация не проходит
    resp = client.post("/saas/onboarding/apply", json=payload)
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# Billing                                                                     #
# --------------------------------------------------------------------------- #


def test_billing_balance_topup_estimate(client: TestClient) -> None:
    account_id = _register(client, "bill@example.com")["accounts"][0]["id"]

    balance = client.get(f"/billing/account/{account_id}/balance")
    assert balance.status_code == 200
    assert balance.json()["balance_units"] == 0

    topup = client.post(f"/billing/account/{account_id}/manual-topup", json={"amount_units": 500})
    assert topup.status_code == 200
    assert topup.json()["balance_after_units"] == 500

    assert client.get(f"/billing/account/{account_id}/balance").json()["balance_units"] == 500

    ledger = client.get(f"/billing/account/{account_id}/ledger")
    assert ledger.status_code == 200
    assert len(ledger.json()) == 1

    estimate = client.post(
        "/billing/estimate", json={"action_type": "ai_generation", "account_id": account_id}
    )
    assert estimate.status_code == 200
    assert estimate.json()["estimated_units"] == 10
    assert estimate.json()["affordable"] is True


def test_billing_topup_idempotent(client: TestClient) -> None:
    account_id = _register(client, "idem@example.com")["accounts"][0]["id"]
    body = {"amount_units": 100, "idempotency_key": "k-1"}
    client.post(f"/billing/account/{account_id}/manual-topup", json=body)
    client.post(f"/billing/account/{account_id}/manual-topup", json=body)
    assert client.get(f"/billing/account/{account_id}/balance").json()["balance_units"] == 100


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/crm/bot-smm/form-schema").status_code == 200
    assert client.get("/post-publications/platform-capabilities").status_code == 200
