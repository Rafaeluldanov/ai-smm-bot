"""Тесты процессора локального улучшения изображений (Pillow, без сети/AI)."""

from io import BytesIO

import pytest
from PIL import Image

from app.services.image_enhancement_processor import (
    PRODUCT_FIDELITY_WARNING,
    ImageEnhancementProcessor,
    ImageTooLargeError,
    UnsupportedImageError,
)


def _png(
    width: int = 1200, height: int = 800, color: tuple[int, int, int] = (120, 90, 60)
) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_social_safe_returns_jpeg_bytes() -> None:
    processor = ImageEnhancementProcessor(output_format="jpg")
    result = processor.enhance_image_bytes(_png(3000, 2000), "social_safe")

    assert result.output_bytes
    assert result.output_format == "jpg"
    assert max(result.width, result.height) <= 2048
    assert "resize" in result.operations_applied
    # social_safe не делает спорных правок — без предупреждений.
    assert result.warnings == []
    with Image.open(BytesIO(result.output_bytes)) as img:
        assert img.format == "JPEG"


def test_minimal_only_convert_resize() -> None:
    processor = ImageEnhancementProcessor()
    result = processor.enhance_image_bytes(_png(500, 500), "minimal")

    assert set(result.operations_applied) <= {"convert", "resize"}
    assert "auto_contrast" not in result.operations_applied
    # Маленькое изображение не ресайзится (thumbnail только уменьшает).
    assert "resize" not in result.operations_applied


def test_product_clean_warns_needs_review() -> None:
    processor = ImageEnhancementProcessor()
    result = processor.enhance_image_bytes(_png(), "product_clean")

    assert "white_balance" in result.operations_applied
    assert "denoise" in result.operations_applied
    assert PRODUCT_FIDELITY_WARNING in result.warnings


def test_operations_override_toggles_flags() -> None:
    processor = ImageEnhancementProcessor()
    result = processor.enhance_image_bytes(
        _png(), "social_safe", {"white_balance": True, "sharpen": False}
    )

    assert "white_balance" in result.operations_applied
    assert "sharpen" not in result.operations_applied
    # Баланс белого — спорная правка, появляется предупреждение.
    assert result.warnings


def test_quality_score_in_range() -> None:
    processor = ImageEnhancementProcessor()
    result = processor.enhance_image_bytes(_png(), "social_safe")
    assert 0.0 <= result.quality_score <= 1.0
    assert result.before_metadata["width"] == 1200


def test_corrupt_image_raises_clear_error() -> None:
    processor = ImageEnhancementProcessor()
    with pytest.raises(UnsupportedImageError):
        processor.enhance_image_bytes(b"not-an-image", "social_safe")


def test_too_large_raises() -> None:
    processor = ImageEnhancementProcessor(max_image_mb=1)
    with pytest.raises(ImageTooLargeError):
        processor.enhance_image_bytes(b"x" * (2 * 1024 * 1024), "social_safe")


def test_build_output_file_name() -> None:
    processor = ImageEnhancementProcessor()
    name = processor.build_output_file_name(7, "Худи DTF.HEIC", "social_safe", "jpg")
    assert name.startswith("7_")
    assert name.endswith(".jpg")
    assert "HEIC" not in name
