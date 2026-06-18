"""Тесты fake-провайдера внешних изображений (без сети)."""

from app.services.external_image_provider import FakeExternalImageProvider


def test_deterministic() -> None:
    provider = FakeExternalImageProvider()
    first = provider.search("шелкография", 10)
    second = provider.search("шелкография", 10)
    assert [r.source_url for r in first] == [r.source_url for r in second]
    assert first


def test_query_present_in_results() -> None:
    results = FakeExternalImageProvider().search("шелкография", 10)
    assert any("шелкография" in (r.title or "") for r in results)
    assert any("шелкография" in r.tags for r in results)


def test_has_logo_and_noncommercial_variants() -> None:
    results = FakeExternalImageProvider().search("футболки", 10)
    assert any(r.contains_logo for r in results)
    assert any(not r.commercial_use_allowed for r in results)
    assert any(r.commercial_use_allowed and r.safe_for_business for r in results)


def test_limit_respected() -> None:
    assert len(FakeExternalImageProvider().search("футболки", 2)) == 2
    assert len(FakeExternalImageProvider().search("футболки", 0)) == 0
