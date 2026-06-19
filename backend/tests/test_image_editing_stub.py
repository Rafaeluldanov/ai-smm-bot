"""Тесты заглушки AI-ретуши: реальный AI не подключён."""

import pytest

from app.ai.image_editing import (
    BaseImageEditor,
    ImageEditingNotConfiguredError,
    ImageEditRequest,
    StubImageEditor,
)

_METHODS = (
    "remove_dirt_and_stains",
    "even_fabric_color",
    "improve_texture",
    "upscale",
    "edit_image",
)


def test_stub_raises_on_all_methods() -> None:
    editor = StubImageEditor()
    request = ImageEditRequest(image_bytes=b"x", operation="remove_dirt_and_stains")
    for method_name in _METHODS:
        with pytest.raises(ImageEditingNotConfiguredError):
            getattr(editor, method_name)(request)


def test_stub_satisfies_protocol() -> None:
    # Заглушка структурно реализует контракт будущего AI-редактора.
    assert isinstance(StubImageEditor(), BaseImageEditor)
