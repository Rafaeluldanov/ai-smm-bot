"""Тесты сервиса предложений экспериментов (v0.4.3).

Offline, без внешних API и live-публикаций. Проверяют генерацию/приём/создание A/B,
дедуп, лимиты, изоляцию проектов и сигналы обучения.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    client_learning_repository,
    content_experiment_repository,
    experiment_suggestion_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.billing_service import BillingService, InsufficientBalanceError
from app.services.client_learning_service import ClientLearningService
from app.services.experiment_suggestion_service import (
    ExperimentSuggestionError,
    ExperimentSuggestionService,
)

_TOPICS = [
    "Футболки с логотипом",
    "Худи осень",
    "Акция мерч",
    "Кружки промо",
    "Стикеры бренд",
    "Кепки лето",
]


def _seed(db: Session, slug: str, topup: int = 500, topics: list[str] | None = None):  # noqa: ANN202
    """Проект с обученным профилем (одобренные темы → publish_more ≥ 0.55)."""
    user = user_repository.create_user(db, email=f"{slug}@e.com", password_hash="x")
    account = account_repository.create_account(db, name=slug, slug=slug, owner_user_id=user.id)
    project = project_repository.create_project(db, ProjectCreate(name=slug, slug=slug))
    project.account_id = account.id
    db.commit()
    if topup:
        BillingService().manual_topup(db, account.id, topup, idempotency_key=f"seed-{slug}")
        db.commit()
    learn = ClientLearningService()
    for title in topics or _TOPICS:
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
    return account, project, user


def _svc(**flags: object) -> ExperimentSuggestionService:
    return ExperimentSuggestionService(settings=Settings(**flags))


def test_preview_no_writes(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-prev")
    result = _svc().preview_suggestions(db_session, project.id)
    assert result["writes"] is False
    assert len(result["suggestions"]) > 0
    # Ничего не записано в БД.
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 0


def test_generate_creates_proposed(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-gen")
    result = _svc().generate_suggestions(db_session, project.id)
    assert result["created"] > 0
    rows = experiment_suggestion_repository.list_for_project(db_session, project.id)
    assert all(r.status == "proposed" for r in rows)
    assert all(r.confidence_score >= 0.55 for r in rows)


def test_generate_dedup_cooldown(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-dedup")
    # max_per_tick ≥ числа тем, чтобы первый прогон захватил все — второй ничего не добавит.
    svc = _svc(experiment_suggestions_cooldown_hours=24, experiment_suggestions_max_per_tick=10)
    first = svc.generate_suggestions(db_session, project.id)
    second = svc.generate_suggestions(db_session, project.id)
    assert first["created"] == len(_TOPICS)
    # Те же темы в окне cooldown → повторно не создаются.
    assert second["created"] == 0
    assert second["skipped"] >= first["created"]


def test_min_confidence_filters(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-minconf")
    # Порог выше максимально достижимого (0.62) → ни одного предложения.
    result = _svc(experiment_suggestions_min_confidence=0.99).generate_suggestions(
        db_session, project.id
    )
    # Кандидаты были (scanned>0), но все отфильтрованы по уверенности — не «пусто на входе».
    assert result["scanned"] > 0
    assert result["created"] == 0
    assert result["skipped"] == result["scanned"]


def test_max_per_tick_cap(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-cap")
    result = _svc(experiment_suggestions_max_per_tick=2).generate_suggestions(
        db_session, project.id
    )
    assert result["created"] == 2


def test_max_active_cap(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-active")
    # 6 тем в сиде, max_per_tick=10 → без ограничения создалось бы 6; кап active=3 связывает.
    svc = _svc(
        experiment_suggestions_max_active_per_project=3, experiment_suggestions_max_per_tick=10
    )
    result = svc.generate_suggestions(db_session, project.id)
    assert result["created"] == 3  # ровно кап, не больше и не меньше
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 3


def test_accept_marks_and_learns(db_session: Session) -> None:
    acc, project, user = _seed(db_session, "sug-accept")
    # НОВАЯ тема, которой заведомо нет в preferred_topics профиля — чтобы приём
    # действительно должен был её туда добавить (иначе тест был бы тавтологичным:
    # темы publish_more уже лежат в preferred).
    novel = "Совершенно новая тема про носки"
    before = client_learning_repository.get_profile(db_session, project.id, None)
    assert novel not in (before.preferred_topics or [])
    suggestion = experiment_suggestion_repository.create_suggestion(
        db_session,
        account_id=acc.id,
        project_id=project.id,
        platform_key=None,
        suggestion_type="publish_more",
        source="manual",
        status="proposed",
        topic=novel,
        title=f"Тест: {novel}",
        reason="тест",
        confidence_score=0.9,
    )
    view = _svc().accept_suggestion(db_session, suggestion.id, current_user_id=user.id)
    assert view["status"] == "accepted"
    profile = client_learning_repository.get_profile(db_session, project.id, None)
    assert novel in (profile.preferred_topics or [])  # приём реально подвинул профиль


def test_reject_marks_and_learns(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-reject")
    created = _svc().generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    topic = created["suggestions"][0]["topic"]
    view = _svc().reject_suggestion(db_session, sid, reason="не подходит")
    assert view["status"] == "rejected"
    profile = client_learning_repository.get_profile(db_session, project.id, None)
    assert topic in (profile.rejected_topics or [])


def test_dismiss_marks(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-dismiss")
    created = _svc().generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    view = _svc().dismiss_suggestion(db_session, sid)
    assert view["status"] == "dismissed"
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) < len(
        created["suggestions"]
    )


def test_create_experiment_charges_and_links(db_session: Session) -> None:
    acc, project, user = _seed(db_session, "sug-create")
    svc = _svc()
    created = svc.generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    before = BillingService().get_balance(db_session, acc.id).balance_units
    result = svc.create_experiment_from_suggestion(db_session, sid, current_user_id=user.id)
    after = BillingService().get_balance(db_session, acc.id).balance_units
    assert result["experiment_id"] is not None
    assert result["outcome"] == "created"
    assert before - after == 10  # цена создания A/B
    # Связь suggestion ↔ experiment.
    experiment = content_experiment_repository.get_experiment_by_id(
        db_session, result["experiment_id"]
    )
    assert experiment.experiment_metadata.get("suggestion_id") == sid
    suggestion = experiment_suggestion_repository.get_by_id(db_session, sid)
    assert suggestion.status == "experiment_created"


def test_create_experiment_no_live_publish(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-nolive")
    svc = _svc()
    created = svc.generate_suggestions(db_session, project.id)
    result = svc.create_experiment_from_suggestion(db_session, created["suggestions"][0]["id"])
    variants = content_experiment_repository.list_variants_for_experiment(
        db_session, result["experiment_id"]
    )
    assert variants
    for v in variants:
        post = post_repository.get_post_by_id(db_session, v.post_id)
        assert post.status == "needs_review"
        assert post.published_at is None  # live-публикации нет


def test_create_experiment_idempotent(db_session: Session) -> None:
    acc, project, _u = _seed(db_session, "sug-idem")
    svc = _svc()
    created = svc.generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    first = svc.create_experiment_from_suggestion(db_session, sid)
    bal1 = BillingService().get_balance(db_session, acc.id).balance_units
    second = svc.create_experiment_from_suggestion(db_session, sid)
    bal2 = BillingService().get_balance(db_session, acc.id).balance_units
    assert first["experiment_id"] == second["experiment_id"]
    assert second["outcome"] == "skipped_duplicate"
    assert bal1 == bal2  # без двойного списания


def test_create_experiment_insufficient_balance(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-poor", topup=0)
    svc = _svc()
    created = svc.generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    try:
        svc.create_experiment_from_suggestion(db_session, sid)
        raise AssertionError("ожидали InsufficientBalanceError")
    except InsufficientBalanceError:
        pass
    # Предложение не помечено как experiment_created.
    assert (
        experiment_suggestion_repository.get_by_id(db_session, sid).status != "experiment_created"
    )


def test_missing_suggestion_raises(db_session: Session) -> None:
    try:
        _svc().accept_suggestion(db_session, 999999)
        raise AssertionError("ожидали ExperimentSuggestionError")
    except ExperimentSuggestionError:
        pass


def test_project_isolation(db_session: Session) -> None:
    _a1, p1, _u1 = _seed(db_session, "sug-iso1")
    _a2, p2, _u2 = _seed(db_session, "sug-iso2")
    _svc().generate_suggestions(db_session, p1.id)
    # Предложения проекта 1 не видны из проекта 2.
    assert experiment_suggestion_repository.list_for_project(db_session, p2.id) == []
    assert experiment_suggestion_repository.count_active_for_project(db_session, p1.id) > 0


def test_worker_disabled_by_default(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-wdis")
    # Дефолтные настройки: worker выключен → ничего не создаётся.
    result = ExperimentSuggestionService(settings=Settings()).run_worker_suggestions_for_project(
        db_session, project.id, dry_run=False
    )
    assert result["enabled"] is False
    assert result["created"] == 0
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 0


def test_feature_kill_switch_blocks_generate(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-killgen")
    # Мастер-выключатель фичи выключает и ручную генерацию (не только worker).
    result = _svc(experiment_suggestions_enabled=False).generate_suggestions(db_session, project.id)
    assert result["created"] == 0
    assert result.get("disabled") is True
    assert experiment_suggestion_repository.count_active_for_project(db_session, project.id) == 0


def test_feature_kill_switch_blocks_preview(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-killprev")
    result = _svc(experiment_suggestions_enabled=False).preview_suggestions(db_session, project.id)
    assert result["suggestions"] == []
    assert result.get("disabled") is True


def test_create_experiment_rejected_status_blocked(db_session: Session) -> None:
    acc, project, _u = _seed(db_session, "sug-rejstat")
    svc = _svc()
    created = svc.generate_suggestions(db_session, project.id)
    sid = created["suggestions"][0]["id"]
    svc.reject_suggestion(db_session, sid)
    before = BillingService().get_balance(db_session, acc.id).balance_units
    # Из отклонённого предложения нельзя создать A/B (и units не тратятся).
    try:
        svc.create_experiment_from_suggestion(db_session, sid)
        raise AssertionError("ожидали ExperimentSuggestionError")
    except ExperimentSuggestionError:
        pass
    assert BillingService().get_balance(db_session, acc.id).balance_units == before


def test_cooldown_reproposal_after_window(db_session: Session) -> None:
    _acc, project, _u = _seed(db_session, "sug-reprop")
    # cooldown=0 → окно повторов закрыто: та же тема может быть предложена снова.
    svc = _svc(experiment_suggestions_cooldown_hours=0, experiment_suggestions_max_per_tick=10)
    first = svc.generate_suggestions(db_session, project.id)
    second = svc.generate_suggestions(db_session, project.id)
    assert first["created"] == len(_TOPICS)
    assert second["created"] == len(_TOPICS)  # cooldown не блокирует — повтор разрешён
