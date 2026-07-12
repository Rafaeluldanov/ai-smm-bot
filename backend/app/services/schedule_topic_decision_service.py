"""Автовыбор темы для слота расписания (auto topic selection) — v0.4.4.

Worker выбирает лучшую тему/CTA/формат/медиа-стратегию для ближайшего слота на основе
learning profile + метрик + feedback + A/B winners + experiment suggestions и сохраняет
«почему бот выбрал эту тему» (:class:`ScheduleTopicDecision`). Пост создаётся только как
draft/needs_review — live-публикаций нет.

БЕЗОПАСНОСТЬ:
- никаких live-публикаций и внешних API-вызовов;
- автовыбор worker-ом ВЫКЛЮЧЕН по умолчанию (config), dry-run по умолчанию;
- строгая project/account-изоляция; без секретов; без cross-client mixing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    client_learning_repository,
    content_experiment_repository,
    experiment_suggestion_repository,
    media_asset_repository,
    post_repository,
    project_repository,
    schedule_topic_decision_repository,
)
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService
    from app.services.topic_optimization_service import TopicOptimizationService

logger = get_logger(__name__)

# Веса скоринга кандидата (MVP, из спецификации).
_SCORE_ACCEPTED_SUGGESTION = 20
_SCORE_PROPOSED_SUGGESTION = 12
_SCORE_AB_WINNER = 25
_SCORE_METRICS_REC = 18
_SCORE_LEARNING_REC = 15
_SCORE_CRM = 5
_SCORE_HIGH_TAG = 20
_SCORE_APPROVED_TOPIC = 15
_SCORE_KEYWORD_MAX = 15
_SCORE_MEDIA_AVAILABLE = 10
_SCORE_NOVELTY = 10
_PEN_RECENT_TOPIC = 15
_PEN_REJECTED_TOPIC = 30
_PEN_LOW_TAG = 20
_PEN_NO_MEDIA = 10

# Уверенность источника метрик (api/manual выше demo/estimated) — для дисконта.
_SOURCE_CONFIDENCE = {"api": 1.0, "manual": 0.8, "internal": 0.6, "estimated": 0.4, "demo": 0.2}


class TopicDecisionError(Exception):
    """Ошибка автовыбора темы (нет проекта/плана) — API → 400."""


class ScheduleTopicDecisionService:
    """Выбор темы/CTA/формата/медиа для слота + запись решения (без live-публикации)."""

    def __init__(
        self,
        topic_service: TopicOptimizationService | None = None,
        learning_service: ClientLearningService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._topic = topic_service
        self._learning = learning_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview (без записи, без биллинга)                               #
    # ------------------------------------------------------------------ #

    def preview_decision_for_plan(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan_id: int | None = None,
        category_id: int | None = None,
        publish_time: str | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр решения (без записи и без списания)."""
        plan, category = self._resolve_plan_category(db, project_id, plan_id, category_id)
        decision = self.choose_topic_for_schedule(
            db, project_id, platform_key, plan=plan, category=category, publish_time=publish_time
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_TOPIC_DECISION_PREVIEWED,
            {"platform_key": platform_key, "selected_topic": decision["selected_topic"]},
        )
        return {**decision, "writes": False}

    # ------------------------------------------------------------------ #
    # 2. Создание решения (запись, без биллинга)                          #
    # ------------------------------------------------------------------ #

    def create_decision_for_plan(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan_id: int | None = None,
        category_id: int | None = None,
        publish_time: str | None = None,
        idempotency_key: str | None = None,
        worker_owner_id: str | None = None,
        decision_mode: str = "dry_run",
        schedule_run_id: int | None = None,
        status: str = "selected",
    ) -> dict[str, Any]:
        """Создать запись :class:`ScheduleTopicDecision` (без поста и без live)."""
        # Ключ идемпотентности неймспейсим project_id — исключаем межарендную коллизию по
        # чужому (клиентом заданному) ключу и утечку данных другого проекта.
        effective_key = f"p{project_id}-{idempotency_key}" if idempotency_key is not None else None
        if effective_key is not None:
            existing = schedule_topic_decision_repository.get_by_idempotency_key(db, effective_key)
            # Возвращаем существующее решение только если оно принадлежит этому проекту.
            if existing is not None and existing.project_id == project_id:
                return {**self._decision_view(existing), "outcome": "skipped_duplicate"}
        plan, category = self._resolve_plan_category(db, project_id, plan_id, category_id)
        payload = self.choose_topic_for_schedule(
            db, project_id, platform_key, plan=plan, category=category, publish_time=publish_time
        )
        account_id = self._account_id(db, project_id)
        row = schedule_topic_decision_repository.create_decision(
            db,
            account_id=account_id,
            project_id=project_id,
            platform_key=platform_key,
            publishing_plan_id=plan.id if plan is not None else plan_id,
            schedule_run_id=schedule_run_id,
            experiment_suggestion_id=payload.get("experiment_suggestion_id"),
            content_experiment_id=payload.get("content_experiment_id"),
            selected_topic=payload["selected_topic"][:512],
            selected_cta=_clip(payload.get("selected_cta"), 512),
            selected_format=_clip(payload.get("selected_format"), 64),
            selected_media_strategy=_clip(payload.get("selected_media_strategy"), 64),
            selected_publish_time=_clip(payload.get("selected_publish_time"), 20),
            decision_source=payload["decision_source"],
            decision_mode=decision_mode,
            status=status,
            confidence_score=float(payload["confidence_score"]),
            expected_quality_score=payload.get("expected_quality_score"),
            expected_engagement_score=payload.get("expected_engagement_score"),
            learning_profile_version=payload.get("learning_profile_version"),
            alternatives=payload.get("alternatives", []),
            source_signals=payload.get("source_signals", []),
            risk_flags=payload.get("risk_flags", []),
            reasons=payload.get("reasons", []),
            decision_metadata=payload.get("decision_metadata", {}),
            idempotency_key=effective_key,
            created_by_worker_owner_id=worker_owner_id,
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_TOPIC_DECISION_CREATED,
            {
                "decision_id": row.id,
                "platform_key": platform_key,
                "selected_topic": row.selected_topic,
                "decision_source": row.decision_source,
                "confidence": row.confidence_score,
                "risk_flags": list(row.risk_flags or []),
            },
        )
        if "low_confidence" in (row.risk_flags or []):
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_TOPIC_DECISION_LOW_CONFIDENCE,
                {"decision_id": row.id, "confidence": row.confidence_score},
            )
        if row.decision_source in ("crm_category", "fallback"):
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_TOPIC_DECISION_FALLBACK_USED,
                {"decision_id": row.id, "decision_source": row.decision_source},
            )
        return {**self._decision_view(row), "outcome": "created"}

    # ------------------------------------------------------------------ #
    # 3. Основной алгоритм выбора                                         #
    # ------------------------------------------------------------------ #

    def choose_topic_for_schedule(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan: Any | None = None,
        category: Any | None = None,
        publish_time: str | None = None,
    ) -> dict[str, Any]:
        """Собрать сигналы, отскорить кандидатов и выбрать лучшую тему. Ничего не публикует."""
        context = self._build_context(db, project_id, platform_key, plan, category)
        candidates = self.build_candidates(db, project_id, platform_key, plan, category, context)
        scored = [
            (c, self.score_candidate(db, project_id, platform_key, c, context)) for c in candidates
        ]
        scored.sort(key=lambda cs: cs[1]["total_score"], reverse=True)
        max_alt = self._max_alternatives()
        best_candidate, best_score = scored[0]
        # Победившие A/B-стратегии применяем к выбору, если у кандидата их нет.
        cta = best_candidate.get("cta") or context["ab_winning_cta"]
        media_strategy = best_candidate.get("media_strategy") or context["ab_winning_media"]
        fmt = best_candidate.get("format") or context["ab_winning_format"]
        best_time = best_candidate.get("publish_time") or context["ab_winning_time"] or publish_time
        confidence = best_score["confidence_score"]
        risks = self._risk_flags(best_candidate, best_score, context, confidence)
        reasons = self.explain_decision(best_candidate, best_score, context)
        alternatives = [
            {
                "topic": c.get("topic"),
                "decision_source": c.get("source"),
                "total_score": s["total_score"],
                "confidence_score": s["confidence_score"],
            }
            for c, s in scored[1 : max_alt + 1]
        ]
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "selected_topic": str(best_candidate.get("topic") or "").strip() or "Публикация",
            "selected_cta": cta,
            "selected_format": fmt,
            "selected_media_strategy": media_strategy,
            "selected_publish_time": best_time,
            "decision_source": best_candidate.get("source", "fallback"),
            "confidence_score": confidence,
            "expected_quality_score": best_score.get("expected_quality_score"),
            "expected_engagement_score": best_score.get("expected_engagement_score"),
            "learning_profile_version": context["profile_version"],
            "experiment_suggestion_id": best_candidate.get("experiment_suggestion_id"),
            "content_experiment_id": best_candidate.get("content_experiment_id"),
            "alternatives": alternatives,
            "source_signals": list(best_candidate.get("signals", [])),
            "risk_flags": risks,
            "reasons": reasons,
            "decision_metadata": {
                "score_breakdown": best_score.get("breakdown", {}),
                "candidate_count": len(candidates),
                "min_confidence": self._min_confidence(),
            },
        }

    # ------------------------------------------------------------------ #
    # 4. Кандидаты                                                        #
    # ------------------------------------------------------------------ #

    def build_candidates(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan: Any | None = None,
        category: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Кандидаты из: оптимизации тем, принятых suggestions, A/B winners, CRM-категории."""
        context = context or self._build_context(db, project_id, platform_key, plan, category)
        candidates: list[dict[str, Any]] = []
        seen: set[str] = set()

        def add(cand: dict[str, Any]) -> None:
            key = str(cand.get("topic") or "").strip().lower()
            if not key or key in seen:
                return
            seen.add(key)
            candidates.append(cand)

        # Порядок ВАЖЕН: при совпадении темы дедуп оставляет ПЕРВЫЙ кандидат, поэтому
        # источники добавляем по убыванию ценности (A/B winner > предложение > рекомендация
        # оптимизации > CRM), чтобы победил более сильный источник/скор.

        # 1) A/B winners (тема из эксперимента, стратегии из победившего варианта).
        if self._use_ab_winners():
            for variant in content_experiment_repository.list_winners_for_project(db, project_id):
                experiment = content_experiment_repository.get_experiment_by_id(
                    db, variant.experiment_id
                )
                topic = experiment.title if experiment is not None else variant.title
                add(
                    {
                        "topic": topic,
                        "cta": variant.cta_type,
                        "format": variant.text_length_type,
                        "media_strategy": variant.media_strategy,
                        "publish_time": variant.publish_time_strategy,
                        "source": "ab_winner",
                        "base_confidence": min(1.0, float((variant.quality_score or 70) / 100)),
                        "tags": _topic_tags(topic),
                        "signals": [f"ab_winner:{variant.winner_reason or 'winner'}"],
                        "content_experiment_id": variant.experiment_id,
                    }
                )

        # 2) Принятые/активные предложения экспериментов.
        if self._use_suggestions():
            for sugg in experiment_suggestion_repository.list_active_for_project(db, project_id):
                if sugg.platform_key not in (None, platform_key):
                    continue
                add(
                    {
                        "topic": sugg.topic,
                        "cta": sugg.suggested_cta,
                        "format": sugg.suggested_media_type,
                        "media_strategy": sugg.suggested_media_type,
                        "publish_time": sugg.suggested_publish_time,
                        "source": "experiment_suggestion",
                        "base_confidence": float(sugg.confidence_score or 0.0),
                        "tags": _topic_tags(sugg.topic),
                        "signals": [f"experiment_suggestion:{sugg.status}"],
                        "suggestion_status": sugg.status,
                        "experiment_suggestion_id": sugg.id,
                    }
                )

        # 3) Рекомендации оптимизации тем (кроме avoid — их не публикуем).
        recs = self._topic_svc().recommend_next_topics(
            db, project_id, platform_key, self._max_alternatives() * 2 + 4
        )
        for rec in recs.get("recommendations", []):
            rec_category = str(rec.get("category", ""))
            if rec_category == "avoid":
                continue
            source = "metrics" if rec_category in ("explore", "retest") else "learning_profile"
            if rec_category == "fill_gap":
                source = "crm_category"
            add(
                {
                    "topic": rec.get("topic"),
                    "cta": rec.get("suggested_cta"),
                    "format": rec.get("suggested_media_type"),
                    "media_strategy": rec.get("suggested_media_type"),
                    "publish_time": rec.get("suggested_time"),
                    "source": source,
                    "base_confidence": float(rec.get("confidence_score") or 0.0),
                    "tags": _topic_tags(rec.get("topic")),
                    "signals": list(rec.get("source_signals", []))
                    + [f"topic_optimization:{rec_category}"],
                    "rec_category": rec_category,
                }
            )

        # 4) CRM-категория как гарантированный fallback (управляется флагом).
        if category is not None and self._fallback_to_crm_category():
            add(
                {
                    "topic": (category.title or "Публикация по расписанию"),
                    "cta": category.cta or None,
                    "format": None,
                    "media_strategy": (category.media_tags or [None])[0],
                    "publish_time": None,
                    "source": "crm_category",
                    "base_confidence": 0.3,
                    "tags": list(category.media_tags or []),
                    "signals": ["crm_category"],
                }
            )
        if not candidates:
            add(
                {
                    "topic": "Публикация по расписанию",
                    "cta": None,
                    "format": None,
                    "media_strategy": None,
                    "publish_time": None,
                    "source": "fallback",
                    "base_confidence": 0.25,
                    "tags": [],
                    "signals": ["fallback"],
                }
            )
        return candidates

    # ------------------------------------------------------------------ #
    # 5. Скоринг кандидата                                                #
    # ------------------------------------------------------------------ #

    def score_candidate(
        self,
        db: Session,  # noqa: ARG002 — контекст уже собран
        project_id: int,  # noqa: ARG002
        platform_key: str | None,  # noqa: ARG002
        candidate: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Отскорить кандидата по обучению/метрикам/новизне; вернуть breakdown + confidence."""
        breakdown: dict[str, int] = {}
        source = candidate.get("source", "fallback")
        topic_l = str(candidate.get("topic") or "").strip().lower()
        tags_l = {str(t).lower().lstrip("#") for t in candidate.get("tags", [])}

        # База по источнику.
        if source == "experiment_suggestion":
            base = (
                _SCORE_ACCEPTED_SUGGESTION
                if candidate.get("suggestion_status") == "accepted"
                else _SCORE_PROPOSED_SUGGESTION
            )
        elif source == "ab_winner":
            base = _SCORE_AB_WINNER
        elif source == "metrics":
            base = _SCORE_METRICS_REC
        elif source == "learning_profile":
            base = _SCORE_LEARNING_REC
        else:
            base = _SCORE_CRM
        breakdown["source_base"] = base

        # Learning fit.
        learn = 0
        if tags_l & context["high_tags"]:
            learn += _SCORE_HIGH_TAG
        if tags_l & context["low_tags"]:
            learn -= _PEN_LOW_TAG
        if any(t in topic_l or topic_l in t for t in context["preferred_topics"] if t):
            learn += _SCORE_APPROVED_TOPIC
        if any(t in topic_l or topic_l in t for t in context["rejected_topics"] if t):
            learn -= _PEN_REJECTED_TOPIC
        breakdown["learning_fit"] = learn

        # Приоритет ключевого слова.
        keyword = 0
        for kw, priority in context["keyword_priorities"].items():
            if kw and (kw in topic_l or any(kw in t for t in tags_l)):
                keyword = max(keyword, min(_SCORE_KEYWORD_MAX, int(priority)))
        breakdown["keyword_priority"] = keyword

        # Доступность медиа.
        media = 0
        if context["media_available"] and (not tags_l or tags_l & context["media_tags"]):
            media += _SCORE_MEDIA_AVAILABLE
        elif context["require_media"] and not context["media_available"]:
            media -= _PEN_NO_MEDIA
        breakdown["media_availability"] = media

        # Новизна / усталость. recent_topics хранятся без '#', поэтому сравниваем
        # нормализованную тему (иначе кандидаты-теги «#tag» никогда не штрафуются).
        recent = (
            topic_l.lstrip("#") in context["recent_topics"] or topic_l in context["recent_topics"]
        )
        novelty = -_PEN_RECENT_TOPIC if recent else _SCORE_NOVELTY
        breakdown["novelty"] = novelty

        total = base + learn + keyword + media + novelty
        # Дисконт уверенности по источнику метрик (api/manual > demo/estimated).
        metrics_conf = context["metrics_confidence"]
        base_conf = float(candidate.get("base_confidence", 0.0)) * (0.6 + 0.4 * metrics_conf)
        raw = 0.30 + 0.007 * total + 0.25 * base_conf
        confidence = round(max(0.0, min(1.0, raw)), 3)
        return {
            "total_score": total,
            "confidence_score": confidence,
            "breakdown": breakdown,
            "recent": recent,
            "expected_quality_score": context["expected_quality"],
            "expected_engagement_score": context["expected_engagement"],
        }

    # ------------------------------------------------------------------ #
    # 6. Объяснение                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def explain_decision(
        candidate: dict[str, Any], score: dict[str, Any], context: dict[str, Any]
    ) -> list[str]:
        """Человекочитаемые причины выбора темы."""
        reasons: list[str] = []
        source = candidate.get("source")
        bd = score.get("breakdown", {})
        if source == "ab_winner":
            reasons.append("Тема и CTA взяты из победившего A/B-теста.")
        elif source == "experiment_suggestion":
            reasons.append("Тема основана на принятом предложении worker-а.")
        elif source == "metrics":
            reasons.append("Похожие посты по метрикам дали высокий отклик.")
        elif source == "learning_profile":
            reasons.append("Клиент одобрял такие темы — публикуем чаще.")
        elif source in ("crm_category", "fallback"):
            reasons.append("Использована тема из плана/категории (fallback).")
        if bd.get("learning_fit", 0) > 0:
            reasons.append("Совпадение с сильными темами/тегами профиля обучения.")
        if bd.get("learning_fit", 0) < 0:
            reasons.append("Есть слабые/отклонённые сигналы — учтены со штрафом.")
        if bd.get("media_availability", 0) > 0:
            reasons.append("Подходящее медиа доступно в проекте.")
        if bd.get("keyword_priority", 0) > 0:
            reasons.append("Тема совпадает с приоритетным ключевым словом CRM.")
        if score.get("recent"):
            reasons.append("Тема недавно уже публиковалась — риск повторения.")
        else:
            reasons.append("Тема давно не публиковалась.")
        return reasons[:8]

    # ------------------------------------------------------------------ #
    # 7. Применение решения к драфту                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def apply_decision_to_draft_payload(
        decision: dict[str, Any], base_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Наложить выбранную тему/CTA/медиа на payload драфта (без live-публикации)."""
        payload = dict(base_payload)
        topic = str(decision.get("selected_topic") or "").strip()
        if topic:
            payload["title"] = topic
        if decision.get("selected_cta"):
            payload["cta"] = decision["selected_cta"]
        if decision.get("selected_format"):
            payload["format"] = decision["selected_format"]
        if decision.get("selected_media_strategy"):
            payload["media_strategy"] = decision["selected_media_strategy"]
        notes = dict(payload.get("generation_notes", {}) or {})
        notes.update(
            {
                "schedule_topic_decision_id": decision.get("id"),
                "selected_topic": topic,
                "selected_cta": decision.get("selected_cta"),
                "selected_format": decision.get("selected_format"),
                "selected_media_strategy": decision.get("selected_media_strategy"),
                "topic_decision_confidence": decision.get("confidence_score"),
                "topic_decision_reasons": (decision.get("reasons") or [])[:8],
                "topic_decision_source_signals": (decision.get("source_signals") or [])[:8],
                "topic_decision_risk_flags": (decision.get("risk_flags") or [])[:8],
            }
        )
        payload["generation_notes"] = notes
        return payload

    def mark_decision_draft_created(
        self, db: Session, decision_id: int, schedule_run_id: int | None, post_id: int | None
    ) -> None:
        """Отметить решение как использованное для драфта (+ аудит)."""
        decision = schedule_topic_decision_repository.get_by_id(db, decision_id)
        if decision is None:
            return
        schedule_topic_decision_repository.mark_draft_created(
            db, decision, schedule_run_id, post_id
        )
        self._write_audit(
            db,
            decision.project_id,
            audit_actions.ACTION_TOPIC_DECISION_APPLIED_TO_DRAFT,
            {"decision_id": decision_id, "post_id": post_id, "schedule_run_id": schedule_run_id},
        )

    def mark_decision_failed(self, db: Session, decision_id: int, error: str) -> None:
        """Отметить решение как failed (без секретов)."""
        decision = schedule_topic_decision_repository.get_by_id(db, decision_id)
        if decision is None:
            return
        schedule_topic_decision_repository.mark_failed(db, decision, error)
        self._write_audit(
            db,
            decision.project_id,
            audit_actions.ACTION_TOPIC_DECISION_FAILED,
            {"decision_id": decision_id, "error": error[:120]},
        )

    # ------------------------------------------------------------------ #
    # 8. Дашборд                                                          #
    # ------------------------------------------------------------------ #

    def build_decision_dashboard(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Сводка решений проекта для UI."""
        decisions = schedule_topic_decision_repository.list_for_project(
            db, project_id, platform_key=platform_key, limit=200
        )
        by_source: dict[str, int] = {}
        by_topic: dict[str, int] = {}
        confidences: list[float] = []
        low_conf = 0
        risk_counts: dict[str, int] = {}
        for d in decisions:
            by_source[d.decision_source] = by_source.get(d.decision_source, 0) + 1
            by_topic[d.selected_topic] = by_topic.get(d.selected_topic, 0) + 1
            confidences.append(d.confidence_score)
            if "low_confidence" in (d.risk_flags or []):
                low_conf += 1
            for flag in d.risk_flags or []:
                risk_counts[flag] = risk_counts.get(flag, 0) + 1
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "total": len(decisions),
            "low_confidence_count": low_conf,
            "avg_confidence": avg_conf,
            "top_sources": sorted(by_source.items(), key=lambda kv: kv[1], reverse=True)[:5],
            "top_topics": sorted(by_topic.items(), key=lambda kv: kv[1], reverse=True)[:5],
            "risk_flags": sorted(risk_counts.items(), key=lambda kv: kv[1], reverse=True)[:8],
            "worker_enabled": self._worker_enabled(),
            "recent": [self._decision_view(d) for d in decisions[:20]],
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _build_context(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan: Any | None,
        category: Any | None,
    ) -> dict[str, Any]:
        """Собрать сигналы проекта (learning/метрики/медиа/усталость/A/B-стратегии)."""
        summary = self._topic_svc().build_project_signal_summary(db, project_id, platform_key)
        profile = client_learning_repository.get_profile(db, project_id, None)
        profile_version = int(getattr(profile, "profile_version", 0) or 0) if profile else 0
        high_tags = {str(t).lower().lstrip("#") for t in summary.get("high_performing_tags", [])}
        low_tags = {str(t).lower().lstrip("#") for t in summary.get("low_performing_tags", [])}
        # Сигналы клиентского фидбэка (одобряемые/отклонённые темы) — управляются флагом.
        if self._use_client_feedback():
            preferred = [str(t).lower() for t in summary.get("top_topics", [])]
            rejected = [str(t).lower() for t in summary.get("weak_topics", [])]
        else:
            preferred = []
            rejected = []

        # Приоритеты ключевых слов CRM (name → 0..15).
        keyword_priorities = self._keyword_priorities(db, project_id, category)
        # Доступность одобренного медиа + теги медиа.
        media_available, media_tags = self._media_availability(db, project_id, category)
        require_media = bool(
            self._require_media() and category is not None and (category.media_tags or [])
        )
        # Усталость: недавно использованные темы/теги.
        recent_topics = self._recent_topics(db, project_id)
        # Победившие A/B-стратегии (агрегированные).
        ab_cta, ab_media, ab_format, ab_time = self._ab_winning_strategies(db, project_id)
        # Ожидаемые метрики из паттернов (best-effort).
        perf = summary.get("performance_patterns", {}) or {}
        expected_quality = int(min(100, float(perf.get("avg_quality_score", 0) or 0)))
        expected_engagement = int(min(100, float(perf.get("avg_engagement_rate", 0) or 0) * 500))
        metrics_confidence = self._metrics_confidence(db, project_id)
        return {
            "profile_version": profile_version or None,
            "high_tags": high_tags,
            "low_tags": low_tags,
            "preferred_topics": preferred,
            "rejected_topics": rejected,
            "keyword_priorities": keyword_priorities,
            "media_available": media_available,
            "media_tags": media_tags,
            "require_media": require_media,
            "recent_topics": recent_topics,
            "ab_winning_cta": ab_cta,
            "ab_winning_media": ab_media,
            "ab_winning_format": ab_format,
            "ab_winning_time": ab_time,
            "expected_quality": expected_quality or None,
            "expected_engagement": expected_engagement or None,
            "metrics_confidence": metrics_confidence,
            "profile_confidence": float(summary.get("confidence_score", 0.0) or 0.0),
        }

    def _keyword_priorities(
        self, db: Session, project_id: int, category: Any | None
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return out
        for kw in crm_repo.list_keywords_by_config(db, config.id):
            query = str(getattr(kw, "query", "") or "").strip().lower()
            if not query:
                continue
            # priority в CRM — небольшое число; шкалируем в [0..15].
            priority = int(getattr(kw, "priority", 0) or 0)
            out[query] = float(max(0, min(_SCORE_KEYWORD_MAX, priority)))
        return out

    def _media_availability(
        self, db: Session, project_id: int, category: Any | None
    ) -> tuple[bool, set[str]]:
        assets = [
            a
            for a in media_asset_repository.list_media_assets_by_project(db, project_id)
            if a.status in ("approved", "approved_video")
        ]
        available = bool(assets)
        media_tags: set[str] = set()
        if category is not None:
            media_tags = {str(t).lower().lstrip("#") for t in (category.media_tags or [])}
        return available, media_tags

    def _recent_topics(self, db: Session, project_id: int) -> set[str]:
        recent: set[str] = set()
        for post in post_repository.list_recent_posts(db, project_id, limit=self._recency_window()):
            if post.title:
                recent.add(post.title.strip().lower())
            for tag in post.hashtags or []:
                recent.add(str(tag).strip().lower().lstrip("#"))
        # Плюс недавно выбранные темы (по решениям).
        for d in schedule_topic_decision_repository.list_for_project(
            db, project_id, status="draft_created", limit=self._recency_window()
        ):
            recent.add(d.selected_topic.strip().lower())
        return recent

    def _ab_winning_strategies(
        self, db: Session, project_id: int
    ) -> tuple[str | None, str | None, str | None, str | None]:
        if not self._use_ab_winners():
            return None, None, None, None
        winners = content_experiment_repository.list_winners_for_project(db, project_id, limit=10)
        for variant in winners:  # самый свежий победитель первым
            return (
                variant.cta_type,
                variant.media_strategy,
                variant.text_length_type,
                variant.publish_time_strategy,
            )
        return None, None, None, None

    def _metrics_confidence(self, db: Session, project_id: int) -> float:
        """Уверенность метрик проекта по источнику последнего снимка (api/manual > demo)."""
        if not self._use_metrics():
            return 0.5
        from app.repositories import analytics_repository

        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        if not snapshots:
            return 0.5
        latest = snapshots[-1]
        return _SOURCE_CONFIDENCE.get(str(getattr(latest, "source", "") or ""), 0.4)

    def _risk_flags(
        self,
        candidate: dict[str, Any],
        score: dict[str, Any],
        context: dict[str, Any],
        confidence: float,
    ) -> list[str]:
        flags: list[str] = []
        if confidence < self._min_confidence():
            flags.append("low_confidence")
        if score.get("recent"):
            flags.append("repeated_topic")
        if context["require_media"] and not context["media_available"]:
            flags.append("no_media")
        if candidate.get("rec_category") == "fill_gap":
            flags.append("content_gap")
        if context["profile_confidence"] < 0.3:
            flags.append("stale_learning_profile")
        if score.get("breakdown", {}).get("learning_fit", 0) < 0:
            flags.append("weak_metrics")
        return flags

    def _decision_view(self, decision: Any) -> dict[str, Any]:
        return {
            "id": decision.id,
            "project_id": decision.project_id,
            "platform_key": decision.platform_key,
            "publishing_plan_id": decision.publishing_plan_id,
            "schedule_run_id": decision.schedule_run_id,
            "selected_topic": decision.selected_topic,
            "selected_cta": decision.selected_cta,
            "selected_format": decision.selected_format,
            "selected_media_strategy": decision.selected_media_strategy,
            "selected_publish_time": decision.selected_publish_time,
            "decision_source": decision.decision_source,
            "decision_mode": decision.decision_mode,
            "status": decision.status,
            "confidence_score": round(decision.confidence_score, 3),
            "expected_quality_score": decision.expected_quality_score,
            "expected_engagement_score": decision.expected_engagement_score,
            "learning_profile_version": decision.learning_profile_version,
            "alternatives": list(decision.alternatives or []),
            "source_signals": list(decision.source_signals or []),
            "risk_flags": list(decision.risk_flags or []),
            "reasons": list(decision.reasons or []),
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
        }

    def _resolve_plan_category(
        self, db: Session, project_id: int, plan_id: int | None, category_id: int | None
    ) -> tuple[Any | None, Any | None]:
        plan = None
        category = None
        if plan_id is not None:
            plan = crm_repo.get_plan_by_id(db, plan_id)
            if plan is not None and plan.project_id != project_id:
                raise TopicDecisionError("План не принадлежит проекту")
            if plan is not None and category_id is None:
                category_id = plan.category_id
        if category_id is not None:
            category = crm_repo.get_category_by_id(db, category_id)
            if category is not None and category.project_id != project_id:
                raise TopicDecisionError("Категория не принадлежит проекту")
        if category is None:
            # Первая категория проекта как дефолт.
            config = crm_repo.get_config_by_project_id(db, project_id)
            if config is not None:
                cats = crm_repo.list_categories_by_config(db, config.id)
                category = cats[0] if cats else None
        return plan, category

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise TopicDecisionError(f"Проект id={project_id} не найден")
        return project.account_id

    # --- Настройки ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _enabled(self) -> bool:
        return bool(self._resolve_settings().auto_topic_selection_enabled_effective)

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().auto_topic_selection_worker_enabled_effective)

    def _min_confidence(self) -> float:
        return float(self._resolve_settings().auto_topic_selection_min_confidence_safe)

    def _max_alternatives(self) -> int:
        return int(getattr(self._resolve_settings(), "auto_topic_selection_max_alternatives", 5))

    def _recency_window(self) -> int:
        return max(10, int(self._resolve_settings().auto_topic_selection_recency_days_safe))

    def _require_media(self) -> bool:
        return bool(
            getattr(
                self._resolve_settings(),
                "auto_topic_selection_require_media_for_media_plans",
                False,
            )
        )

    def _use_suggestions(self) -> bool:
        return bool(
            getattr(
                self._resolve_settings(), "auto_topic_selection_use_experiment_suggestions", True
            )
        )

    def _use_ab_winners(self) -> bool:
        return bool(getattr(self._resolve_settings(), "auto_topic_selection_use_ab_winners", True))

    def _use_metrics(self) -> bool:
        return bool(getattr(self._resolve_settings(), "auto_topic_selection_use_metrics", True))

    def _use_client_feedback(self) -> bool:
        return bool(
            getattr(self._resolve_settings(), "auto_topic_selection_use_client_feedback", True)
        )

    def _fallback_to_crm_category(self) -> bool:
        return bool(
            getattr(self._resolve_settings(), "auto_topic_selection_fallback_to_crm_category", True)
        )

    # --- Ленивые зависимости ---

    def _topic_svc(self) -> TopicOptimizationService:
        if self._topic is None:
            from app.services.topic_optimization_service import TopicOptimizationService

            self._topic = TopicOptimizationService(settings=self._settings)
        return self._topic

    def _audit_svc(self) -> AuditLogService:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        return self._audit

    def _write_audit(
        self, db: Session, project_id: int, action: str, metadata: dict[str, Any]
    ) -> None:
        project = project_repository.get_project_by_id(db, project_id)
        account_id = project.account_id if project is not None else None
        self._audit_svc().record(
            db,
            action,
            account_id=account_id,
            project_id=project_id,
            entity_type="schedule_topic_decision",
            metadata=metadata,
        )


def _clip(value: Any, length: int) -> str | None:
    if value is None:
        return None
    return str(value)[:length]


def _topic_tags(topic: Any) -> list[str]:
    text = str(topic or "").strip().lstrip("#")
    return [text] if text else []


def get_topic_decision_service() -> ScheduleTopicDecisionService:
    """DI-фабрика сервиса автовыбора темы."""
    return ScheduleTopicDecisionService()
