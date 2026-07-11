"""Тесты сервиса импорта метрик (v0.4.1, offline — без сети)."""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    analytics_repository,
    client_learning_repository,
    post_feedback_repository,
    post_publication_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.post_publication import PostPublicationCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService
from app.services.metrics_import_service import MetricsImportService


def _seed(db: Session, slug: str, posts: int = 2):  # noqa: ANN202
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    BillingService().manual_topup(db, account.id, 500, idempotency_key=f"seed-{slug}")
    pubs = []
    for i in range(posts):
        post = post_repository.create_post(
            db,
            PostCreate(
                project_id=project.id,
                title=f"Пост {i}",
                status="scheduled",
                vk_text=f"Заказать мерч {i} за 990 руб #мерч",
                hashtags=["мерч"],
            ),
        )
        post.scheduled_at = datetime(2026, 7, 13, 18, 0, tzinfo=UTC)
        pub = post_publication_repository.create_publication(
            db,
            PostPublicationCreate(
                post_id=post.id,
                project_id=project.id,
                platform="vk",
                target_id="-1",
                status="scheduled",
            ),
        )
        pubs.append(pub)
    db.commit()
    return account, project, pubs


def test_preview_no_writes(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-prev")
    svc = MetricsImportService()
    before = len(analytics_repository.list_snapshots_for_project(db_session, project.id))
    result = svc.preview_import(db_session, project.id, source="demo")
    assert result["writes"] is False
    assert result["publications_found"] == 2
    after = len(analytics_repository.list_snapshots_for_project(db_session, project.id))
    assert before == after == 0


def test_demo_import_creates_snapshots(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-demo")
    svc = MetricsImportService()
    result = svc.run_import(db_session, project.id, source="demo", idempotency_key="d1")
    assert result["outcome"] == "imported"
    assert result["snapshots_created"] == 2
    snaps = analytics_repository.list_snapshots_for_project(db_session, project.id)
    assert len(snaps) == 2
    assert all(s.source == "demo" for s in snaps)


def test_demo_import_is_free(db_session: Session) -> None:
    acc, project, _pubs = _seed(db_session, "mi-free")
    before = BillingService().get_balance(db_session, acc.id).balance_units
    MetricsImportService().run_import(db_session, project.id, source="demo", idempotency_key="f1")
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert before == after


def test_run_import_creates_feedback_event(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-fb")
    MetricsImportService().run_import(db_session, project.id, source="demo", idempotency_key="fb1")
    counts = post_feedback_repository.aggregate_by_project(db_session, project.id)
    assert counts.get("analytics_imported") == 2


def test_learning_profile_updated(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-learn")
    MetricsImportService().run_import(db_session, project.id, source="demo", idempotency_key="l1")
    profile = client_learning_repository.get_profile(db_session, project.id, None)
    assert profile is not None
    assert "мерч" in profile.high_performing_tags


def test_api_disabled_returns_skipped(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-api")
    result = MetricsImportService().run_import(
        db_session, project.id, platform_key="vk", source="api", idempotency_key="a1"
    )
    assert result["outcome"] == "skipped"
    assert result["snapshots_created"] == 0


def test_manual_metrics_free_and_creates_snapshot(db_session: Session) -> None:
    acc, project, pubs = _seed(db_session, "mi-man")
    before = BillingService().get_balance(db_session, acc.id).balance_units
    result = MetricsImportService().save_manual_metrics(
        db_session,
        pubs[0].id,
        {"views": 2000, "reach": 1500, "likes": 100, "clicks": 40, "impressions": 1800},
    )
    assert result["units_charged"] == 0
    assert result["er_percent"] is not None
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert before == after
    snaps = analytics_repository.list_snapshots(db_session, post_id=pubs[0].post_id)
    assert any(s.source == "manual" for s in snaps)


def test_idempotency_no_duplicate_import(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-idem")
    svc = MetricsImportService()
    first = svc.run_import(db_session, project.id, source="demo", idempotency_key="same")
    second = svc.run_import(db_session, project.id, source="demo", idempotency_key="same")
    assert first["outcome"] == "imported"
    assert second["outcome"] == "skipped_duplicate"
    snaps = analytics_repository.list_snapshots_for_project(db_session, project.id)
    assert len(snaps) == 2  # без дубля


def test_idempotency_retry_after_skip_does_not_crash(db_session: Session) -> None:
    """Повтор с тем же ключом после неуспешного (skipped) прогона не падает на unique."""
    _acc, project, _pubs = _seed(db_session, "mi-retry")
    svc = MetricsImportService()
    # api при выключенном флаге → skipped (неуспешный прогон с ключом "same-key").
    first = svc.run_import(
        db_session, project.id, platform_key="vk", source="api", idempotency_key="same-key"
    )
    assert first["outcome"] == "skipped"
    # Повтор тем же ключом (теперь demo) — должен переиспользовать строку, не упасть.
    second = svc.run_import(db_session, project.id, source="demo", idempotency_key="same-key")
    assert second["outcome"] == "imported"
    assert second["snapshots_created"] == 2


def test_no_cross_project_mixing(db_session: Session) -> None:
    _a1, proj_a, _pa = _seed(db_session, "mi-a")
    _a2, proj_b, _pb = _seed(db_session, "mi-b")
    MetricsImportService().run_import(db_session, proj_a.id, source="demo", idempotency_key="xa")
    snaps_b = analytics_repository.list_snapshots_for_project(db_session, proj_b.id)
    assert len(snaps_b) == 0


def test_rebuild_dry_run_free_and_no_version_bump(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-rb")
    svc = MetricsImportService()
    svc.run_import(db_session, project.id, source="demo", idempotency_key="rb1")
    v_before = client_learning_repository.get_profile(db_session, project.id, None).profile_version
    result = svc.rebuild_learning_from_metrics(db_session, project.id, dry_run=True)
    assert result["units_charged"] == 0
    v_after = client_learning_repository.get_profile(db_session, project.id, None).profile_version
    assert v_after == v_before  # dry-run не поднимает версию


def test_rebuild_paid_charges_and_bumps_version(db_session: Session) -> None:
    acc, project, _pubs = _seed(db_session, "mi-rbp")
    svc = MetricsImportService()
    svc.run_import(db_session, project.id, source="demo", idempotency_key="rbp1")
    v_before = client_learning_repository.get_profile(db_session, project.id, None).profile_version
    before = BillingService().get_balance(db_session, acc.id).balance_units
    result = svc.rebuild_learning_from_metrics(db_session, project.id, dry_run=False)
    assert result["units_charged"] == 5
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert after == before - 5
    v_after = client_learning_repository.get_profile(db_session, project.id, None).profile_version
    assert v_after == v_before + 1


def test_dashboard_summary(db_session: Session) -> None:
    _acc, project, _pubs = _seed(db_session, "mi-dash")
    svc = MetricsImportService()
    svc.run_import(db_session, project.id, source="demo", idempotency_key="dsh")
    dash = svc.build_metrics_dashboard(db_session, project.id, {})
    assert dash["with_metrics_count"] == 2
    assert dash["avg_er_percent"] is not None
    assert dash["source_breakdown"].get("demo") == 2
