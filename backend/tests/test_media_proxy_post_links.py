"""Тесты создания публичных ссылок для медиа поста (offline)."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.media_proxy_service import MediaProxyService


def _svc() -> MediaProxyService:
    return MediaProxyService(
        settings=Settings(_env_file=None, app_env="local", public_app_url="https://app.teeon.ru")
    )


def _asset(db: Session, project_id: int, name: str) -> int:
    return media_asset_repository.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id, file_name=name, yandex_disk_path=f"public://yandex/SMM/{name}"
        ),
    ).id


def test_creates_links_for_post_media(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="T", slug="teeon"))
    ids = [_asset(db_session, project.id, f"a{i}.jpg") for i in range(3)]
    post = post_repository.create_post(
        db_session,
        PostCreate(
            project_id=project.id,
            title="P",
            status="approved",
            generation_notes={"media_asset_ids": ids},
        ),
    )
    results = _svc().create_public_links_for_post(db_session, post.id, purpose="instagram")
    assert len(results) == 3
    assert {r.media_asset_id for r in results} == set(ids)


def test_respects_max_items(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="T", slug="teeon"))
    ids = [_asset(db_session, project.id, f"a{i}.jpg") for i in range(5)]
    post = post_repository.create_post(
        db_session,
        PostCreate(
            project_id=project.id,
            title="P",
            status="approved",
            generation_notes={"media_asset_ids": ids},
        ),
    )
    results = _svc().create_public_links_for_post(db_session, post.id, max_items=2)
    assert len(results) == 2


def test_no_links_if_no_media(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="T", slug="teeon"))
    post = post_repository.create_post(
        db_session, PostCreate(project_id=project.id, title="P", status="approved")
    )
    assert _svc().create_public_links_for_post(db_session, post.id) == []


def test_single_media_asset_id(db_session: Session) -> None:
    project = create_project(db_session, ProjectCreate(name="T", slug="teeon"))
    aid = _asset(db_session, project.id, "solo.jpg")
    post = post_repository.create_post(
        db_session,
        PostCreate(project_id=project.id, title="P", status="approved", media_asset_id=aid),
    )
    results = _svc().create_public_links_for_post(db_session, post.id)
    assert len(results) == 1 and results[0].media_asset_id == aid


def test_post_links_api_project_isolation(client, db_session: Session) -> None:  # noqa: ANN001
    project = create_project(db_session, ProjectCreate(name="A", slug="acc-a"))
    other = create_project(db_session, ProjectCreate(name="B", slug="acc-b"))
    aid = _asset(db_session, project.id, "x.jpg")
    post = post_repository.create_post(
        db_session,
        PostCreate(project_id=project.id, title="P", status="approved", media_asset_id=aid),
    )
    db_session.commit()
    # Пост принадлежит project, а запрашиваем под other → 404.
    r = client.post(f"/media-proxy/projects/{other.id}/posts/{post.id}/public-links", json={})
    assert r.status_code == 404
