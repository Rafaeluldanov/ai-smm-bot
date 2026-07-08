"""Тесты CLI группировки медиа и создания поста (offline, SQLite).

Проверяют импорт, парсинг аргументов, что превью не создаёт пост, а создание
формирует пост needs_review с ``generation_notes.media_asset_ids``.
"""

import pytest
from sqlalchemy.orm import Session

from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.scripts import create_media_group_post, preview_media_groups
from app.services.media_grouping_service import MediaGroupingService


def _seed(db: Session) -> int:
    project_id = create_project(db, ProjectCreate(name="TEEON", slug="teeon")).id
    for index in range(3):
        media_asset_repository.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=project_id,
                file_name=f"tshirt_{index}.jpg",
                yandex_disk_path=f"public://yandex/teeon/teeon/tshirt_{index}.jpg",
                source_type="internal",
                license_type="company_owned",
                status="approved",
                tags={"products": ["футболка"]},
            ),
        )
    return project_id


# --------------------------------------------------------------------------- #
# Импорт и парсинг аргументов                                                  #
# --------------------------------------------------------------------------- #


def test_scripts_import() -> None:
    assert callable(preview_media_groups.main)
    assert callable(create_media_group_post.main)


def test_preview_parser() -> None:
    args = preview_media_groups.build_parser().parse_args(
        [
            "--project-slug",
            "teeon",
            "--tag",
            "футболка",
            "--max-groups",
            "10",
            "--limit-media",
            "5",
            "--include-videos",
        ]
    )
    assert args.project_slug == "teeon"
    assert args.tag == "футболка"
    assert args.max_groups == 10
    assert args.limit_media == 5
    assert args.include_videos is True


def test_create_parser() -> None:
    args = create_media_group_post.build_parser().parse_args(
        [
            "--project-slug",
            "teeon",
            "--tag",
            "футболка",
            "--limit-media",
            "5",
            "--status",
            "needs_review",
        ]
    )
    assert args.project_slug == "teeon"
    assert args.tag == "футболка"
    assert args.limit_media == 5
    assert args.status == "needs_review"


# --------------------------------------------------------------------------- #
# Превью не создаёт пост; создание создаёт needs_review                        #
# --------------------------------------------------------------------------- #


def test_preview_does_not_create_post(db_session: Session) -> None:
    _seed(db_session)
    service = MediaGroupingService()
    args = preview_media_groups.build_parser().parse_args(
        ["--project-slug", "teeon", "--tag", "футболка"]
    )

    groups = preview_media_groups.collect_groups(db_session, service, args)

    assert groups
    assert post_repository.list_posts(db_session) == []


def test_print_groups_runs(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(db_session)
    service = MediaGroupingService()
    args = preview_media_groups.build_parser().parse_args(["--project-slug", "teeon"])

    groups = preview_media_groups.collect_groups(db_session, service, args)
    preview_media_groups.print_groups(db_session, groups)

    out = capsys.readouterr().out
    assert "Группа" in out
    assert "футболка" in out


def test_create_creates_needs_review_post(db_session: Session) -> None:
    _seed(db_session)
    service = MediaGroupingService()
    args = create_media_group_post.build_parser().parse_args(
        ["--project-slug", "teeon", "--tag", "футболка"]
    )

    post = create_media_group_post.create_from_args(db_session, service, args)

    assert post is not None
    assert post.status == "needs_review"
    assert len(post.generation_notes["media_asset_ids"]) >= 2
    assert post_repository.list_posts(db_session)  # ровно один пост создан
    assert len(post_repository.list_posts(db_session)) == 1


def test_print_post_runs(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    _seed(db_session)
    service = MediaGroupingService()
    args = create_media_group_post.build_parser().parse_args(
        ["--project-slug", "teeon", "--tag", "футболка"]
    )

    post = create_media_group_post.create_from_args(db_session, service, args)
    assert post is not None
    create_media_group_post._print_post(post)

    out = capsys.readouterr().out
    assert f"id={post.id}" in out
    assert "publish_post" in out


def test_create_returns_none_when_no_group(db_session: Session) -> None:
    create_project(db_session, ProjectCreate(name="TEEON", slug="teeon"))
    service = MediaGroupingService()
    args = create_media_group_post.build_parser().parse_args(
        ["--project-slug", "teeon", "--tag", "футболка"]
    )

    assert create_media_group_post.create_from_args(db_session, service, args) is None
