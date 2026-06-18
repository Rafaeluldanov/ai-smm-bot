"""Тесты REST API автономных прогонов."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import post_repository
from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def test_dry_run_creates_no_posts(client: TestClient, db_session: Session) -> None:
    project_id = _project(db_session)
    response = client.post("/autonomous-runs/dry-run", json={"project_slug": "teeon"})
    assert response.status_code == 200
    assert response.json()["run"]["mode"] == "dry_run"
    assert post_repository.list_posts(db_session, project_id=project_id) == []


def test_run_and_route_ordering(client: TestClient, db_session: Session) -> None:
    _project(db_session)
    # /run не должен перехватываться /{run_id}.
    response = client.post(
        "/autonomous-runs/run", json={"project_slug": "teeon", "mode": "semi_auto"}
    )
    assert response.status_code == 200
    assert response.json()["run"]["status"].startswith("completed")


def test_run_by_slug(client: TestClient, db_session: Session) -> None:
    _project(db_session)
    response = client.post("/autonomous-runs/run/slug/teeon", json={"mode": "semi_auto"})
    assert response.status_code == 200
    assert response.json()["run"]["mode"] == "semi_auto"


def test_invalid_mode_422(client: TestClient, db_session: Session) -> None:
    _project(db_session)
    response = client.post("/autonomous-runs/run", json={"project_slug": "teeon", "mode": "bogus"})
    assert response.status_code == 422


def test_run_missing_project_404(client: TestClient) -> None:
    response = client.post("/autonomous-runs/run", json={"project_slug": "nope"})
    assert response.status_code == 404


def test_list_get_steps_report(client: TestClient, db_session: Session) -> None:
    _project(db_session)
    run_id = client.post("/autonomous-runs/dry-run", json={"project_slug": "teeon"}).json()["run"][
        "id"
    ]

    listing = client.get("/autonomous-runs")
    assert listing.status_code == 200
    assert any(r["id"] == run_id for r in listing.json())

    detail = client.get(f"/autonomous-runs/{run_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == run_id

    steps = client.get(f"/autonomous-runs/{run_id}/steps")
    assert steps.status_code == 200
    assert len(steps.json()) == 10

    report = client.get(f"/autonomous-runs/{run_id}/report")
    assert report.status_code == 200
    assert report.json()["next_actions"]


def test_missing_run_404(client: TestClient) -> None:
    assert client.get("/autonomous-runs/99999").status_code == 404
    assert client.get("/autonomous-runs/99999/steps").status_code == 404
    assert client.get("/autonomous-runs/99999/report").status_code == 404


def test_old_endpoints_still_work(client: TestClient) -> None:
    assert client.get("/health").status_code == 200
    assert client.get("/posts").status_code == 200
    assert client.get("/external-images").status_code == 200
