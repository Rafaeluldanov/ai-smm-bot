"""Тесты адаптеров стратегии (v0.6.6): SEO + trend (mock). Без сети и внешних API."""

from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.seo_strategy_adapter import SeoStrategyAdapter
from app.services.trend_strategy_adapter import TrendStrategyAdapter


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def test_seo_signal_supported_project(db_session: Session) -> None:
    pid = _project(db_session, "teeon")  # известный SEO-проект
    signal = SeoStrategyAdapter().get_seo_signal(db_session, pid)
    assert signal["supported"] is True
    assert signal["keywords"]
    assert 0.0 <= signal["seo_score"] <= 1.0


def test_seo_signal_unknown_project_is_neutral(db_session: Session) -> None:
    pid = _project(db_session, "unknown-shop-xyz")
    signal = SeoStrategyAdapter().get_seo_signal(db_session, pid)
    # Неизвестный проект → нейтральный сигнал, без исключений.
    assert signal["supported"] is False
    assert signal["seo_score"] == 0.0


def test_seo_score_topic_range(db_session: Session) -> None:
    pid = _project(db_session, "teeon")
    score = SeoStrategyAdapter().score_topic_seo(db_session, pid, "одежда")
    assert 0.0 <= score <= 1.0


def test_trend_topics_are_deterministic() -> None:
    adapter = TrendStrategyAdapter()
    a = adapter.get_trending_topics("teeon")
    b = adapter.get_trending_topics("teeon")
    assert a == b  # детерминированный mock, без внешних API
    assert all({"topic", "score", "reason"} <= set(t) for t in a)


def test_trend_score_matches_keywords() -> None:
    adapter = TrendStrategyAdapter()
    # тема про видео производства совпадает с трендом «видео-обзор производства».
    assert adapter.score_topic_trend("Видео о нашем производстве") > 0.0
    # тема без совпадений → 0.
    assert adapter.score_topic_trend("абвгд ерунда") == 0.0
