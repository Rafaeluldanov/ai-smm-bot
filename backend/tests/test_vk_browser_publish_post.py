"""Тесты VK browser publisher fallback (offline; без реального браузера/сети/токенов)."""

import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.repositories import post_publication_repository, post_repository
from app.repositories.project_repository import create_project
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.scripts import vk_browser_publish_post as vb

SETTINGS = SimpleNamespace(vk_default_group_id="240102732")


class FakeBrowser:
    """Заглушка browser_fn: не поднимает браузер, фиксирует вызовы и возвращает result."""

    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


def _args(post: Any, **over: Any) -> SimpleNamespace:
    base = {
        "post_id": post.id,
        "group_url": None,
        "browser_profile_dir": "tmp/vk_browser_profile",
        "dry_run": "true",
        "max_images": 5,
        "headless": "false",
        "confirm_live": "false",
    }
    base.update(over)
    return SimpleNamespace(**base)


def _seed_post(
    db: Session,
    tmp_path: Path,
    *,
    images: int = 2,
    vk_text: str = "VK текст",
    extra_notes: Any = None,
) -> Any:
    project = create_project(db, ProjectCreate(name="TEEON", slug="teeon"))
    media_files: list[dict[str, Any]] = []
    for index in range(images):
        img = tmp_path / f"img_{index}.jpg"
        img.write_bytes(b"\xff\xd8\xff\xe0JPEGDATA")  # локальный файл-картинка
        media_files.append({"file_name": img.name, "media_path": str(img), "media_kind": "image"})
    notes = {"media_files": media_files, "media_asset_ids": list(range(images))}
    if extra_notes is not None:
        notes = extra_notes
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project.id,
            title="Заголовок",
            vk_text=vk_text,
            telegram_text="TG текст",
            status="needs_review",
            generation_notes=notes,
        ),
    )
    return post


# --------------------------------------------------------------------------- #
# Чистые функции                                                              #
# --------------------------------------------------------------------------- #


def test_build_group_url_from_group_id() -> None:
    assert vb.build_group_url_from_group_id("240102732") == "https://vk.com/club240102732"
    assert vb.build_group_url_from_group_id("club240102732") == "https://vk.com/club240102732"
    assert vb.build_group_url_from_group_id("-240102732") == "https://vk.com/club240102732"
    assert vb.build_group_url_from_group_id("") is None
    assert vb.build_group_url_from_group_id(None) is None


def test_select_vk_text_prefers_vk_text() -> None:
    assert vb.select_vk_text(SimpleNamespace(vk_text="A", telegram_text="B", title="C")) == "A"
    assert vb.select_vk_text(SimpleNamespace(vk_text="", telegram_text="B", title="C")) == "B"
    assert vb.select_vk_text(SimpleNamespace(vk_text="", telegram_text="", title="C")) == "C"
    assert vb.select_vk_text(SimpleNamespace(vk_text=None, telegram_text=None, title=None)) == ""


def test_extract_image_media_files_from_generation_notes() -> None:
    notes = {
        "media_files": [
            {"file_name": "a.jpg", "media_kind": "image"},
            {"file_name": "clip.mp4", "media_kind": "video"},
            {"file_name": "b.png"},  # kind не указан → по расширению image
        ]
    }
    images = vb.extract_image_media_files(notes, 5)
    assert [i["file_name"] for i in images] == ["a.jpg", "b.png"]


def test_limits_max_images() -> None:
    notes = {"media_files": [{"file_name": f"{i}.jpg", "media_kind": "image"} for i in range(10)]}
    assert len(vb.extract_image_media_files(notes, 3)) == 3


def test_heic_conversion_path_is_selected(tmp_path: Path) -> None:
    # needs_heic_conversion распознаёт HEIC/HEIF.
    assert vb.needs_heic_conversion("photo.HEIC") is True
    assert vb.needs_heic_conversion("photo.jpg") is False

    # prepare_images конвертирует HEIC → .jpg через процессор (path выбран).
    class _Downloaded:
        bytes = b"HEICBYTES"

    class _Downloader:
        def download_public_media(self, disk_path: str, file_name: str) -> Any:
            return _Downloaded()

    class _Processor:
        def enhance_image_bytes(
            self, image_bytes: bytes, profile: str, operations: Any = None
        ) -> Any:
            return SimpleNamespace(output_bytes=b"JPEGBYTES")

    items = [{"file_name": "photo.heic", "yandex_disk_path": "public://yandex/x/photo.heic"}]
    paths, warnings = vb.prepare_images(items, _Downloader(), _Processor(), tmp_path / "out")
    assert len(paths) == 1
    assert paths[0].name.endswith(".jpg")  # сконвертировано в JPEG
    assert paths[0].read_bytes() == b"JPEGBYTES"
    assert warnings == []  # HEIC успешно сконвертирован — предупреждения нет


