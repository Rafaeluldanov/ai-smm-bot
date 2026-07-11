"""Тесты автоматических логов подключений платформ (audit → API логов, без секретов)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _project(db: Session) -> int:
    pid = create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id
    db.commit()
    return pid


def _base(pid: int) -> str:
    return f"/projects/{pid}/platform-connections/telegram"


def test_connection_update_creates_log(client: TestClient, db_session: Session) -> None:
    pid = _project(db_session)
    client.post(_base(pid), json={"api_key": _TOKEN, "external_id": "@teeon"})
    logs = client.get(_base(pid) + "/logs").json()
    actions = {row["action"] for row in logs}
    assert "platform.connection.created" in actions
    assert "platform.connection.secret.updated" in actions


def test_check_creates_log(client: TestClient, db_session: Session) -> None:
    pid = _project(db_session)
    client.post(_base(pid), json={"api_key": _TOKEN, "external_id": "@teeon"})
    client.post(_base(pid) + "/check")
    logs = client.get(_base(pid) + "/logs").json()
    assert any(row["action"].startswith("platform.connection.check") for row in logs)


def test_logs_sanitized_no_secret(client: TestClient, db_session: Session) -> None:
    pid = _project(db_session)
    client.post(_base(pid), json={"api_key": _TOKEN, "external_id": "@teeon"})
    client.post(_base(pid) + "/check")
    raw = client.get(_base(pid) + "/logs").text
    assert _TOKEN not in raw
    assert "api_key_encrypted" not in raw


def test_logs_have_action_and_time(client: TestClient, db_session: Session) -> None:
    pid = _project(db_session)
    client.post(_base(pid), json={"api_key": _TOKEN})
    logs = client.get(_base(pid) + "/logs").json()
    assert logs
    for row in logs:
        assert row["action"]
        assert "created_at" in row


def test_workspace_renders_logs_container(client: TestClient) -> None:
    body = client.get("/ui/projects/1/platforms/telegram").text
    assert "conn-logs" in body
    assert "connLogs" in body
