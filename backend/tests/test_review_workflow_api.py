"""Тесты API review/approval workflow (v0.4.0, offline, tenant-изоляция)."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_feedback_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.platform_connection_service import PlatformConnectionService

_TOKEN = "123456789:ABCdefGHIjklMNOpqrstUVwxyz012345"


def _seed(db: Session, slug: str, connect: bool = True):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if connect:
        PlatformConnectionService().upsert_connection(
            db, project.id, "telegram", {"api_key": _TOKEN, "external_id": "@x"}
        )
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    db.commit()
    return account, project, make_dev_token(user.id)


def _post(db: Session, project_id: int, status: str = "needs_review"):  # noqa: ANN202
    post = post_repository.create_post(
        db,
        PostCreate(
            project_id=project_id,
            title="Тестовый пост",
            status=status,
            telegram_text="Заказать футболку за 990 руб! #мерч",
            hashtags=["мерч"],
        ),
    )
    db.commit()
    return post


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


def test_queue_returns_needs_review_posts(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvq")
    _post(db_session, project.id)
    r = client.get(f"/review/projects/{project.id}/queue", headers=_h(token))
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["items"][0]["quality_score"] >= 0


def test_approve_creates_feedback_event(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rva")
    post = _post(db_session, project.id)
    r = client.post(f"/review/posts/{post.id}/approve", json={"comment": "ok"}, headers=_h(token))
    assert r.status_code == 200
    assert r.json()["status"] == "approved"
    events = post_feedback_repository.list_for_post(db_session, post.id)
    assert any(e.event_type == "approved" for e in events)


def test_reject_creates_feedback_event(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvr")
    post = _post(db_session, project.id)
    r = client.post(
        f"/review/posts/{post.id}/reject",
        json={"reason_tags": ["не та тема"]},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    events = post_feedback_repository.list_for_post(db_session, post.id)
    assert any(e.event_type == "rejected" for e in events)


def test_request_changes_sets_status(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvc")
    post = _post(db_session, project.id)
    r = client.post(
        f"/review/posts/{post.id}/request-changes",
        json={"reason_tags": ["слишком длинно"]},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "changes_requested"
    db_session.refresh(post)
    assert post.status == "changes_requested"


def test_edit_creates_feedback_and_updates_post(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rve")
    post = _post(db_session, project.id)
    r = client.post(
        f"/review/posts/{post.id}/edit",
        json={"telegram_text": "Короткий новый текст. Заказать!"},
        headers=_h(token),
    )
    assert r.status_code == 200
    db_session.refresh(post)
    assert post.telegram_text == "Короткий новый текст. Заказать!"
    events = post_feedback_repository.list_for_post(db_session, post.id)
    assert any(e.event_type == "edited" for e in events)


def test_publish_now_blocked_when_live_disabled(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvp")
    post = _post(db_session, project.id)
    r = client.post(
        f"/review/posts/{post.id}/publish-now", json={"confirm": True}, headers=_h(token)
    )
    assert r.status_code == 200
    body = r.json()
    assert body["blocked"] is True
    assert body["published"] is False
    assert body["reason"] in ("live_disabled", "platform_not_connected", "missing_credentials")


def test_publish_now_no_charge_when_blocked(client: TestClient, db_session: Session) -> None:
    acc, project, token = _seed(db_session, "rvnc")
    post = _post(db_session, project.id)
    before = BillingService().get_balance(db_session, acc.id).balance_units
    r = client.post(
        f"/review/posts/{post.id}/publish-now", json={"confirm": True}, headers=_h(token)
    )
    assert r.json()["units_charged"] == 0
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert before == after


def test_publish_now_requires_confirmation(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvcf")
    post = _post(db_session, project.id)
    r = client.post(f"/review/posts/{post.id}/publish-now", json={}, headers=_h(token))
    assert r.status_code == 200
    assert r.json()["blocked"] is True
    assert r.json()["reason"] == "confirmation_required"


def test_no_raw_token_in_responses(client: TestClient, db_session: Session) -> None:
    _acc, project, token = _seed(db_session, "rvsec")
    post = _post(db_session, project.id)
    for path in (f"/review/projects/{project.id}/queue", f"/review/posts/{post.id}"):
        assert _TOKEN not in client.get(path, headers=_h(token)).text


def test_user_cannot_access_other_project_queue(client: TestClient, db_session: Session) -> None:
    _a1, proj_a, _ta = _seed(db_session, "rvo-a")
    _a2, _pb, token_b = _seed(db_session, "rvo-b")
    r = client.get(f"/review/projects/{proj_a.id}/queue", headers=_h(token_b))
    assert r.status_code == 404


# --- Регрессии по итогам adversarial-ревью (publish_now, service-level с fake-реестром) ---


def _fake_review_service(fail_vk: bool = False):  # noqa: ANN202
    from app.integrations.publishing import FakePublishingClient
    from app.services.post_publication_service import PostPublicationService
    from app.services.publication_platform_registry import PublicationPlatformRegistry
    from app.services.review_workflow_service import ReviewWorkflowService

    registry = PublicationPlatformRegistry(
        {
            "telegram": FakePublishingClient("telegram", live_enabled=True),
            "vk": FakePublishingClient("vk", live_enabled=True, fail=fail_vk),
        }
    )
    publication = PostPublicationService(
        registry=registry, default_targets={"telegram": "@x", "vk": "-1"}
    )
    return ReviewWorkflowService(publication_service=publication, billing_service=BillingService())


def test_publish_now_insufficient_balance_does_not_approve(db_session: Session) -> None:
    """Блокировка по балансу не должна оставлять пост approved (approve — после гейта баланса)."""
    acc, project, _token = _seed(db_session, "rv-bal")
    # Списываем весь баланс (_seed пополняет 500) → баланс 0 < 5, paid_actions_enforced=True.
    BillingService().debit_for_action(
        db_session, acc.id, units=500, usage_type="test_drain", idempotency_key="rv-bal-drain"
    )
    db_session.commit()
    post = _post(db_session, project.id)
    svc = _fake_review_service()
    result = svc.publish_now(db_session, post.id, confirm=True)
    assert result["blocked"] is True
    assert result["reason"] == "insufficient_balance"
    assert result["units_charged"] == 0
    db_session.refresh(post)
    assert post.status == "needs_review"  # НЕ approved


def test_publish_now_partial_success_charges_and_records(db_session: Session) -> None:
    """Частичный live-успех: списываем один раз, фиксируем публикацию, published=True."""
    acc, project, _token = _seed(db_session, "rv-partial")  # _seed уже пополняет 500 units
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "vk", {"api_key": "vk-secret", "external_id": "-1"}
    )
    post = post_repository.create_post(
        db_session,
        PostCreate(
            project_id=project.id,
            title="Мульти",
            status="needs_review",
            telegram_text="Заказать мерч #мерч",
            vk_text="Заказать мерч #мерч",
            hashtags=["мерч"],
        ),
    )
    db_session.commit()
    before = BillingService().get_balance(db_session, acc.id).balance_units
    svc = _fake_review_service(fail_vk=True)
    result = svc.publish_now(db_session, post.id, confirm=True)
    assert result["blocked"] is False
    assert result["published"] is True
    assert result["partial"] is True
    assert result["units_charged"] == 5  # списано ровно один раз
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert after == before - 5
    events = post_feedback_repository.list_for_post(db_session, post.id)
    assert any(e.event_type == "published" for e in events)