def test_heic_without_processor_warns(tmp_path: Path) -> None:
    class _Downloaded:
        bytes = b"HEICBYTES"

    class _Downloader:
        def download_public_media(self, disk_path: str, file_name: str) -> Any:
            return _Downloaded()

    items = [{"file_name": "photo.heic", "yandex_disk_path": "public://yandex/x/photo.heic"}]
    paths, warnings = vb.prepare_images(items, _Downloader(), None, tmp_path / "out")
    assert len(paths) == 1
    assert any("HEIC" in w for w in warnings)  # понятное предупреждение


# --------------------------------------------------------------------------- #
# Оркестрация (run) с инъекцией browser_fn                                     #
# --------------------------------------------------------------------------- #


def test_rejects_no_images(db_session: Session, tmp_path: Path) -> None:
    post = _seed_post(db_session, tmp_path, extra_notes={"media_files": []})
    fake = FakeBrowser({"published": False})
    result = vb.run(db_session, None, None, SETTINGS, _args(post), browser_fn=fake)
    assert result is not None and result["reason"] == "no_images"
    assert fake.calls == []  # браузер не запускался


def test_dry_run_does_not_mark_publication_published(db_session: Session, tmp_path: Path) -> None:
    post = _seed_post(db_session, tmp_path, images=2)
    fake = FakeBrowser({"published": False})
    result = vb.run(db_session, None, None, SETTINGS, _args(post, dry_run="true"), browser_fn=fake)
    assert result is not None and result["dry_run"] is True and result["created"] is False
    assert result["images"] == 2
    # В БД нет опубликованной VK-публикации.
    assert post_publication_repository.list_publications(db_session, post_id=post.id) == []
    # Группа взята из VK_DEFAULT_GROUP_ID.
    assert fake.calls and fake.calls[0]["group_url"] == "https://vk.com/club240102732"


def test_live_requires_confirm_live(db_session: Session, tmp_path: Path) -> None:
    post = _seed_post(db_session, tmp_path, images=1)
    fake = FakeBrowser({"published": True})
    result = vb.run(
        db_session,
        None,
        None,
        SETTINGS,
        _args(post, dry_run="false", confirm_live="false"),
        browser_fn=fake,
    )
    assert result is not None and result["reason"] == "need_confirm_live"
    assert fake.calls == []  # без confirm-live браузер не запускается
    assert post_publication_repository.list_publications(db_session, post_id=post.id) == []


def test_live_with_confirm_records_publication(db_session: Session, tmp_path: Path) -> None:
    post = _seed_post(db_session, tmp_path, images=1)
    fake = FakeBrowser(
        {
            "published": True,
            "external_url": "https://vk.com/wall-240102732_5",
            "external_post_id": "-240102732_5",
        }
    )
    result = vb.run(
        db_session,
        None,
        None,
        SETTINGS,
        _args(post, dry_run="false", confirm_live="true"),
        browser_fn=fake,
    )
    assert result is not None and result["published"] is True and result["created"] is True
    pubs = post_publication_repository.list_publications(
        db_session, post_id=post.id, status="published"
    )
    assert len(pubs) == 1
    assert pubs[0].platform == "vk"
    assert pubs[0].external_url == "https://vk.com/wall-240102732_5"


def test_secrets_and_post_text_are_not_printed(
    db_session: Session, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    secret_marker = "SUPER_SECRET_TEXT_XYZ"
    post = _seed_post(db_session, tmp_path, images=1, vk_text=secret_marker)
    fake = FakeBrowser({"published": False})
    vb.run(db_session, None, None, SETTINGS, _args(post, dry_run="true"), browser_fn=fake)
    out = capsys.readouterr().out
    # Скрипт печатает длину/источник текста, но НЕ сам текст (безопасность).
    assert secret_marker not in out
    # В модуле нет обращения к VK API-токену/паролю.
    src = inspect.getsource(vb).lower()
    assert "vk_access_token" not in src
    assert "getpass" not in src


def test_playwright_missing_message_is_clear() -> None:
    assert "pip install playwright" in vb.PLAYWRIGHT_MISSING_MESSAGE
    assert "playwright install chromium" in vb.PLAYWRIGHT_MISSING_MESSAGE
