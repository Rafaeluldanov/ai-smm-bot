"""Тесты fake-провайдера метрик (без сети)."""

from app.models.post_publication import PostPublication
from app.services.analytics_provider import FakeAnalyticsProvider


def _publication(post_id: int, platform: str) -> PostPublication:
    return PostPublication(post_id=post_id, project_id=1, platform=platform, status="published")


def test_deterministic() -> None:
    provider = FakeAnalyticsProvider()
    first = provider.fetch_post_metrics(_publication(5, "telegram"))
    second = provider.fetch_post_metrics(_publication(5, "telegram"))
    assert first == second
    assert set(first) >= {"impressions", "reach", "likes", "clicks"}
    assert first["impressions"] > 0


def test_varies_by_platform() -> None:
    provider = FakeAnalyticsProvider()
    telegram = provider.fetch_post_metrics(_publication(5, "telegram"))
    vk = provider.fetch_post_metrics(_publication(5, "vk"))
    # Разные платформы дают разные seed-метрики (детерминированно).
    assert telegram != vk
