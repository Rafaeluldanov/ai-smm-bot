"""Тесты безопасности базы SMM-рекомендаций Botfleet (v1.0.1).

Инварианты (Part 12): всё read-only — нет мутаций БД/UsageEvent/платежей/внешних вызовов; slug через
whitelist; path traversal невозможен; путь к ресурсу зафиксирован в коде; project-scoped роут с
tenant-гардом; ответы без секретов и файловых путей; в UI весь текст экранирован.
"""

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.security import make_dev_token
from app.models.billing import UsageEvent
from app.models.business_workflow import BusinessWorkflow
from app.models.crm_bot_smm import CrmSmmResource
from app.models.payment import PaymentInvoice
from app.models.post_publication import PostPublication
from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate

_FORBIDDEN_MODELS = (PostPublication, CrmSmmResource, BusinessWorkflow, PaymentInvoice, UsageEvent)
_SECRET_HINTS = ("password", "secret", "token", "api_key", "access_key", "refresh")
_SERVICE_SRC = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "services"
    / "platform_recommendations_service.py"
).read_text(encoding="utf-8")
_API_SRC = (
    Path(__file__).resolve().parent.parent / "app" / "api" / "platform_recommendations.py"
).read_text(encoding="utf-8")


def _account(db: Session, slug: str) -> tuple[int, int]:
    owner = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=owner.id)
    return account.id, owner.id


def _project(db: Session, account_id: int, slug: str) -> int:
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account_id
    db.commit()
    return project.id


def _h(user_id: int) -> dict[str, str]:
    return {"Authorization": make_dev_token(user_id)}


def _forbidden_counts(db: Session) -> dict[str, int]:
    return {m.__name__: db.query(m).count() for m in _FORBIDDEN_MODELS}


def test_reads_create_no_forbidden_entities(client: TestClient, db_session: Session) -> None:
    """Любые чтения рекомендаций НЕ создают публикаций/CRM/workflow/платежей/списаний."""
    before = _forbidden_counts(db_session)
    client.get("/platform-recommendations")
    client.get("/platform-recommendations/universal")
    client.get("/platform-recommendations/telegram")
    client.get("/platform-recommendations/odnoklassniki")
    assert _forbidden_counts(db_session) == before


def test_service_has_no_network_or_mutation_imports() -> None:
    """Сервис/API не импортируют сеть и не пишут в БД (структурный allowlist)."""
    for src in (_SERVICE_SRC, _API_SRC):
        lowered = src.lower()
        for banned in ("httpx", "requests", "urllib", "socket", "http://", "https://"):
            assert banned not in lowered
    # Сервис не пишет в БД и не списывает units.
    for banned in ("session", "db.add", "db.commit", "usageevent", "billing", "audit"):
        assert banned not in _SERVICE_SRC.lower()


def test_resource_path_is_fixed_in_code() -> None:
    """Путь к ресурсу зафиксирован (app/resources/...), не строится из пользовательского ввода."""
    from app.services import platform_recommendations_service as mod

    assert mod._RESOURCE_PATH.is_absolute()
    assert mod._RESOURCE_PATH.parent.name == "resources"
    assert mod._RESOURCE_PATH.name == "botfleet_smm_recommendations_2026.json"


def test_path_traversal_via_api_404(client: TestClient) -> None:
    for attack in ["..%2f..%2fetc%2fpasswd", "telegram%2f..%2f..", "....//secret"]:
        assert client.get(f"/platform-recommendations/{attack}").status_code == 404


def test_unknown_slug_never_becomes_file_path(client: TestClient) -> None:
    """Неизвестный slug → 404 и ответ не содержит файловых путей."""
    r = client.get("/platform-recommendations/etc_passwd")
    assert r.status_code == 404
    assert "/Users/" not in r.text and "resources" not in r.text and ".json" not in r.text


def test_project_scoped_route_has_tenant_guard(client: TestClient, db_session: Session) -> None:
    aid_a, _uid_a = _account(db_session, "secta")
    _aid_b, uid_b = _account(db_session, "sectb")
    pid = _project(db_session, aid_a, "sectproj")
    assert (
        client.get(
            f"/projects/{pid}/platforms/telegram/recommendations", headers=_h(uid_b)
        ).status_code
        == 404
    )


def test_no_secrets_or_file_paths_in_responses(client: TestClient) -> None:
    for path in (
        "/platform-recommendations",
        "/platform-recommendations/universal",
        "/platform-recommendations/telegram",
    ):
        text = client.get(path).text
        low = text.lower()
        for hint in _SECRET_HINTS:
            assert hint not in low
        assert "/users/" not in low
        assert "app/resources" not in low


def test_global_page_has_no_private_project_data(client: TestClient) -> None:
    """Статическая база не содержит account/project/email приватных данных."""
    body = client.get("/platform-recommendations/telegram").json()
    blob = repr(body).lower()
    assert "account_id" not in blob
    assert "project_id" not in blob


def test_ui_pane_has_no_script_injection() -> None:
    from app.api.ui import _platform_recommendations_pane_html

    pane, _ = _platform_recommendations_pane_html("vk")
    assert "<script" not in pane.lower()
    assert "javascript:" not in pane.lower()
    assert "onerror=" not in pane.lower()


def test_routes_registered_without_collision() -> None:
    from app.main import create_app

    paths = set(create_app().openapi()["paths"])
    assert "/platform-recommendations" in paths
    assert "/platform-recommendations/universal" in paths
    assert "/platform-recommendations/{platform_slug}" in paths
    assert "/projects/{project_id}/platforms/{platform_slug}/recommendations" in paths
