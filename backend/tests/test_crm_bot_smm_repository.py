"""Тесты репозитория «БОТ СММ»: обработка секрета и CRUD-хелперы."""

from sqlalchemy.orm import Session

from app.repositories import crm_bot_smm_repository as repo
from app.repositories.project_repository import create_project
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmSmmResourceCreate,
    CrmSmmResourceRead,
)
from app.schemas.project import ProjectCreate


def _config(db: Session) -> tuple[int, int]:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    config = repo.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name="TEEON")
    )
    return project.id, config.id


def test_resource_secret_encoded_and_not_leaked(db_session: Session) -> None:
    project_id, config_id = _config(db_session)
    secret = "vk-token-abcdef123456"
    resource = repo.create_resource(
        db_session,
        CrmSmmResourceCreate(
            project_id=project_id,
            config_id=config_id,
            resource_type="vk",
            title="VK",
            api_key=secret,
            external_id="240102732",
        ),
    )
    # Секрет закодирован и не хранится как есть.
    assert resource.api_key_encrypted is not None
    assert secret not in resource.api_key_encrypted
    assert resource.api_key_masked is not None
    assert secret not in resource.api_key_masked

    # Read-схема не содержит секрета, только факт и маску.
    read = CrmSmmResourceRead.from_model(resource)
    dumped = read.model_dump()
    assert "api_key_encrypted" not in dumped
    assert "api_key" not in dumped
    assert dumped["api_key_present"] is True
    assert dumped["api_key_masked"] == resource.api_key_masked
    assert secret not in read.model_dump_json()


def test_resource_without_secret(db_session: Session) -> None:
    project_id, config_id = _config(db_session)
    resource = repo.create_resource(
        db_session,
        CrmSmmResourceCreate(
            project_id=project_id,
            config_id=config_id,
            resource_type="website",
            title="Сайт",
            url="https://teeon.ru",
        ),
    )
    assert resource.api_key_encrypted is None
    read = CrmSmmResourceRead.from_model(resource)
    assert read.api_key_present is False
    assert read.api_key_masked is None


def test_config_lookup_helpers(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    config = repo.create_config(
        db_session,
        CrmBotProjectConfigCreate(
            project_id=project.id, display_name="TEEON", crm_external_id="crm-1"
        ),
    )
    assert repo.get_config_by_project_id(db_session, project.id).id == config.id
    assert repo.get_config_by_crm_external_id(db_session, "crm-1").id == config.id
    assert repo.get_config_by_crm_external_id(db_session, "nope") is None


def test_list_by_config_helpers(db_session: Session) -> None:
    project_id, config_id = _config(db_session)
    repo.create_resource(
        db_session,
        CrmSmmResourceCreate(
            project_id=project_id, config_id=config_id, resource_type="vk", title="VK", url="u"
        ),
    )
    assert len(repo.list_resources_by_config(db_session, config_id)) == 1
    assert repo.list_keywords_by_config(db_session, config_id) == []
    assert repo.list_categories_by_config(db_session, config_id) == []
