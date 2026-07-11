"""Тесты CLI A/B-экспериментов и рекомендаций (v0.4.2)."""

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.repositories import (
    account_repository,
    content_experiment_repository,
    project_repository,
    user_repository,
)
from app.schemas.project import ProjectCreate
from app.scripts import (
    choose_experiment_winner,
    create_ab_experiment,
    score_experiment,
    topic_recommendations,
)
from app.services.ab_testing_service import ABTestingService
from app.services.billing_service import BillingService


def test_scripts_import() -> None:
    assert callable(topic_recommendations.main)
    assert callable(create_ab_experiment.main)
    assert callable(score_experiment.main)
    assert callable(choose_experiment_winner.main)


def test_topic_parser() -> None:
    args = topic_recommendations.build_parser().parse_args(
        ["--project-id", "1", "--platform", "telegram", "--limit", "5"]
    )
    assert args.project_id == 1
    assert args.limit == 5


def test_create_parser_dry_run_default_true() -> None:
    args = create_ab_experiment.build_parser().parse_args(["--project-id", "1", "--topic", "Тест"])
    assert args.dry_run == "true"
    assert create_ab_experiment._is_true(args.dry_run) is True


def test_winner_parser_dry_run_default_true() -> None:
    args = choose_experiment_winner.build_parser().parse_args(["--experiment-id", "1"])
    assert args.dry_run == "true"
    assert args.method == "auto"


def _seed(db: Session):  # noqa: ANN202
    user = user_repository.create_user(db, email="cli@e.com", password_hash="x")
    account = account_repository.create_account(db, name="cli", slug="cli-a", owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name="cli", slug="cli-proj"))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key="cli")
    db.commit()
    return account, project


def test_topic_recommendations_cli_prints(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(topic_recommendations, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["topic_recommendations", "--project-id", str(project.id)])
    topic_recommendations.main()
    assert "Рекомендации тем" in capsys.readouterr().out


def test_create_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    monkeypatch.setattr(create_ab_experiment, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv",
        ["create_ab_experiment", "--project-id", str(project.id), "--topic", "Футболки"],
    )
    create_ab_experiment.main()
    assert "DRY-RUN" in capsys.readouterr().out
    # dry-run не создаёт экспериментов
    assert content_experiment_repository.list_experiments_for_project(db_session, project.id) == []


def test_score_cli_works(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    created = ABTestingService().create_experiment_from_topic(db_session, project.id, "vk", "Тема")
    eid = created["experiment"]["id"]
    monkeypatch.setattr(score_experiment, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr("sys.argv", ["score_experiment", "--experiment-id", str(eid)])
    score_experiment.main()
    assert "Скоринг эксперимента" in capsys.readouterr().out


def test_winner_cli_dry_run_no_writes(
    db_session: Session,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _acc, project = _seed(db_session)
    created = ABTestingService().create_experiment_from_topic(db_session, project.id, "vk", "Тема")
    eid = created["experiment"]["id"]
    monkeypatch.setattr(choose_experiment_winner, "get_sessionmaker", lambda: session_factory)
    monkeypatch.setattr(
        "sys.argv", ["choose_experiment_winner", "--experiment-id", str(eid), "--method", "auto"]
    )
    choose_experiment_winner.main()
    assert "DRY-RUN" in capsys.readouterr().out
    # dry-run не выбирает winner (эксперимент остаётся active)
    exp = content_experiment_repository.get_experiment_by_id(db_session, eid)
    assert exp.status == "active"
