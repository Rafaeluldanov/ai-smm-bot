"""Тесты сервиса fingerprint медиа (v0.4.7).

Offline; без внешнего AI/сети/live. Проверяют sha256/perceptual/dhash, metadata-fallback,
детерминизм, dry-run vs write и отсутствие путей/имён файлов в публичном результате.
"""

from io import BytesIO

from PIL import Image
from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    media_fingerprint_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.repositories import (
    media_asset_repository as media_repo,
)
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.project import ProjectCreate
from app.services.media_fingerprint_service import MediaFingerprintService


def _png(color: tuple[int, int, int], size: tuple[int, int] = (64, 64)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _media(db: Session, project_id: int, key: str, file_name: str = "img.jpg") -> int:
    asset = media_repo.create_media_asset(
        db,
        MediaAssetCreate(
            project_id=project_id,
            file_name=file_name,
            yandex_disk_path=f"disk:/{key}.jpg",
            source_type="internal",
            license_type=None,
            status="approved",
            tags={"products": ["мерч"], "technologies": ["dtf"]},
        ),
    )
    db.commit()
    return asset.id


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    return account, project


def _svc(**flags: object) -> MediaFingerprintService:
    return MediaFingerprintService(settings=Settings(**flags))


def test_sha256_from_bytes_deterministic() -> None:
    content = _png((200, 30, 30))
    svc = _svc()
    assert svc.calculate_file_sha256(content) == svc.calculate_file_sha256(content)
    assert svc.calculate_file_sha256(content) != svc.calculate_file_sha256(_png((20, 40, 200)))


def test_perceptual_hash_deterministic_and_hex() -> None:
    grad = BytesIO()
    Image.linear_gradient("L").resize((64, 64)).convert("RGB").save(grad, "PNG")
    content = grad.getvalue()
    svc = _svc()
    h1 = svc.calculate_perceptual_hash(content, "g.png")
    h2 = svc.calculate_perceptual_hash(content, "g.png")
    assert h1 == h2
    assert h1["average_hash"] and len(h1["average_hash"]) == 16
    assert h1["difference_hash"] and len(h1["difference_hash"]) == 16
    assert h1["perceptual_hash"] == h1["average_hash"]


def test_perceptual_hash_fallback_on_bad_bytes() -> None:
    assert _svc().calculate_perceptual_hash(b"not-an-image", "x.jpg") == {}


def test_color_signature_distinguishes_colors() -> None:
    svc = _svc()
    red = svc.calculate_color_signature(_png((200, 30, 30)), "r.png")
    blue = svc.calculate_color_signature(_png((20, 40, 200)), "b.png")
    assert red["buckets"] != blue["buckets"]


def test_metadata_signature_hashes_name_and_path(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fp-meta")
    aid = _media(db_session, project.id, "secret", file_name="secret-photo.jpg")
    asset = media_repo.get_media_asset_by_id(db_session, aid)
    sig = _svc().build_metadata_signature(asset)
    assert sig["extension"] == "jpg" and sig["media_kind"] == "image"
    assert sig["name_hash"] and sig["yandex_path_hash"]
    blob = str(sig)
    assert "secret-photo.jpg" not in blob and "disk:/" not in blob


def test_dry_run_no_write(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fp-dry")
    aid = _media(db_session, project.id, "a")
    result = _svc().calculate_fingerprint_for_asset(db_session, project.id, aid, dry_run=True)
    assert result["writes"] is False
    assert media_fingerprint_repository.list_for_project(db_session, project.id) == []


def test_write_creates_fingerprint(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fp-write")
    aid = _media(db_session, project.id, "a")
    result = _svc().calculate_fingerprint_for_asset(db_session, project.id, aid, dry_run=False)
    assert result["writes"] is True
    # Без локальных байтов — metadata-only fallback (status partial).
    assert result["status"] in ("partial", "calculated", "unavailable")
    rows = media_fingerprint_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1 and rows[0].media_asset_id == aid


def test_metadata_only_fallback_status(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fp-part")
    aid = _media(db_session, project.id, "a")
    result = _svc().calculate_fingerprint_for_asset(db_session, project.id, aid, dry_run=True)
    # Локальных байтов нет → partial (metadata/tags-only), без визуального хэша.
    assert result["status"] == "partial"
    assert result["perceptual_hash"] is None


def test_no_internal_path_in_public_result(db_session: Session) -> None:
    _acc, project = _seed(db_session, "fp-nopath")
    aid = _media(db_session, project.id, "hidden", file_name="hidden-file.jpg")
    result = _svc().calculate_fingerprint_for_asset(db_session, project.id, aid, dry_run=False)
    blob = str(result)
    assert "disk:/" not in blob
    assert "hidden-file.jpg" not in blob
    assert "hidden" not in blob


def test_no_cross_project_mixing(db_session: Session) -> None:
    _a1, p1 = _seed(db_session, "fp-iso1")
    _a2, p2 = _seed(db_session, "fp-iso2")
    aid = _media(db_session, p1.id, "a")
    _svc().calculate_fingerprint_for_asset(db_session, p1.id, aid, dry_run=False)
    assert media_fingerprint_repository.list_for_project(db_session, p2.id) == []
    assert len(media_fingerprint_repository.list_for_project(db_session, p1.id)) == 1


def test_score_asset_other_project_rejected(db_session: Session) -> None:
    import pytest

    from app.services.media_fingerprint_service import MediaFingerprintError

    _a1, p1 = _seed(db_session, "fp-rej1")
    _a2, p2 = _seed(db_session, "fp-rej2")
    aid = _media(db_session, p1.id, "a")
    with pytest.raises(MediaFingerprintError):
        _svc().calculate_fingerprint_for_asset(db_session, p2.id, aid, dry_run=True)
