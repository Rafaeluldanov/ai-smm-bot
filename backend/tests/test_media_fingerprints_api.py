"""Тесты REST API fingerprint/дедупликации медиа (v0.4.7, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    media_fingerprint_repository,
    project_repository,
    user_repository,
)
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "123456789:fpSECRETtelegramTOKENxyz"


def _media(db: Session, project_id: int, key: str) -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=f"{key}.jpg",
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={"products": ["мерч"]},
        ),
    )
    db.commit()
    return asset.id


def _fp(db: Session, project_id: int, asset_id: int, sha: str) -> None:
    media_fingerprint_repository.create_fingerprint(
        db,
        project_id=project_id,
        media_asset_id=asset_id,
        status="calculated",
        source="media_variant",
        file_sha256=sha,
        perceptual_hash=None,
        metadata_signature={},
        tag_signature={"signature": ""},
    )


def _seed(db: Session, slug: str, with_dupes: bool = False):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    ids = [_media(db, project.id, f"{slug}-{i}") for i in range(2)]
    if with_dupes:
        _fp(db, project.id, ids[0], sha="dupe")
        _fp(db, project.id, ids[1], sha="dupe")
    return account, project, ids, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_preview_no_writes(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-prev")
    r = client.post(
        f"/media-fingerprints/projects/{project.id}/preview", json={"limit": 10}, headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["dry_run"] is True
    assert client.get(f"/media-fingerprints/projects/{project.id}", headers=_h(token)).json() == []


def test_calculate_writes_fingerprints(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-calc")
    r = client.post(
        f"/media-fingerprints/projects/{project.id}/calculate",
        json={"limit": 10, "dry_run": False},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["created"] == 2
    lst = client.get(f"/media-fingerprints/projects/{project.id}", headers=_h(token)).json()
    assert len(lst) == 2


def test_single_asset_fingerprint(client: TestClient, db_session: Session) -> None:
    _a, project, ids, token = _seed(db_session, "fpa-one")
    pv = client.post(
        f"/media-fingerprints/projects/{project.id}/media-assets/{ids[0]}/preview",
        headers=_h(token),
    )
    assert pv.status_code == 200 and pv.json()["writes"] is False
    sc = client.post(
        f"/media-fingerprints/projects/{project.id}/media-assets/{ids[0]}/calculate",
        headers=_h(token),
    )
    assert sc.status_code == 200
    fid = sc.json()["id"]
    assert client.get(f"/media-fingerprints/{fid}", headers=_h(token)).status_code == 200


def test_duplicates_preview_and_calculate(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-dup", with_dupes=True)
    pv = client.post(
        f"/media-fingerprints/projects/{project.id}/duplicates/preview", headers=_h(token)
    )
    assert pv.status_code == 200 and pv.json()["clusters_found"] == 1
    ca = client.post(
        f"/media-fingerprints/projects/{project.id}/duplicates/calculate",
        json={"dry_run": False},
        headers=_h(token),
    )
    assert ca.status_code == 200 and ca.json()["clusters_created"] == 1
    clusters = client.get(
        f"/media-fingerprints/projects/{project.id}/duplicates", headers=_h(token)
    ).json()
    assert len(clusters) == 1


def test_review_cluster(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-review", with_dupes=True)
    client.post(
        f"/media-fingerprints/projects/{project.id}/duplicates/calculate",
        json={"dry_run": False},
        headers=_h(token),
    )
    cid = client.get(
        f"/media-fingerprints/projects/{project.id}/duplicates", headers=_h(token)
    ).json()[0]["id"]
    r = client.post(
        f"/media-fingerprints/projects/{project.id}/duplicates/{cid}/review",
        json={"action": "reviewed"},
        headers=_h(token),
    )
    assert r.status_code == 200 and r.json()["status"] == "reviewed"


def test_dashboard(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-dash", with_dupes=True)
    d = client.get(f"/media-fingerprints/projects/{project.id}/dashboard", headers=_h(token))
    assert d.status_code == 200
    assert d.json()["total_fingerprints"] == 2


def test_tenant_isolation(client: TestClient, db_session: Session) -> None:
    _a1, p1, _i1, _t1 = _seed(db_session, "fpa-iso1")
    _a2, _p2, _i2, t2 = _seed(db_session, "fpa-iso2")
    assert client.get(f"/media-fingerprints/projects/{p1.id}", headers=_h(t2)).status_code == 404
    assert (
        client.post(
            f"/media-fingerprints/projects/{p1.id}/preview", json={}, headers=_h(t2)
        ).status_code
        == 404
    )


def test_no_secrets_or_paths_in_responses(client: TestClient, db_session: Session) -> None:
    _a, project, _ids, token = _seed(db_session, "fpa-nosec")
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    client.post(
        f"/media-fingerprints/projects/{project.id}/calculate",
        json={"limit": 10, "dry_run": False},
        headers=_h(token),
    )
    bodies = [
        client.get(f"/media-fingerprints/projects/{project.id}", headers=_h(token)).text,
        client.get(f"/media-fingerprints/projects/{project.id}/dashboard", headers=_h(token)).text,
    ]
    for body in bodies:
        assert _SECRET_TOKEN not in body
        assert "api_key" not in body
        assert "disk:/" not in body
