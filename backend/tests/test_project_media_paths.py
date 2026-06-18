"""Тесты сопоставления проектов и папок Яндекс Диска."""

import pytest

from app.services.project_media_paths import (
    UnknownProjectError,
    get_default_scan_folders,
    get_project_disk_root,
)


def test_teeon_root() -> None:
    assert get_project_disk_root("teeon") == "/SMM_BOT/01_TEEON"


def test_fabric_souvenirs_root() -> None:
    assert get_project_disk_root("fabric-souvenirs") == "/SMM_BOT/02_Фабрика_сувениров"


def test_default_scan_folders() -> None:
    folders = get_default_scan_folders("teeon")
    assert folders == [
        "/SMM_BOT/01_TEEON/01_Входящие_на_разбор",
        "/SMM_BOT/01_TEEON/02_Одобренные_фото",
        "/SMM_BOT/01_TEEON/03_Видео",
        "/SMM_BOT/01_TEEON/04_Внешние_картинки_из_интернета",
        "/SMM_BOT/01_TEEON/06_Нужно_переснять",
    ]


def test_default_scan_folders_includes_reshoot_excludes_used() -> None:
    folders = get_default_scan_folders("teeon")
    assert len(folders) == 5
    assert any("06_Нужно_переснять" in f for f in folders)
    assert not any("05_Использовано_в_постах" in f for f in folders)


def test_custom_root_path() -> None:
    assert get_project_disk_root("teeon", root_path="/Custom/Root") == "/Custom/Root/01_TEEON"


def test_unknown_slug_raises() -> None:
    with pytest.raises(UnknownProjectError):
        get_project_disk_root("unknown-slug")
