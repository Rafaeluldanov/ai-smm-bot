"""Тесты правил доступа к публичным папкам Яндекс Диска по проектам."""

from app.services.project_media_paths import (
    get_public_project_folder_names,
    get_public_scan_roots,
    is_public_folder_allowed_for_project,
    is_public_path_allowed_for_project,
)


def test_teeon_can_use_tion() -> None:
    assert is_public_folder_allowed_for_project("teeon", "Тион") is True
    assert is_public_folder_allowed_for_project("teeon", "/SMM/Тион") is True


def test_teeon_cannot_use_fabric() -> None:
    assert is_public_folder_allowed_for_project("teeon", "Фабрика сувениров") is False
    assert is_public_folder_allowed_for_project("teeon", "/SMM/Фабрика сувениров") is False


def test_fabric_can_use_own_and_tion() -> None:
    assert is_public_folder_allowed_for_project("fabric-souvenirs", "Фабрика сувениров") is True
    assert is_public_folder_allowed_for_project("fabric-souvenirs", "Тион") is True
    assert is_public_folder_allowed_for_project("fabric-souvenirs", "/SMM/Тион") is True


def test_normalization() -> None:
    assert is_public_folder_allowed_for_project("teeon", "тион") is True
    assert is_public_folder_allowed_for_project("teeon", "TEEON") is True
    assert is_public_folder_allowed_for_project("teeon", "Tion") is True
    assert is_public_folder_allowed_for_project("teeon", "  Тион  ") is True


def test_folder_names_and_scan_roots() -> None:
    assert "Тион" in get_public_project_folder_names("teeon")
    assert get_public_scan_roots("teeon", root_folder="SMM") == ["/SMM/Тион"]
    fabric_roots = get_public_scan_roots("fabric-souvenirs", root_folder="SMM")
    assert "/SMM/Тион" in fabric_roots
    assert "/SMM/Фабрика сувениров" in fabric_roots


def test_path_policy_blocks_nested_fabric_for_teeon() -> None:
    # teeon: «Фабрика сувениров», вложенная в «Тион», запрещена по полному пути.
    assert is_public_path_allowed_for_project("teeon", "/SMM/Тион/tion-foto.jpg") is True
    assert is_public_path_allowed_for_project("teeon", "/SMM/Тион/Фабрика сувениров/k.jpg") is False
    assert is_public_path_allowed_for_project("teeon", "/SMM/Тион/02_Одобренные/x.jpg") is True


def test_path_policy_allows_everything_for_fabric() -> None:
    assert is_public_path_allowed_for_project("fabric-souvenirs", "/SMM/Тион/x.jpg") is True
    assert (
        is_public_path_allowed_for_project("fabric-souvenirs", "/SMM/Фабрика сувениров/x.jpg")
        is True
    )
