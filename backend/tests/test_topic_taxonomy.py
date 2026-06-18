"""Тесты словаря тем и кластеров (topic_taxonomy)."""

from app.services import topic_taxonomy as tax


def test_teeon_clusters() -> None:
    clusters = tax.get_topic_clusters("teeon")
    assert "футболки" in clusters
    assert "худи" in clusters
    assert "шелкография" in clusters


def test_fabric_clusters() -> None:
    clusters = tax.get_topic_clusters("fabric-souvenirs")
    assert "кружки" in clusters
    assert "ручки" in clusters
    assert "гравировка" in clusters


def test_cluster_topics() -> None:
    topics = tax.get_cluster_topics("teeon", "футболки")
    assert "Футболки с логотипом на заказ" in topics


def test_all_candidates_have_metadata() -> None:
    candidates = tax.get_all_topic_candidates("teeon")
    assert len(candidates) > 0
    sample = candidates[0]
    for key in (
        "title",
        "cluster",
        "base_seo_keywords",
        "related_media_tags",
        "recommended_formats",
        "default_business_priority",
    ):
        assert key in sample


def test_infer_cluster_from_tags() -> None:
    clusters = tax.infer_cluster_from_tags(
        {"products": ["футболка"], "technologies": ["шелкография"]}
    )
    assert "футболки" in clusters
    assert "шелкография" in clusters


def test_unknown_slug_returns_empty() -> None:
    assert tax.get_topic_clusters("unknown") == {}
    assert tax.get_all_topic_candidates("unknown") == []


def test_normalize_topic_key() -> None:
    assert tax.normalize_topic_key("  Шёлкография  ") == "шелкография"
