"""Тесты growth_score (v0.6.9): revenue 40 + conversion 25 + content 20 + learning 15."""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.business_growth_agent_service import BusinessGrowthAgentService

_SETTINGS = Settings(media_proxy_public_base_url="https://m.example.com")


def _svc() -> BusinessGrowthAgentService:
    return BusinessGrowthAgentService(settings=_SETTINGS)


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _signals(**over: object) -> dict:
    base = {
        "total_revenue": 0.0,
        "leads": 0,
        "won_deals": 0,
        "conversion": 0.0,
        "best_platform": "",
        "best_cta": [],
        "top_content": [],
        "top_campaigns": [],
        "best_topics": [],
        "weak_topics": [],
        "best_formats": [],
        "learning_score": 0.0,
        "content_efficiency": 0.0,
        "reach": 0,
        "impressions": 0,
    }
    base.update(over)
    return base


def test_score_weights_sum_to_100() -> None:
    svc = _svc()
    # Все компоненты на максимуме → score = 100 (40+25+20+15).
    s = _signals(total_revenue=200000, conversion=1.0, content_efficiency=1.0, learning_score=100)
    comps = svc._score_components(s)
    assert comps == {"revenue": 40.0, "conversion": 25.0, "content": 20.0, "learning": 15.0}
    assert svc._calculate_growth_score(s) == 100.0


def test_score_zero_signals() -> None:
    svc = _svc()
    assert svc._calculate_growth_score(_signals()) == 0.0


def test_revenue_normalized_and_clamped() -> None:
    svc = _svc()
    # Выручка выше ориентира → компонент не превышает вес 40.
    assert svc._score_components(_signals(total_revenue=100000))["revenue"] == 40.0
    assert svc._score_components(_signals(total_revenue=500000))["revenue"] == 40.0
    # Половина ориентира → половина веса.
    assert svc._score_components(_signals(total_revenue=50000))["revenue"] == 20.0


def test_conversion_component() -> None:
    svc = _svc()
    assert svc._score_components(_signals(conversion=0.5))["conversion"] == 12.5
    # Клампится ≤ 25 даже при conversion > 1.
    assert svc._score_components(_signals(conversion=2.0))["conversion"] == 25.0


def test_calculate_growth_score_endpoint(db_session: Session) -> None:
    pid = _project(db_session, "gs1")
    out = _svc().calculate_growth_score(db_session, pid)
    # Без данных — score 0, компоненты присутствуют.
    assert out["growth_score"] == 0.0
    assert set(out["components"]) == {"revenue", "conversion", "content", "learning"}
