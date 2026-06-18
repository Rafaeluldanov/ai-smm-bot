"""Тесты репозитория внешних изображений-кандидатов."""

import pytest
from sqlalchemy.orm import Session

from app.repositories import external_image_repository as repo
from app.repositories.external_image_repository import (
    ExternalImageCandidateNotFoundError,
    InvalidExternalImageReviewStatusError,
)
from app.repositories.project_repository import create_project
from app.schemas.external_image import ExternalImageCandidateCreate
from app.schemas.project import ProjectCreate


def _project(db: Session) -> int:
    return create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id


def _data(
    project_id: int, source_url: str = "https://x/1", review_status: str = "needs_review"
) -> ExternalImageCandidateCreate:
    return ExternalImageCandidateCreate(
        project_id=project_id,
        query="шелкография",
        provider="fake",
        source_url=source_url,
        license_name="CC0",
        commercial_use_allowed=True,
        safe_for_business=True,
        review_status=review_status,
    )


def test_create_and_get(db_session: Session) -> None:
    project_id = _project(db_session)
    created = repo.create_candidate(db_session, _data(project_id))
    assert repo.get_candidate_by_id(db_session, created.id) is not None
    found = repo.get_candidate_by_provider_source(db_session, "fake", "https://x/1")
    assert found is not None
    assert found.id == created.id


def test_upsert_no_duplicate(db_session: Session) -> None:
    project_id = _project(db_session)
    c1, a1 = repo.upsert_candidate(db_session, _data(project_id))
    c2, a2 = repo.upsert_candidate(db_session, _data(project_id))
    assert a1 == "created"
    assert a2 in {"updated", "unchanged"}
    assert c1.id == c2.id
    assert len(repo.list_candidates(db_session, project_id=project_id)) == 1


def test_upsert_keeps_protected_status(db_session: Session) -> None:
    project_id = _project(db_session)
    candidate, _ = repo.upsert_candidate(db_session, _data(project_id))
    repo.mark_review_status(db_session, candidate.id, "approved")
    again, _ = repo.upsert_candidate(db_session, _data(project_id, review_status="rejected"))
    assert again.review_status == "approved"


def test_list_filters(db_session: Session) -> None:
    project_id = _project(db_session)
    repo.create_candidate(db_session, _data(project_id, source_url="u1", review_status="approved"))
    repo.create_candidate(db_session, _data(project_id, source_url="u2", review_status="rejected"))
    assert len(repo.list_candidates(db_session, provider="fake")) == 2
    assert len(repo.list_candidates(db_session, review_status="approved")) == 1
    assert len(repo.list_candidates(db_session, review_status="rejected")) == 1


def test_mark_review_status_errors(db_session: Session) -> None:
    project_id = _project(db_session)
    candidate = repo.create_candidate(db_session, _data(project_id))
    updated = repo.mark_review_status(db_session, candidate.id, "approved", reviewed_by="Stanislav")
    assert updated.review_status == "approved"
    assert updated.reviewed_by == "Stanislav"
    with pytest.raises(InvalidExternalImageReviewStatusError):
        repo.mark_review_status(db_session, candidate.id, "bogus")
    with pytest.raises(ExternalImageCandidateNotFoundError):
        repo.mark_review_status(db_session, 99999, "approved")
