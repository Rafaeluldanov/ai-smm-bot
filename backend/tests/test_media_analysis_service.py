"""Тесты сервиса анализа/ретегирования медиа."""

from sqlalchemy.orm import Session

from app.repositories import media_asset_repository as repo
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_analysis_service import MediaAnalysisService
from app.services.media_status_service import MediaStatusService
from app.services.media_tagging_service import MediaTaggingService


def _service() -> MediaAnalysisService:
    return MediaAnalysisService(
        tagging_service=MediaTaggingService(),
        status_service=MediaStatusService(),
    )


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _asset(db: Session, project_id: int, file_name: str, status: str = "new") -> int:
    asset = repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{file_name}",
            status=status,
        ),
    )
    return asset.id


def test_analyze_without_save_does_not_change_tags(db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи с шелкографией.jpg")
    repo.update_media_asset_tags(db_session, repo.get_media_asset_by_id(db_session, asset_id), {})

    result = _service().analyze_media_asset(db_session, asset_id, save=False)

    assert result["saved"] is False
    assert result["tags"]["products"] == ["худи"]
    # В БД теги не изменились (остались пустыми).
    assert repo.get_media_asset_by_id(db_session, asset_id).tags == {}


def test_analyze_with_save_updates_tags(db_session: Session) -> None:
    project_id = _project(db_session)
    asset_id = _asset(db_session, project_id, "Худи с шелкографией.jpg")

    _service().analyze_media_asset(db_session, asset_id, save=True)

    tags = repo.get_media_asset_by_id(db_session, asset_id).tags
    assert tags["products"] == ["худи"]
    assert tags["technologies"] == ["шелкография"]


def test_retag_project_updates_all(db_session: Session) -> None:
    project_id = _project(db_session)
    _asset(db_session, project_id, "Футболка DTF.png")
    _asset(db_session, project_id, "Кружка с гравировкой.jpg")

    result = _service().retag_project_media(db_session, project_id)

    assert result["processed"] == 2
    assert result["updated"] == 2
    assert result["project_slug"] == "teeon"


def test_tags_summary_counts(db_session: Session) -> None:
    project_id = _project(db_session)
    a1 = _asset(db_session, project_id, "Худи с шелкографией.jpg")
    a2 = _asset(db_session, project_id, "Худи с вышивкой.jpg")
    service = _service()
    service.analyze_media_asset(db_session, a1, save=True)
    service.analyze_media_asset(db_session, a2, save=True)

    summary = service.get_tags_summary(db_session, project_id=project_id)

    assert summary["total_assets"] == 2
    assert summary["products"]["худи"] == 2
    assert summary["technologies"].get("шелкография") == 1


def test_suggest_shooting_tasks_when_lacking_approved(db_session: Session) -> None:
    project_id = _project(db_session)
    # Ни одного approved-медиа -> по целевым темам ожидаем задачи на досъёмку.
    tasks = _service().suggest_shooting_tasks(db_session, project_id)

    assert len(tasks) > 0
    task = tasks[0]
    assert task["project_slug"] == "teeon"
    assert task["tag_group"] in {"products", "technologies", "details"}
    assert "06_Нужно_переснять" in task["suggested_folder"]
    assert task["suggested_shots"]
