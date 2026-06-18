"""Тесты заглушки vision-анализа (AI не подключён)."""

import pytest

from app.ai.vision import (
    BaseVisionAnalyzer,
    StubVisionAnalyzer,
    VisionAnalysisNotConfiguredError,
    VisionAnalysisResult,
)


def test_stub_raises_not_configured() -> None:
    analyzer = StubVisionAnalyzer()
    with pytest.raises(VisionAnalysisNotConfiguredError):
        analyzer.analyze_image_metadata("disk:/SMM_BOT/01_TEEON/02_Одобренные_фото/hoodie.jpg")


def test_stub_satisfies_protocol() -> None:
    # Структурная совместимость с контрактом анализатора.
    assert isinstance(StubVisionAnalyzer(), BaseVisionAnalyzer)


def test_vision_result_defaults() -> None:
    result = VisionAnalysisResult()
    assert result.labels == []
    assert result.objects == []
    assert result.colors == []
    assert result.text is None
    assert result.raw == {}
