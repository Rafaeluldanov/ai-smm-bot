"""Тесты моделей атрибуции (v0.6.8): first_touch / last_touch / multi_touch.

Проверяет корректность распределения выручки по касаниям контента + атрибуцию на кампанию.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.ai_sales_intelligence_service import AISalesIntelligenceService


def _svc() -> AISalesIntelligenceService:
    return AISalesIntelligenceService(
        settings=Settings(media_proxy_public_base_url="https://m.example.com")
    )


def _project(db: Session, slug: str) -> int:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    return project.id


def _post(db: Session, project_id: int, title: str) -> int:
    return post_repository.create_post(
        db, PostCreate(project_id=project_id, title=title, status="published", vk_text="x")
    ).id


def _two_touch_journey(db: Session, svc: AISalesIntelligenceService, pid: int) -> tuple[int, int]:
    """Путь лида L1: касание A (lead_created) → касание B (deal_won 60000)."""
    a = _post(db, pid, "Пост A")
    b = _post(db, pid, "Пост B")
    svc.record_lead_event(
        db, pid, event_type="lead_created", post_id=a, metadata={"lead_ref": "L1"}
    )
    svc.record_lead_event(
        db, pid, event_type="deal_won", post_id=b, value=60000, metadata={"lead_ref": "L1"}
    )
    return a, b


def test_first_touch_credits_first_post(db_session: Session) -> None:
    pid = _project(db_session, "attr1")
    svc = _svc()
    a, b = _two_touch_journey(db_session, svc, pid)
    rows = svc.calculate_attribution(db_session, pid, model="first_touch")
    by_post = {r["post_id"]: r["revenue_value"] for r in rows}
    assert by_post == {a: 60000.0}


def test_last_touch_credits_last_post(db_session: Session) -> None:
    pid = _project(db_session, "attr2")
    svc = _svc()
    a, b = _two_touch_journey(db_session, svc, pid)
    rows = svc.calculate_attribution(db_session, pid, model="last_touch")
    by_post = {r["post_id"]: r["revenue_value"] for r in rows}
    assert by_post == {b: 60000.0}


def test_multi_touch_splits_evenly(db_session: Session) -> None:
    pid = _project(db_session, "attr3")
    svc = _svc()
    a, b = _two_touch_journey(db_session, svc, pid)
    rows = svc.calculate_attribution(db_session, pid, model="multi_touch")
    by_post = {r["post_id"]: r["revenue_value"] for r in rows}
    assert by_post == {a: 30000.0, b: 30000.0}


def test_attribution_is_idempotent(db_session: Session) -> None:
    pid = _project(db_session, "attr4")
    svc = _svc()
    _two_touch_journey(db_session, svc, pid)
    n1 = len(svc.calculate_attribution(db_session, pid, model="last_touch"))
    n2 = len(svc.calculate_attribution(db_session, pid, model="last_touch"))
    assert n1 == n2  # пере-расчёт заменяет строки, не плодит дубли


def test_zero_revenue_journey_no_attribution(db_session: Session) -> None:
    pid = _project(db_session, "attr5")
    svc = _svc()
    a = _post(db_session, pid, "Пост A")
    # Только лид без выручки → нечего атрибутировать.
    svc.record_lead_event(db_session, pid, event_type="lead_created", post_id=a)
    rows = svc.calculate_attribution(db_session, pid, model="last_touch")
    assert rows == []


def test_campaign_only_attribution(db_session: Session) -> None:
    from app.models.ai_campaign import AICampaign

    pid = _project(db_session, "attr6")
    svc = _svc()
    campaign = AICampaign(project_id=pid, name="C", goal="sales", status="active")
    db_session.add(campaign)
    db_session.commit()
    # Выручка без поста, но с кампанией → атрибуция на кампанию.
    svc.record_lead_event(
        db_session, pid, event_type="deal_won", campaign_id=campaign.id, value=15000
    )
    rows = svc.calculate_attribution(db_session, pid, model="last_touch")
    assert len(rows) == 1
    assert rows[0]["post_id"] is None
    assert rows[0]["campaign_id"] == campaign.id
    assert rows[0]["revenue_value"] == 15000.0
