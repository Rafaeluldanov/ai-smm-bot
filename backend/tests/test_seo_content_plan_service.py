"""Тесты SEO-контент-плана проекта."""

from datetime import date

from app.services.seo_content_plan_service import SeoContentPlanService


def _plan(days: int = 30):  # noqa: ANN202
    return SeoContentPlanService().build_plan("teeon", days=days, start_date=date(2026, 7, 7))


def test_plan_has_requested_number_of_days() -> None:
    plan = _plan(30)
    assert plan.days == 30
    assert len(plan.items) == 30
    assert [item.day_number for item in plan.items] == list(range(1, 31))


def test_every_item_has_site_url() -> None:
    plan = _plan(30)
    for item in plan.items:
        assert item.site_url.startswith("https://teeon.ru")
        assert item.cta
        assert item.media_tag


def test_plan_covers_priority_technologies() -> None:
    plan = _plan(30)
    technologies = {item.technology for item in plan.items if item.technology}
    assert {"DTF-печать", "вышивка", "гравировка", "УФ-печать"} <= technologies


def test_rubric_distribution_matches_content_mix() -> None:
    plan = _plan(30)
    dist = plan.rubric_distribution
    # 30% товары, 30% технологии, 20% производство, 10% кейсы, 10% FAQ.
    assert dist["Товары и изделия"] == 9
    assert dist["Технологии нанесения"] == 9
    assert dist["Производство и процесс"] == 6
    assert sum(dist.values()) == 30


def test_dates_increment_from_start() -> None:
    plan = _plan(5)
    assert plan.items[0].date == "2026-07-07"
    assert plan.items[4].date == "2026-07-11"


def test_technology_days_link_to_branding() -> None:
    plan = _plan(30)
    tech_items = [item for item in plan.items if item.technology]
    for item in tech_items:
        assert "/branding" in item.site_url
