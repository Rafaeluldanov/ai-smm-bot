"""Тесты CLI предложений экспериментов (v0.4.3).

Offline; dry-run по умолчанию; секретов не печатаем; live-публикаций нет.
"""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    experiment_suggestion_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.scripts import (
    experiment_suggestion_accept,
    experiment_suggestion_create,
    experiment_suggestions_generate,
    experiment_suggestions_preview,
)
from app.services.billing_service import BillingService
from app.services.client_learning_service import ClientLearningService
from app.services.experiment_suggestion_service import ExperimentSuggestionService
from app.services.platform_connection_service import PlatformConnectionService

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры бренд"]
_SECRET_TOKEN = "555000111:cliSECRETtelegramTOKENabc"


def _seed(db: Session, slug: str = "clis", topup: int = 500):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
    learn = ClientLearningService()
    for title in _TOPICS:
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=title,
                status="needs_review",
                vk_text="Текст про " + title,
                hashtags=["мерч"],
            ),
        )
        db.commit()
        learn.record_review_feedback(db, post.id, "approved")
        db.commit()
    learn.build_learning_profile(db, project.id)
    db.commit()
    return account, project


def test_scripts_import() -> None:
    assert callable(experiment_suggestions_preview.main)
    assert callable(experiment_suggestions_generate.main)
    assert callable(experiment_suggestion_accept.main)
    assert callable(experiment_suggestion_create.main)


def test_generate_parser_dry_run_default_true() -> None:
    args = experiment_suggestions_generate.build_parser().parse_args(["--project-id", "1"])
    assert args.dry_run == "true"
    assert experiment_suggestions_generate._is_true(args.dry_run) is True


def test_create_parser_dry_run_default_true() -> None:
    args = experiment_suggestion_create.build_parser().parse_args(["--suggestion-id", "1"])
    assert args.dry_run == "true"


def test_preview_cli_prints(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(experiment_suggestions_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["experiment_suggestions_preview", "--project-id", str(project.id)]
    )
    experiment_suggestions_preview.main()
    out = capsys.readouterr().out
    assert "кандидат" in out.lower() or "preview" in out.lower()
    # Preview ничего не пишет.
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 0


def test_generate_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(
        experiment_suggestions_generate, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv", ["experiment_suggestions_generate", "--project-id", str(project.id)]
    )
    experiment_suggestions_generate.main()
    assert "DRY-RUN" in capsys.readouterr().out
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 0


def test_generate_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(
        experiment_suggestions_generate, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv",
        ["experiment_suggestions_generate", "--project-id", str(project.id), "--dry-run", "false"],
    )
    experiment_suggestions_generate.main()
    assert "создано" in capsys.readouterr().out.lower()
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) > 0


def test_accept_cli(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    gen = ExperimentSuggestionService().generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    monkeypatch.setattr(experiment_suggestion_accept, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["experiment_suggestion_accept", "--suggestion-id", str(sid)])
    experiment_suggestion_accept.main()
    assert "принято" in capsys.readouterr().out.lower()
    assert experiment_suggestion_repository.get_by_id(db_session, sid).status == "accepted"


def test_create_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    gen = ExperimentSuggestionService().generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    monkeypatch.setattr(experiment_suggestion_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["experiment_suggestion_create", "--suggestion-id", str(sid)])
    experiment_suggestion_create.main()
    assert "DRY-RUN" in capsys.readouterr().out
    # dry-run не создаёт эксперимент.
    assert (
        experiment_suggestion_repository.get_by_id(db_session, sid).status != "experiment_created"
    )


def test_create_cli_writes_when_not_dry(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    gen = ExperimentSuggestionService().generate_suggestions(db_session, project.id)
    sid = gen["suggestions"][0]["id"]
    monkeypatch.setattr(experiment_suggestion_create, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["experiment_suggestion_create", "--suggestion-id", str(sid), "--dry-run", "false"],
    )
    experiment_suggestion_create.main()
    out = capsys.readouterr().out
    assert "Live-публикаций нет" in out
    assert (
        experiment_suggestion_repository.get_by_id(db_session, sid).status == "experiment_created"
    )


def test_cli_prints_no_secrets(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    # Проект с подключённой платформой (секретный токен) — CLI не должен его печатать.
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": _SECRET_TOKEN, "external_id": "@t"}
    )
    db_session.commit()
    monkeypatch.setattr(experiment_suggestions_preview, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        experiment_suggestions_generate, "get_sessionmaker", lambda: session_factory
    )
    monkeypatch.setattr(
        "sys.argv", ["experiment_suggestions_preview", "--project-id", str(project.id)]
    )
    experiment_suggestions_preview.main()
    monkeypatch.setattr(
        "sys.argv",
        ["experiment_suggestions_generate", "--project-id", str(project.id), "--dry-run", "false"],
    )
    experiment_suggestions_generate.main()
    out = capsys.readouterr().out
    assert _SECRET_TOKEN not in out
    assert "api_key" not in out
