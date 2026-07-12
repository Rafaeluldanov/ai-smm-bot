"""Тесты UI предложений экспериментов (v0.4.3, offline).

Проверяют рендер страницы «Рекомендации worker-а», предупреждение об отсутствии
live-публикаций, вход из оптимизации и карточку дашборда. Токенов/секретов в UI нет.
"""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.repositories import account_repository, project_repository, user_repository
from app.schemas.project import ProjectCreate
from app.services.platform_connection_service import PlatformConnectionService

_SECRET_TOKEN = "987654321:ZZtopSECRETtelegramTOKENxyz"


def test_suggestions_page_renders(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiment-suggestions").text
    assert "Рекомендации worker-а" in body
    assert "Активные предложения" in body


def test_page_warns_no_live_publish(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiment-suggestions").text
    assert "Live-публикаций нет" in body
    assert "очередь ревью" in body


def test_page_has_generate_and_preview(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiment-suggestions").text
    assert "Сгенерировать предложения" in body
    assert "Preview" in body
    # Обращается к безопасным API-эндпоинтам.
    assert "/experiment-suggestions/projects/'+PID+'/generate" in body


def test_page_has_accept_reject_create_actions(client: TestClient) -> None:
    body = client.get("/ui/projects/1/experiment-suggestions").text
    assert "esAccept" in body
    assert "esReject" in body
    assert "esCreate" in body
    assert "Создать A/B тест" in body


def test_optimization_links_worker_suggestions(client: TestClient) -> None:
    body = client.get("/ui/projects/1/optimization").text
    assert "Предложения worker-а" in body
    assert "/ui/projects/1/experiment-suggestions" in body


def test_scheduler_shows_suggestions_summary(client: TestClient) -> None:
    body = client.get("/ui/scheduler").text
    assert "experiment_suggestions" in body or "Предложения" in body


def test_ui_contains_no_publish_due_action(client: TestClient) -> None:
    # Безопасность: страница не предлагает live-публикацию.
    body = client.get("/ui/projects/1/experiment-suggestions").text
    assert "publish-due" not in body
    assert "publish_due" not in body
    assert "/publish/" not in body


def test_ui_has_no_raw_tokens(client: TestClient, db_session: Session) -> None:
    # Проект с подключённой платформой (секретный токен) — токен не должен утечь в HTML.
    user = user_repository.create_user(db_session, email="uisec@e.com", password_hash="x")
    account = account_repository.create_account(
        db_session, name="uisec", slug="uisec", owner_user_id=user.id
    )
    project = project_repository.create_project(
        db_session, ProjectCreate(name="uisec", slug="uisec-proj")
    )
    project.account_id = account.id
    db_session.commit()
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    body = client.get(f"/ui/projects/{project.id}/experiment-suggestions").text
    assert _SECRET_TOKEN not in body
    assert "api_key" not in body
