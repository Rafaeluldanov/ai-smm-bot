"""Anti-free-use платежей (HTTP): счёт не даёт units до оплаты, чужой счёт недоступен."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.repositories import account_repository, user_repository


def _account(db: Session, email: str, slug: str) -> tuple[int, str]:
    user = user_repository.create_user(db, email=email, password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    return account.id, make_dev_token(user.id)


def _h(token: str) -> dict[str, str]:
    return {"Authorization": token}


@pytest.fixture()
def two_accounts(db_session: Session):  # noqa: ANN201
    a_id, a_tok = _account(db_session, "a@e.com", "acc-a")
    b_id, b_tok = _account(db_session, "b@e.com", "acc-b")
    return {"a": (a_id, a_tok), "b": (b_id, b_tok)}


def _balance(client: TestClient, account_id: int, token: str) -> int:
    r = client.get(f"/billing/account/{account_id}/balance", headers=_h(token))
    assert r.status_code == 200
    return r.json()["balance_units"]


def test_create_invoice_does_not_credit(client: TestClient, two_accounts) -> None:  # noqa: ANN001
    account_id, token = two_accounts["a"]
    r = client.post(
        f"/billing/account/{account_id}/invoices",
        json={"amount_units": 500, "method": "bank_card"},
        headers=_h(token),
    )
    assert r.status_code == 200
    assert _balance(client, account_id, token) == 0  # счёт не дал units


def test_mock_pay_credits_via_http(client: TestClient, two_accounts) -> None:  # noqa: ANN001
    account_id, token = two_accounts["a"]
    inv = client.post(
        f"/billing/account/{account_id}/invoices",
        json={"amount_units": 500, "method": "bank_card"},
        headers=_h(token),
    ).json()
    r = client.post(f"/billing/invoices/{inv['id']}/mock-pay", headers=_h(token))
    assert r.status_code == 200 and r.json()["status"] == "paid"
    assert _balance(client, account_id, token) == 500


def test_cannot_pay_other_accounts_invoice(client: TestClient, two_accounts) -> None:  # noqa: ANN001
    a_id, a_tok = two_accounts["a"]
    _, b_tok = two_accounts["b"]
    inv = client.post(
        f"/billing/account/{a_id}/invoices",
        json={"amount_units": 500, "method": "bank_card"},
        headers=_h(a_tok),
    ).json()
    # Пользователь B не видит и не может оплатить счёт аккаунта A → 404.
    r = client.post(f"/billing/invoices/{inv['id']}/mock-pay", headers=_h(b_tok))
    assert r.status_code == 404
    # Баланс A не изменился.
    assert _balance(client, a_id, a_tok) == 0


def test_failed_invoice_no_credit_via_http(client: TestClient, two_accounts) -> None:  # noqa: ANN001
    account_id, token = two_accounts["a"]
    inv = client.post(
        f"/billing/account/{account_id}/invoices",
        json={"amount_units": 500, "method": "sbp"},
        headers=_h(token),
    ).json()
    client.post(f"/billing/invoices/{inv['id']}/mock-fail", headers=_h(token))
    assert _balance(client, account_id, token) == 0
