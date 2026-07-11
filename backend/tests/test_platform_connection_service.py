"""Тесты сервиса подключений платформ (шифрование, маска, tenant-изоляция, аудит)."""

from sqlalchemy.orm import Session

from app.repositories import audit_log_repository
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories.project_repository import create_project
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

SVC = PlatformConnectionService()
_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _project(db: Session, slug: str = "teeon") -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug=slug)).id


def test_create_connection_encrypts_token(db_session: Session) -> None:
    pid = _project(db_session)
    conn = SVC.upsert_connection(
        db_session, pid, "telegram", {"api_key": _TOKEN, "external_id": "@teeon", "title": "Канал"}
    )
    assert conn["api_key_present"] is True
    assert conn["api_key_masked"].endswith("2345")
    # В БД хранится шифртекст (не открытый токен).
    resource = crm_repo.get_active_resource_by_project_platform(db_session, pid, "telegram")
    assert resource.api_key_encrypted and _TOKEN not in resource.api_key_encrypted


def test_response_masks_token(db_session: Session) -> None:
    pid = _project(db_session)
    conn = SVC.upsert_connection(db_session, pid, "telegram", {"api_key": _TOKEN})
    assert _TOKEN not in str(conn)


def test_update_without_api_key_keeps_secret(db_session: Session) -> None:
    pid = _project(db_session)
    SVC.upsert_connection(
        db_session, pid, "vk", {"api_key": "vk1.SECRETTOKENVALUE123", "external_id": "111"}
    )
    first = crm_repo.get_active_resource_by_project_platform(
        db_session, pid, "vk"
    ).api_key_encrypted
    # Обновление без api_key не трогает секрет.
    conn = SVC.upsert_connection(db_session, pid, "vk", {"external_id": "222"})
    assert conn["external_id"] == "222"
    kept = crm_repo.get_active_resource_by_project_platform(db_session, pid, "vk").api_key_encrypted
    assert kept == first
    assert conn["api_key_present"] is True


def test_update_with_api_key_changes_mask(db_session: Session) -> None:
    pid = _project(db_session)
    SVC.upsert_connection(db_session, pid, "vk", {"api_key": "vk1.OLDTOKENAAAA1111"})
    conn = SVC.upsert_connection(db_session, pid, "vk", {"api_key": "vk1.NEWTOKENBBBB9999"})
    assert conn["api_key_masked"].endswith("9999")


def test_list_connections_no_secret_leak(db_session: Session) -> None:
    pid = _project(db_session)
    SVC.upsert_connection(db_session, pid, "telegram", {"api_key": _TOKEN})
    rows = SVC.list_connections(db_session, pid)
    assert len(rows) == 1
    assert _TOKEN not in str(rows)
    assert "api_key_encrypted" not in str(rows)


def test_delete_deactivates(db_session: Session) -> None:
    pid = _project(db_session)
    SVC.upsert_connection(db_session, pid, "telegram", {"api_key": _TOKEN})
    assert SVC.delete_connection(db_session, pid, "telegram") is True
    assert SVC.list_connections(db_session, pid) == []
    assert SVC.get_connection(db_session, pid, "telegram") is None


def test_audit_events_recorded(db_session: Session) -> None:
    pid = _project(db_session)
    SVC.upsert_connection(db_session, pid, "telegram", {"api_key": _TOKEN})
    SVC.check_connection(db_session, pid, "telegram")
    actions = {e.action for e in audit_log_repository.list_for_project(db_session, pid)}
    assert "platform.connection.created" in actions
    assert "platform.connection.secret.updated" in actions
    assert any(a.startswith("platform.connection.check") for a in actions)


def test_project_isolation(db_session: Session) -> None:
    pid_a = _project(db_session, "acc-a")
    pid_b = _project(db_session, "acc-b")
    SVC.upsert_connection(db_session, pid_a, "telegram", {"api_key": _TOKEN, "external_id": "@a"})
    # Проект B не видит подключение проекта A.
    assert SVC.get_connection(db_session, pid_b, "telegram") is None
    assert SVC.list_connections(db_session, pid_b) == []
