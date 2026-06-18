"""Тесты REST API проектов."""

from fastapi.testclient import TestClient


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {"name": "TEEON", "slug": "teeon"}
    payload.update(overrides)
    response = client.post("/projects", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_create_project(client: TestClient) -> None:
    body = _create(client, website_url="https://teeon.ru")
    assert body["slug"] == "teeon"
    assert body["name"] == "TEEON"
    assert body["is_active"] is True
    assert isinstance(body["id"], int)
    assert body["created_at"] is not None


def test_create_duplicate_slug_conflict(client: TestClient) -> None:
    _create(client)
    response = client.post("/projects", json={"name": "Other", "slug": "teeon"})
    assert response.status_code == 409


def test_create_invalid_slug_422(client: TestClient) -> None:
    response = client.post("/projects", json={"name": "Bad", "slug": "не валидный slug"})
    assert response.status_code == 422


def test_get_by_id(client: TestClient) -> None:
    created = _create(client)
    response = client.get(f"/projects/{created['id']}")
    assert response.status_code == 200
    assert response.json()["id"] == created["id"]


def test_get_by_id_404(client: TestClient) -> None:
    response = client.get("/projects/999999")
    assert response.status_code == 404


def test_get_by_slug(client: TestClient) -> None:
    _create(client)
    response = client.get("/projects/slug/teeon")
    assert response.status_code == 200
    assert response.json()["slug"] == "teeon"


def test_get_by_slug_404(client: TestClient) -> None:
    response = client.get("/projects/slug/nope")
    assert response.status_code == 404


def test_list_projects(client: TestClient) -> None:
    _create(client, name="A", slug="aaa")
    _create(client, name="B", slug="bbb")
    response = client.get("/projects")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_list_active_only_filter(client: TestClient) -> None:
    first = _create(client, slug="keep")
    second = _create(client, slug="drop")
    client.post(f"/projects/{second['id']}/deactivate")

    active = client.get("/projects", params={"active_only": "true"}).json()
    all_items = client.get("/projects", params={"active_only": "false"}).json()

    active_slugs = {p["slug"] for p in active}
    all_slugs = {p["slug"] for p in all_items}
    assert active_slugs == {"keep"}
    assert all_slugs == {"keep", "drop"}
    assert first["slug"] == "keep"


def test_patch_partial(client: TestClient) -> None:
    created = _create(client)
    response = client.patch(
        f"/projects/{created['id']}", json={"description": "обновлённое описание"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["description"] == "обновлённое описание"
    assert body["slug"] == "teeon"  # не изменился


def test_patch_slug_conflict(client: TestClient) -> None:
    _create(client, slug="first")
    second = _create(client, slug="second")
    response = client.patch(f"/projects/{second['id']}", json={"slug": "first"})
    assert response.status_code == 409


def test_patch_404(client: TestClient) -> None:
    response = client.patch("/projects/999999", json={"name": "X"})
    assert response.status_code == 404


def test_deactivate(client: TestClient) -> None:
    created = _create(client)
    response = client.post(f"/projects/{created['id']}/deactivate")
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_deactivate_404(client: TestClient) -> None:
    response = client.post("/projects/999999/deactivate")
    assert response.status_code == 404
