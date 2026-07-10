"""Тесты подготовки VK photo-теста (offline; probe через httpx.MockTransport).

Пост создаётся ТОЛЬКО если probe рекомендует стратегию (wall/album), иначе — нет.
OAuth user-token не требуется. Токен не печатается; публикаций нет.
"""

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy.orm import Session

from app.integrations.vk.client import VKPublishingClient
from app.models.post import Post
from app.repositories import crm_bot_smm_repository as crm_repo
from app.repositories import media_asset_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmSmmResourceCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.scripts import prepare_vk_photo_test as prep
from app.services.media_grouping_service import MediaGroupingService

TOKEN = "SECRET_VK_TOKEN_do_not_leak"
GROUP_ID = 240102732
ACCOUNT_ID = 2
ALBUM_TITLE = "AI SMM Bot uploads"


def _probe_transport(*, wall_ok: bool = False, album_ok: bool = True) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "groups.getById" in path:
            return httpx.Response(200, json={"response": [{"id": 100, "name": "TEEON"}]})
        if "photos.getWallUploadServer" in path:
            if wall_ok:
                return httpx.Response(200, json={"response": {"upload_url": "https://u/x"}})
            return httpx.Response(200, json={"error": {"error_code": 27, "error_msg": "group"}})
        if "photos.getAlbums" in path:
            if album_ok:
                return httpx.Response(
                    200, json={"response": {"items": [{"id": 555, "title": ALBUM_TITLE}]}}
                )
            return httpx.Response(200, json={"error": {"error_code": 15, "error_msg": "denied"}})
        return httpx.Response(200, json={"error": {"error_code": 100, "error_msg": "unknown"}})

    return httpx.MockTransport(handler)


def _client(transport: httpx.MockTransport) -> VKPublishingClient:
    return VKPublishingClient(
        token=TOKEN,
        default_target_id=str(GROUP_ID),
        transport=transport,
        photo_upload_strategy="auto",
        photo_album_title=ALBUM_TITLE,
    )


def _seed(db: Session, *, with_media: bool = True) -> Any:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    project.account_id = ACCOUNT_ID
    db.commit()
    db.refresh(project)
    config = crm_repo.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name="TEEON")
    )
    crm_repo.create_resource(
        db,
        CrmSmmResourceCreate(
            project_id=project.id,
            config_id=config.id,
            resource_type="vk",
            title="VK TEEON",
            external_id=str(GROUP_ID),
        ),
    )
    if with_media:
        for i in range(3):
            media_asset_repository.create_media_asset(
                db,
                MediaAssetCreate(
                    project_id=project.id,
                    file_name=f"tshirt_{i}.jpg",
                    yandex_disk_path=f"public://yandex/teeon/teeon/tshirt_{i}.jpg",
                    source_type="internal",
                    license_type="company_owned",
                    status="approved",
                    tags={"products": ["футболка"]},
                ),
            )
    return project


def _args(dry_run: bool, account_id: int = ACCOUNT_ID) -> SimpleNamespace:
    return SimpleNamespace(
        account_id=account_id,
        project_slug="teeon",
        tag="футболка",
        dry_run="true" if dry_run else "false",
    )


def test_no_post_when_strategy_none(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _seed(db_session)
    # wall и album недоступны → recommended none → пост НЕ создан.
    result = prep.run(
        db_session,
        _client(_probe_transport(wall_ok=False, album_ok=False)),
        MediaGroupingService(),
        _args(False),
    )
    assert result is not None and result["reason"] == "strategy_none"
    assert not post_repository.list_posts(db_session, project_id=project.id)
    assert "не работают" in capsys.readouterr().out


def test_apply_creates_post_when_album_recommended(
    db_session: Session, capsys: pytest.CaptureFixture[str]
) -> None:
    project = _seed(db_session)
    result = prep.run(
        db_session,
        _client(_probe_transport(wall_ok=False, album_ok=True)),
        MediaGroupingService(),
        _args(False),
    )
    assert result is not None and result["created"] is True and result["strategy"] == "album"
    posts = post_repository.list_posts(db_session, project_id=project.id)
    assert len(posts) == 1
    post: Post = posts[0]
    assert post.status == "needs_review"
    notes = post.generation_notes
    assert notes.get("platform_target") == "vk"
    assert notes.get("media_policy") == "media_group"
    assert notes.get("vk_photo_upload_strategy") == "album"
    assert notes.get("media_count") and notes.get("media_asset_ids")
    assert TOKEN not in capsys.readouterr().out


def test_apply_creates_post_when_wall_recommended(db_session: Session) -> None:
    project = _seed(db_session)
    result = prep.run(
        db_session,
        _client(_probe_transport(wall_ok=True)),
        MediaGroupingService(),
        _args(False),
    )
    assert result is not None and result["strategy"] == "wall"
    post = post_repository.list_posts(db_session, project_id=project.id)[0]
    assert post.generation_notes.get("vk_photo_upload_strategy") == "wall"


def test_dry_run_writes_nothing(db_session: Session, capsys: pytest.CaptureFixture[str]) -> None:
    project = _seed(db_session)
    result = prep.run(db_session, _client(_probe_transport()), MediaGroupingService(), _args(True))
    assert result is not None and result["dry_run"] is True and result["post_id"] is None
    assert not post_repository.list_posts(db_session, project_id=project.id)
    out = capsys.readouterr().out
    assert "review_post" in out and "--platform vk" in out


def test_no_media_no_post(db_session: Session) -> None:
    project = _seed(db_session, with_media=False)
    result = prep.run(db_session, _client(_probe_transport()), MediaGroupingService(), _args(False))
    assert result is not None and result["reason"] == "no_media"
    assert not post_repository.list_posts(db_session, project_id=project.id)


def test_wrong_account_blocked(db_session: Session) -> None:
    _seed(db_session)
    result = prep.run(
        db_session,
        _client(_probe_transport()),
        MediaGroupingService(),
        _args(True, account_id=ACCOUNT_ID + 999),
    )
    assert result is None
