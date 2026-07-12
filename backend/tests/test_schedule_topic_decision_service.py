"""Тесты сервиса автовыбора темы (v0.4.4).

Offline, без внешних API и live-публикаций. Проверяют кандидатов, скоринг, объяснение,
запись решения, штрафы (rejected/fatigue), fallback и изоляцию проектов.
"""

from sqlalchemy.orm import Session

from app.config import Settings
from app.repositories import (
    account_repository,
    content_experiment_repository,
    experiment_suggestion_repository,
    post_repository,
    project_repository,
    schedule_topic_decision_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm
from app.schemas.crm_bot_smm import CrmBotProjectConfigCreate, CrmPromotionCategoryCreate
from app.schemas.post import PostCreate
from app.schemas.project import ProjectCreate
from app.services.client_learning_service import ClientLearningService
from app.services.schedule_topic_decision_service import ScheduleTopicDecisionService

_TOPICS = ["Футболки лого", "Худи осень", "Акция мерч", "Кружки промо", "Стикеры", "Кепки лето"]


def _seed(db: Session, slug: str, approve: bool = True):  # noqa: ANN202
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
    if approve:
        for t in _TOPICS:
            post = post_repository.create_post(
                db,
                PostCreate(
                    project_id=project.id,
                    title=t,
                    status="needs_review",
                    vk_text="Текст " + t,
                    hashtags=["мерч"],
                ),
            )
            db.commit()
            learn.record_review_feedback(db, post.id, "approved")
            db.commit()
        learn.build_learning_profile(db, project.id)
        db.commit()
    return account, project, cat


def _svc(**flags: object) -> ScheduleTopicDecisionService:
    return ScheduleTopicDecisionService(settings=Settings(**flags))


def test_preview_no_writes(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-prev")
    result = _svc().preview_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id
    )
    assert result["writes"] is False
    assert result["selected_topic"]
    assert schedule_topic_decision_repository.list_for_project(db_session, project.id) == []


def test_create_decision_writes_row(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-create")
    result = _svc().create_decision_for_plan(db_session, project.id, "telegram", category_id=cat.id)
    assert result["outcome"] == "created"
    rows = schedule_topic_decision_repository.list_for_project(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].status == "selected"


def test_confidence_in_range(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-conf")
    result = _svc().preview_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id
    )
    assert 0.0 <= result["confidence_score"] <= 1.0
    for alt in result["alternatives"]:
        assert 0.0 <= alt["confidence_score"] <= 1.0


def test_decision_uses_accepted_suggestion(db_session: Session) -> None:
    acc, project, cat = _seed(db_session, "td-sugg")
    # Принятое предложение с уникальной темой должно всплыть как источник.
    experiment_suggestion_repository.create_suggestion(
        db_session,
        account_id=acc.id,
        project_id=project.id,
        platform_key="telegram",
        suggestion_type="publish_more",
        source="worker",
        status="accepted",
        topic="Уникальная тема носки",
        title="t",
        reason="r",
        confidence_score=0.9,
        suggested_cta="Купи носки",
    )
    cands = _svc().build_candidates(db_session, project.id, "telegram", category=cat)
    sources = {c["source"] for c in cands}
    assert "experiment_suggestion" in sources
    assert any(c["topic"] == "Уникальная тема носки" for c in cands)


def test_decision_uses_ab_winner(db_session: Session) -> None:
    acc, project, cat = _seed(db_session, "td-ab")
    exp = content_experiment_repository.create_experiment(
        db_session,
        account_id=acc.id,
        project_id=project.id,
        platform_key="telegram",
        experiment_type="ab_test",
        title="Тема-победитель мерча",
        status="completed",
    )
    content_experiment_repository.create_variant(
        db_session,
        experiment_id=exp.id,
        account_id=acc.id,
        project_id=project.id,
        variant_key="A",
        title="Победитель",
        cta_type="Жми",
        media_strategy="single_photo",
        is_winner=True,
        winner_reason="higher_er",
        quality_score=90,
    )
    cands = _svc().build_candidates(db_session, project.id, "telegram", category=cat)
    assert any(c["source"] == "ab_winner" for c in cands)
    # Победивший CTA доступен как ab_winning_cta в контексте.
    ctx = _svc()._build_context(db_session, project.id, "telegram", None, cat)
    assert ctx["ab_winning_cta"] == "Жми"
    # SELECTION: без клиентского фидбэка A/B winner (база 25) выигрывает слот, его CTA применяется.
    svc = _svc(auto_topic_selection_use_client_feedback=False)
    result = svc.choose_topic_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["decision_source"] == "ab_winner"
    assert result["selected_topic"] == "Тема-победитель мерча"
    assert result["selected_cta"] == "Жми"


def test_rejected_topic_penalized(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-rej")
    svc = _svc()
    ctx = svc._build_context(db_session, project.id, "telegram", None, cat)
    good = {
        "topic": "Свежая тема",
        "tags": ["мерч"],
        "source": "learning_profile",
        "base_confidence": 0.6,
    }
    # Отклонённая тема получает штраф.
    ctx_rej = dict(ctx)
    ctx_rej["rejected_topics"] = ["плохая тема"]
    bad = {"topic": "плохая тема", "tags": [], "source": "learning_profile", "base_confidence": 0.6}
    s_good = svc.score_candidate(db_session, project.id, "telegram", good, ctx)
    s_bad = svc.score_candidate(db_session, project.id, "telegram", bad, ctx_rej)
    assert s_bad["breakdown"]["learning_fit"] < 0
    assert s_bad["total_score"] < s_good["total_score"]


def test_recent_topic_fatigue_penalty(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-fat")
    svc = _svc()
    # _build_context должен реально собрать недавние темы из seed-постов.
    ctx = svc._build_context(db_session, project.id, "telegram", None, cat)
    assert "футболки лого" in ctx["recent_topics"]  # одна из тем seed
    # Недавняя тема (из реального контекста) штрафуется, свежая — нет.
    recent_cand = {
        "topic": "Футболки лого",
        "tags": [],
        "source": "crm_category",
        "base_confidence": 0.3,
    }
    fresh_cand = {
        "topic": "Абсолютно новая идея",
        "tags": [],
        "source": "crm_category",
        "base_confidence": 0.3,
    }
    s_recent = svc.score_candidate(db_session, project.id, "telegram", recent_cand, ctx)
    s_fresh = svc.score_candidate(db_session, project.id, "telegram", fresh_cand, ctx)
    assert s_recent["recent"] is True
    assert s_recent["breakdown"]["novelty"] < 0
    assert s_fresh["breakdown"]["novelty"] > 0


def test_fallback_to_crm_category(db_session: Session) -> None:
    # Проект без обучения → решение приходит из CRM-категории (или fallback).
    _acc, project, cat = _seed(db_session, "td-fallback", approve=False)
    result = _svc().choose_topic_for_schedule(db_session, project.id, "telegram", category=cat)
    assert result["selected_topic"] == cat.title
    assert result["decision_source"] in ("crm_category", "fallback")


def test_explain_returns_reasons(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-explain")
    result = _svc().preview_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id
    )
    assert isinstance(result["reasons"], list)
    assert len(result["reasons"]) >= 1


def test_no_secrets_in_metadata(db_session: Session) -> None:
    from app.services.platform_connection_service import PlatformConnectionService

    _acc, project, cat = _seed(db_session, "td-nosec")
    # Проект с подключённой платформой (секретный токен) — токен не должен утечь в решение.
    secret = "123456789:svcSECRETtelegramTOKEN"
    PlatformConnectionService().upsert_connection(
        db_session, project.id, "telegram", {"api_key": secret, "external_id": "@t"}
    )
    db_session.commit()
    result = _svc().create_decision_for_plan(db_session, project.id, "telegram", category_id=cat.id)
    row = schedule_topic_decision_repository.get_by_id(db_session, result["id"])
    blob = (
        str(row.decision_metadata)
        + str(row.source_signals)
        + str(row.reasons)
        + str(row.alternatives)
    )
    assert secret not in blob
    assert "api_key" not in blob
    assert "token" not in blob.lower()


def test_project_isolation(db_session: Session) -> None:
    _a1, p1, c1 = _seed(db_session, "td-iso1")
    _a2, p2, _c2 = _seed(db_session, "td-iso2")
    _svc().create_decision_for_plan(db_session, p1.id, "telegram", category_id=c1.id)
    assert schedule_topic_decision_repository.list_for_project(db_session, p2.id) == []
    assert len(schedule_topic_decision_repository.list_for_project(db_session, p1.id)) == 1


def test_no_cross_project_signal_mixing(db_session: Session) -> None:
    a1, p1, c1 = _seed(db_session, "td-mix1")
    a2, p2, _c2 = _seed(db_session, "td-mix2")
    # У проекта 2 — уникальный акцептованный сигнал, которого НЕ должно быть у проекта 1.
    experiment_suggestion_repository.create_suggestion(
        db_session,
        account_id=a2.id,
        project_id=p2.id,
        platform_key="telegram",
        suggestion_type="publish_more",
        source="worker",
        status="accepted",
        topic="Секретная тема проекта два",
        title="t",
        reason="r",
        confidence_score=0.95,
    )
    cands_p1 = _svc().build_candidates(db_session, p1.id, "telegram", category=c1)
    topics_p1 = {str(c["topic"]).lower() for c in cands_p1}
    assert "секретная тема проекта два" not in topics_p1


def test_create_decision_idempotent(db_session: Session) -> None:
    _acc, project, cat = _seed(db_session, "td-idem")
    svc = _svc()
    first = svc.create_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id, idempotency_key="k1"
    )
    second = svc.create_decision_for_plan(
        db_session, project.id, "telegram", category_id=cat.id, idempotency_key="k1"
    )
    assert first["id"] == second["id"]
    assert second["outcome"] == "skipped_duplicate"
    assert len(schedule_topic_decision_repository.list_for_project(db_session, project.id)) == 1
