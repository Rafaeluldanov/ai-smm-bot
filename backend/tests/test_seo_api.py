"""Тесты SEO-эндпоинтов (профиль, превью VK, контент-план, apply)."""

from fastapi.testclient import TestClient


def test_get_seo_profile(client: TestClient) -> None:
    response = client.get("/seo/project/teeon/profile")
    assert response.status_code == 200
    data = response.json()
    assert data["brand_name"] == "TEEON"
    assert data["site_url"] == "https://teeon.ru"
    assert data["contacts"]["phone"] == "+7 (495) 152-37-45"
    assert data["contacts"]["email"] == "teeon@upgifts.ru"
    assert data["seo_queries_count"] >= 60


def test_get_seo_profile_unknown_404(client: TestClient) -> None:
    assert client.get("/seo/project/no-such/profile").status_code == 404


def test_vk_group_preview_endpoint(client: TestClient) -> None:
    response = client.get("/seo/project/teeon/vk-group-preview")
    assert response.status_code == 200
    data = response.json()
    assert data["group_name"].startswith("TEEON")
    assert len(data["hashtags"]) == 17
    assert data["services"]


def test_content_plan_endpoint(client: TestClient) -> None:
    response = client.get("/seo/project/teeon/content-plan", params={"days": 30})
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 30
    assert all(item["site_url"] for item in data["items"])
    technologies = {item["technology"] for item in data["items"] if item["technology"]}
    assert {"DTF-печать", "вышивка", "гравировка", "УФ-печать"} <= technologies


def test_vk_group_apply_dry_run_default(client: TestClient) -> None:
    response = client.post("/seo/project/teeon/vk-group-apply", json={})
    assert response.status_code == 200
    data = response.json()
    assert data["dry_run"] is True
    assert data["applied"] is False


def test_vk_group_apply_live_without_flag_forbidden(client: TestClient) -> None:
    response = client.post("/seo/project/teeon/vk-group-apply", json={"dry_run": False})
    assert response.status_code == 403
