"""Тесты seed-ядра SEO-запросов TEEON."""

from app.services.teeon_seo_queries import (
    build_teeon_seo_queries,
    get_seed_clusters,
    group_by_cluster,
)


def test_queries_build_and_infer_fields() -> None:
    queries = build_teeon_seo_queries()
    assert len(queries) >= 60
    by_text = {q.query: q for q in queries}
    # Продукт/интент/приоритет выводятся из текста.
    assert by_text["производство кепок москва"].product == "кепки"
    assert by_text["производство кепок москва"].intent == "process"
    assert by_text["сколько стоит пошив футболки на производстве"].intent == "price"
    top = by_text["производство маек и футболок"]
    assert top.frequency == 9
    assert top.priority == 95  # 50 + 9*5


def test_queries_cluster_grouping() -> None:
    queries = build_teeon_seo_queries()
    grouped = group_by_cluster(queries)
    assert len(grouped) >= 8
    assert "футболки / майки" in grouped
    assert "лонгсливы" in grouped
    # Внутри кластера — по убыванию частотности.
    longsleeves = grouped["лонгсливы"]
    freqs = [q.frequency for q in longsleeves]
    assert freqs == sorted(freqs, reverse=True)
    # Каждый запрос принадлежит объявленному кластеру.
    for cluster in grouped:
        assert cluster in get_seed_clusters()


def test_zero_frequency_longtail_preserved() -> None:
    queries = build_teeon_seo_queries()
    zero = [q for q in queries if q.frequency == 0]
    # Нулевые запросы сохранены как long-tail.
    assert any(q.query == "пошив свитшотов оптом" for q in zero)
    assert any(q.query == "производство корпоративных курток" for q in zero)
    # Long-tail всё равно получает ненулевой приоритет.
    assert all(q.priority >= 50 for q in zero)
