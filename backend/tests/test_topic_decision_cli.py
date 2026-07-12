"""Тесты CLI автовыбора темы (v0.4.4). Offline; dry-run по умолчанию; без секретов."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    post_repository,
    project_repository,
    schedule_topic_decision_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.scripts import topic_decision_create, topic_decision_dashboard, topic_decision_preview
from app.services.client_learning_service import ClientLearningService
from app.services.platform_connection_service import PlatformConnectionService

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо"]
_SECRET_TOKEN = "555000111:cliTOPICsecrettoken"


def _seed(db: Session, slug: str = "clitd"):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    cfg = crm.create_config(db, CrmBotProjectConfigCreate(project_id=project.id, display_name=slug))
    cat = crm.create_category(
        db,
        CrmPromotionCategoryCreate(
            project_id=project.id,
            config_id=cfg.id,
            title="Мерч",
            cta="Заказать",
            media_tags=["мерч"],
        ),
    )
    learn = ClientLearningService()
    for t in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=t,
                status="needs_review",
                vk_text="T",
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return account, project, cat


def test_scripts_import() -> None:
    assert callable(topic_decision_preview.main)
    assert callable(topic_decision_create.main)
    assert callable(topic_decision_dashboard.main)


def test_create_parser_dry_run_default_true() -> None:
    args = topic_decision_create.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert topic_decision_create._is_true(args.dry_run) is True


def test_preview_cli_prints_topic(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _cat = _seed(db_session)
    monkeypatch.setattr(topic_decision_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["topic_decision_preview", "--project-id", str(project.id), "--platform", "telegram"],
    )
    topic_decision_preview.main()
    out = capsys.readouterr().out
    assert "тема:" in out.lower()
    assert schedule_topic_decision_repository.list_for_project(db_session, project.id) == []


def test_create_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _cat = _seed(db_session)
    monkeypatch.setattr(topic_decision_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["topic_decision_create", "--project-id", str(project.id), "--platform", "telegram"],
    )
    topic_decision_create.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert schedule_topic_decision_repository.list_for_project(db_session, project.id) == []


def test_create_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _cat = _seed(db_session)
    monkeypatch.setattr(topic_decision_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        [
            "topic_decision_create",
            "--project-id",
            str(project.id),
            "--platform",
            "telegram",
            "--dry-run",
            "false",
        ],
    )
    topic_decision_create.main()
    out = capsys.readouterr().out
    assert "Пост не создан" in out
    assert len(schedule_topic_decision_repository.list_for_project(db_session, project.id)) == 1


def test_dashboard_cli_prints_summary(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _cat = _seed(db_session)
    monkeypatch.setattr(topic_decision_dashboard, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["topic_decision_dashboard", "--project-id", str(project.id)])
    topic_decision_dashboard.main()
    assert "Сводка решений" in capsys.readouterr().out


def test_cli_prints_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project, _cat = _seed(db_session)
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    monkeypatch.setattr(topic_decision_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["topic_decision_preview", "--project-id", str(project.id), "--platform", "telegram"],
    )
    topic_decision_preview.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
    assert "api_key" not in out
