"""Тесты API режима автоматизации (v0.4.0, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, project_repository, user_repository
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import (
    CrmBotProjectConfigCreate,
    CrmPromotionCategoryCreate,
    CrmPublishingPlanCreate,
)
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService


def _seed(db: Session, slug: str):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    config = crm.create_config(
        db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug)
    )
    category = crm.create_category(
        db, CrmPromotionCategoryCreate(project_id=project.id, config_id=config.id, title="C")
    )
    plan = crm.create_plan(
        db,
        CrmPublishingPlanCreate(
            project_id=project.id,
            config_id=config.id,
            category_id=category.id,
            weekdays=[0],
            publish_times=["12:00"],
            platforms=["telegram"],
        ),
    )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, plan, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_get_settings_defaults_semi_auto(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-get")
    r = client.get(f"/automation/projects/{project.id}/settings", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["effective_mode"] == "semi_auto"
    assert body["plans_count"] == 1
    assert body["full_auto_confirmation_phrase"] == "ENABLE_FULL_AUTO"


def test_set_semi_auto(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-semi")
    r = client.post(
        f"/automation/projects/{project.id}/settings",
        json={"automation_mode": "semi_auto"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["effective_mode"] == "semi_auto"


def test_full_auto_requires_confirmation(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-fa1")
    r = client.post(
        f"/automation/projects/{project.id}/settings",
        json={"automation_mode": "full_auto", "auto_publish_enabled": True},
        headers=_h(token),
    )
    assert r.status_code == 400


def test_full_auto_with_confirmation(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-fa2")
    r = client.post(
        f"/automation/projects/{project.id}/settings",
        json={
            "automation_mode": "full_auto",
            "auto_publish_enabled": True,
            "confirm": "ENABLE_FULL_AUTO",
        },
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["effective_mode"] == "full_auto"


def test_full_auto_does_not_enable_live_flag(client: TestClient, db_session: Session) -> None:
    """full_auto НЕ включает глобальные live-флаги публикации."""
    from app.config import get_settings

    _acc, project, _plan, token = _seed(db_session, "am-live")
    client.post(
        f"/automation/projects/{project.id}/settings",
        json={
            "automation_mode": "full_auto",
            "auto_publish_enabled": True,
            "confirm": "ENABLE_FULL_AUTO",
        },
        headers=_h(token),
    )
    s = get_settings()
    assert s.telegram_live_publishing_enabled is False
    assert s.vk_live_publishing_enabled is False
    assert s.instagram_live_publishing_enabled is False


def test_set_plan_mode(client: TestClient, db_session: Session) -> None:
    _acc, project, plan, token = _seed(db_session, "am-plan")
    r = client.post(
        f"/automation/projects/{project.id}/plans/{plan.id}/mode",
        json={"automation_mode": "full_auto", "confirm": "ENABLE_FULL_AUTO"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["plan"]["automation_mode"] == "full_auto"


def test_mode_change_audit_logged(client: TestClient, db_session: Session) -> None:
    from app.repositories import audit_log_repository

    acc, project, _plan, token = _seed(db_session, "am-audit")
    client.post(
        f"/automation/projects/{project.id}/settings",
        json={"automation_mode": "semi_auto"},
        headers=_h(token),
    )
    entries = audit_log_repository.list_for_account(db_session, acc.id, 100, 0)
    assert any(e.action == "automation.mode.changed" for e in entries)


def test_user_cannot_change_other_project(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, _pa, _ta = _seed(db_session, "am-o-a")
    _a2, _pb, _pb2, token_b = _seed(db_session, "am-o-b")
    r = client.post(
        f"/automation/projects/{proj_a.id}/settings",
        json={"automation_mode": "semi_auto"},
        headers=_h(token_b),
    )
    assert r.status_code == 404


def test_learning_summary_endpoint(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-learn")
    r = client.get(f"/learning/projects/{project.id}/summary", headers=_h(token))
    assert r.status_code == 200
    assert "has_profile" in r.json()


def test_set_plan_mode_unknown_plan_404(client: TestClient, db_session: Session) -> None:
    _acc, project, _plan, token = _seed(db_session, "am-404")
    r = client.post(
        f"/automation/projects/{project.id}/plans/999999/mode",
        json={"automation_mode": "semi_auto"},
        headers=_h(token),
    )
    assert r.status_code == 404


def test_rebuild_charges_project_account_only(client: TestClient, db_session: Session) -> None:
    """Пересчёт списывает units с аккаунта ПРОЕКТА; чужой account_id не влияет (tenant)."""
    acc, project, _plan, token = _seed(db_session, "am-rebuild")
    victim = account_repository.create_account(
        db_session,
        name="victim",
        slug="am-victim",
        owner_user_id=user_repository.create_user(
            db_session, email="v@e.com", password_hash="x"
        ).id,
    )
    BillingService().manual_topup(db_session, victim.id, 500, idempotency_key="victim")
    db_session.commit()
    victim_before = BillingService().get_balance(db_session, victim.id).balance_units
    owner_before = BillingService().get_balance(db_session, acc.id).balance_units
    # Даже если передать чужой account_id — он игнорируется (аккаунт берётся из проекта).
    r = client.post(
        f"/learning/projects/{project.id}/rebuild?account_id={victim.id}", headers=_h(token)
    )
    assert r.status_code == 200
    assert r.json()["units_charged"] == 5
    assert BillingService().get_balance(db_session, victim.id).balance_units == victim_before
    assert BillingService().get_balance(db_session, acc.id).balance_units == owner_before - 5
