"""HTTP-тесты защиты платных действий (v0.3.1): баланс, идемпотентность, оплата.

dry-run бесплатен; недостаток баланса блокирует; успех списывает один раз; повтор по
idempotency_key не списывает дважды; неуспех не списывает; счёт не пополняет до оплаты;
mock-pay пополняет один раз; дубликат mock-pay не пополняет дважды.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate


def _setup(db: Session, balance: int = 0):  # noqa: ANN202
    user = user_repository.create_user(db, email="p@e.com", password_hash="x")
    account = account_repository.create_account(db, name="Acc", slug="acc", owner_user_id=user.id)
    account_repository.create_membership(db, account.id, user.id, role="owner")
    project = project_repository.create_project(db, ProjectCreate(name="Proj", slug="proj"))
    project.account_id = account.id
    db.commit()
    post_repository.create_post(
        db, PostCreate(project_id=project.id, title="t", telegram_text="hi", status="published")
    )
    ctx = {"uid": user.id, "aid": account.id, "pid": project.id}
    if balance:
        # Пополнение баланса напрямую (owner может manual-topup, но проще через сервис).
        from app.services.billing_service import BillingService

        b = BillingService()
        b.get_or_create_billing_account(db, account.id)
        b.manual_topup(db, account.id, balance, idempotency_key="seed")
    return ctx


def _h(uid: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(uid)}


def _balance(client: TestClient, ctx) -> int:  # noqa: ANN001
    return client.get(f"/billing/account/{ctx['aid']}/balance", headers=_h(ctx["uid"])).json()[
        "balance_units"
    ]


def test_dry_run_is_free(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=100)
    r = client.post(
        f"/analytics/accounts/{ctx['aid']}/run-dry",
        headers=_h(ctx["uid"]),
        json={"project_id": ctx["pid"], "depth": "deep"},
    )
    assert r.status_code == 200
    assert r.json()["charged_units"] == 0
    assert _balance(client, ctx) == 100


def test_insufficient_balance_blocks_run(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=5)  # < 10 (light)
    r = client.post(
        f"/analytics/accounts/{ctx['aid']}/run",
        headers=_h(ctx["uid"]),
        json={"project_id": ctx["pid"], "depth": "light", "idempotency_key": "r1"},
    )
    assert r.status_code == 402
    assert _balance(client, ctx) == 5


def test_run_debits_once_and_idempotent(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=100)
    body = {"project_id": ctx["pid"], "depth": "light", "idempotency_key": "run-1"}
    r1 = client.post(f"/analytics/accounts/{ctx['aid']}/run", headers=_h(ctx["uid"]), json=body)
    assert r1.status_code == 200
    assert r1.json()["charged_units"] == 10
    assert _balance(client, ctx) == 90
    # Повтор с тем же ключом — без второго списания.
    client.post(f"/analytics/accounts/{ctx['aid']}/run", headers=_h(ctx["uid"]), json=body)
    assert _balance(client, ctx) == 90


def test_failed_action_does_not_debit(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=100)
    r = client.post(
        f"/analytics/accounts/{ctx['aid']}/run",
        headers=_h(ctx["uid"]),
        json={"project_id": ctx["pid"], "depth": "bogus", "idempotency_key": "bad"},
    )
    assert r.status_code == 422  # неизвестная глубина, до списания
    assert _balance(client, ctx) == 100


def test_invoice_creation_does_not_credit(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=0)
    r = client.post(
        f"/billing/account/{ctx['aid']}/invoices",
        headers=_h(ctx["uid"]),
        json={"amount_units": 500, "method": "bank_card", "idempotency_key": "inv-1"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "pending"
    assert _balance(client, ctx) == 0  # счёт не пополнил баланс


def test_mock_pay_credits_once_and_no_double(client: TestClient, db_session: Session) -> None:
    ctx = _setup(db_session, balance=0)
    inv = client.post(
        f"/billing/account/{ctx['aid']}/invoices",
        headers=_h(ctx["uid"]),
        json={"amount_units": 500, "idempotency_key": "inv-2"},
    ).json()
    client.post(f"/billing/invoices/{inv['id']}/mock-pay", headers=_h(ctx["uid"]))
    assert _balance(client, ctx) == 500
    # Дубликат оплаты — без повторного пополнения.
    client.post(f"/billing/invoices/{inv['id']}/mock-pay", headers=_h(ctx["uid"]))
    assert _balance(client, ctx) == 500
