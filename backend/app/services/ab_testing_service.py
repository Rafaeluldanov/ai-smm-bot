"""A/B-тестирование вариантов постов (v0.4.2).

Создаёт эксперименты с вариантами A/B/C (draft/needs_review посты — БЕЗ live-публикации),
сравнивает их по feedback + метрикам, выбирает winner и обновляет ``ClientLearningProfile``.

БЕЗОПАСНОСТЬ:
- live-публикаций нет; варианты идут в очередь ревью;
- строгая project/account-изоляция; секретов в metadata нет;
- создание эксперимента платное (идемпотентно); preview/ручной winner — бесплатно.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    client_learning_repository,
    content_experiment_repository,
    post_repository,
    project_repository,
)
from app.repositories.post_repository import PostNotFoundError
from app.schemas.post import PostCreate
from app.services import audit_log_service as audit_actions
from app.services.billing_service import (
    USAGE_AB_EXPERIMENT_CREATE,
    USAGE_EXPERIMENT_ANALYSIS,
    BillingService,
)
from app.services.content_variant_service import ContentVariantService
from app.services.experiment_analysis_service import ExperimentAnalysisService
from app.services.metrics_normalization_service import MetricsNormalizationService
from app.services.unit_economics_service import UnitEconomicsService

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService
    from app.services.content_scoring_service import ContentScoringService

logger = get_logger(__name__)

_VARIANT_KEYS = ("A", "B", "C")


class ABTestingError(Exception):
    """Ошибка A/B-тестирования (нет поста/эксперимента, режим выключен) — API → 400/409."""


class ABTestingService:
    """Создание/скоринг/winner-выбор A/B-экспериментов."""

    def __init__(
        self,
        variant_service: ContentVariantService | None = None,
        analysis_service: ExperimentAnalysisService | None = None,
        learning_service: ClientLearningService | None = None,
        scoring_service: ContentScoringService | None = None,
        billing_service: BillingService | None = None,
        economics: UnitEconomicsService | None = None,
        audit_service: AuditLogService | None = None,
        normalization_service: MetricsNormalizationService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._variants = variant_service or ContentVariantService()
        self._analysis = analysis_service or ExperimentAnalysisService()
        self._learning = learning_service
        self._scoring = scoring_service
        self._billing = billing_service or BillingService()
        self._economics = economics or UnitEconomicsService(settings)
        self._audit = audit_service
        self._normalize = normalization_service or MetricsNormalizationService()
        self._settings = settings

    # ------------------------------------------------------------------ #
    # Preview (бесплатно, без записи)                                     #
    # ------------------------------------------------------------------ #

    def preview_topic(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        topic: str,
        variant_count: int = 2,
    ) -> dict[str, Any]:
        """Показать предлагаемые варианты по теме + оценку списания (без записи)."""
        count = self._clamp_variant_count(variant_count)
        variants = self.generate_variants(db, project_id, platform_key, None, topic, count)
        units = self._economics.estimate_experiment_create_units(count)
        self._write_audit(
            db,
            project_id,
            None,
            audit_actions.ACTION_AB_TEST_PREVIEWED,
            {"topic": topic, "variant_count": count},
        )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "topic": topic,
            "variant_count": count,
            "estimated_units": units,
            "variants": [self._variant_preview(v) for v in variants],
            "writes": False,
        }

    # ------------------------------------------------------------------ #
    # Генерация вариантов (без записи)                                    #
    # ------------------------------------------------------------------ #

    def generate_variants(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        base_text: str | None,
        topic: str,
        variant_count: int,
    ) -> list[dict[str, Any]]:
        """Сгенерировать варианты текста по профилю (rule-based, без записи)."""
        profile = client_learning_repository.get_profile(db, project_id, platform_key)
        if profile is None:
            profile = client_learning_repository.get_profile(db, project_id, None)
        return self._variants.generate_text_variants(base_text, topic, profile, variant_count)

    # ------------------------------------------------------------------ #
    # Создание эксперимента                                              #
    # ------------------------------------------------------------------ #

    def create_experiment_from_topic(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        topic: str,
        experiment_type: str = "ab_test",
        variant_count: int = 2,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Создать эксперимент из темы: варианты + draft-посты в ревью. Live нет."""
        self._ensure_enabled(db, project_id, current_user_id)
        count = self._clamp_variant_count(variant_count)
        existing = self._find_by_idempotency(db, project_id, idempotency_key)
        if existing is not None:
            return {
                **self.build_experiment_summary(db, existing.id),
                "outcome": "skipped_duplicate",
            }

        account_id = self._account_id(db, project_id)
        units = self._economics.estimate_experiment_create_units(count)
        # Баланс проверяем ДО создания (нехватка → без эксперимента и без списания).
        self._ensure_balance(db, account_id, units)

        title = f"A/B: {topic}"[:255]
        experiment = content_experiment_repository.create_experiment(
            db,
            account_id=account_id,
            project_id=project_id,
            platform_key=platform_key,
            experiment_type=experiment_type,
            title=title,
            hypothesis=f"Проверяем, какой вариант «{topic}» лучше заходит аудитории.",
            status="active",
            started_at=datetime.now(UTC),
            created_by_user_id=current_user_id,
            experiment_metadata=self._creation_metadata(idempotency_key, units, "topic"),
        )
        variants = self.generate_variants(db, project_id, platform_key, None, topic, count)
        self._materialize_variants(db, experiment, project_id, account_id, platform_key, variants)
        self._score_experiment_variants(db, experiment.id)
        # Списание с ключом по id эксперимента (уникально на каждый созданный эксперимент).
        self._debit_created(db, account_id, units, experiment.id, project_id, idempotency_key)
        self._write_audit(
            db,
            project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_CREATED,
            {
                "experiment_id": experiment.id,
                "type": experiment_type,
                "variants": count,
                "units": units,
            },
        )
        return {**self.build_experiment_summary(db, experiment.id), "outcome": "created"}

    def create_experiment_from_post(
        self,
        db: Session,
        post_id: int,
        experiment_type: str = "ab_test",
        variant_count: int = 2,
        current_user_id: int | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Создать эксперимент из существующего поста: A = исходный стиль, B/C — варианты."""
        post = post_repository.get_post_by_id(db, post_id)
        if post is None:
            raise PostNotFoundError(post_id)
        project_id = post.project_id
        self._ensure_enabled(db, project_id, current_user_id)
        count = self._clamp_variant_count(variant_count)
        existing = self._find_by_idempotency(db, project_id, idempotency_key)
        if existing is not None:
            return {
                **self.build_experiment_summary(db, existing.id),
                "outcome": "skipped_duplicate",
            }

        platform_key = self._post_platform(post)
        base_text = post.vk_text or post.telegram_text or post.instagram_text or ""
        topic = post.title or "Публикация"
        account_id = self._account_id(db, project_id)
        units = self._economics.estimate_experiment_create_units(count)
        self._ensure_balance(db, account_id, units)

        experiment = content_experiment_repository.create_experiment(
            db,
            account_id=account_id,
            project_id=project_id,
            platform_key=platform_key,
            experiment_type=experiment_type,
            title=f"A/B из поста #{post_id}: {topic}"[:255],
            hypothesis=f"Сравниваем вариации поста «{topic}».",
            status="active",
            source_post_id=post_id,
            started_at=datetime.now(UTC),
            created_by_user_id=current_user_id,
            experiment_metadata=self._creation_metadata(idempotency_key, units, "post"),
        )
        variants = self.generate_variants(db, project_id, platform_key, base_text, topic, count)
        self._materialize_variants(db, experiment, project_id, account_id, platform_key, variants)
        self._score_experiment_variants(db, experiment.id)
        self._debit_created(db, account_id, units, experiment.id, project_id, idempotency_key)
        self._write_audit(
            db,
            project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_CREATED,
            {"experiment_id": experiment.id, "source_post_id": post_id, "units": units},
        )
        return {**self.build_experiment_summary(db, experiment.id), "outcome": "created"}

    # ------------------------------------------------------------------ #
    # Скоринг вариантов (платно)                                          #
    # ------------------------------------------------------------------ #

    def score_variants(
        self, db: Session, experiment_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Пересчитать оценки вариантов (платное действие — анализ)."""
        experiment = self._get_experiment(db, experiment_id)
        account_id = self._account_id(db, experiment.project_id)
        units = self._economics.estimate_experiment_analysis_units()
        self._charge(
            db,
            account_id,
            units,
            USAGE_EXPERIMENT_ANALYSIS,
            f"experiment-score-{experiment_id}-{self._score_round(db, experiment_id)}",
            experiment.project_id,
        )
        self._score_experiment_variants(db, experiment_id)
        self._write_audit(
            db,
            experiment.project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_SCORED,
            {"experiment_id": experiment_id, "units": units},
        )
        return self.build_experiment_summary(db, experiment_id)

    # ------------------------------------------------------------------ #
    # Feedback и метрики варианта (бесплатно)                             #
    # ------------------------------------------------------------------ #

    def record_variant_feedback(
        self,
        db: Session,
        variant_id: int,
        event_type: str,
        rating: int | None = None,
        comment: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Записать feedback по варианту (событие обучения + счётчики в variant)."""
        variant = self._get_variant(db, variant_id)
        if variant.post_id is not None:
            self._learning_svc().record_review_feedback(
                db,
                variant.post_id,
                event_type,
                user_id=current_user_id,
                rating=rating,
                comment=comment,
                platform_key=self._experiment_platform(db, variant.experiment_id),
            )
        meta = dict(variant.variant_metadata or {})
        feedback = dict(meta.get("feedback") or {})
        feedback[event_type] = int(feedback.get(event_type, 0)) + 1
        meta["feedback"] = feedback
        content_experiment_repository.update_variant(db, variant, variant_metadata=meta)
        self._write_audit(
            db,
            variant.project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_FEEDBACK_RECORDED,
            {"variant_id": variant_id, "event_type": event_type},
        )
        return {"variant_id": variant_id, "event_type": event_type, "feedback": feedback}

    def import_variant_metrics(
        self, db: Session, variant_id: int, metrics_snapshot: dict[str, Any]
    ) -> dict[str, Any]:
        """Привязать метрики к варианту и пересчитать actual-оценку (бесплатно)."""
        variant = self._get_variant(db, variant_id)
        platform = self._experiment_platform(db, variant.experiment_id) or "manual"
        normalized = self._normalize.normalize_platform_metrics(
            platform, metrics_snapshot, "manual"
        )
        snap = normalized.to_dict()
        score = self._analysis.calculate_variant_score(variant, metrics=snap)
        content_experiment_repository.update_variant(
            db,
            variant,
            metrics_snapshot=self._normalize.sanitize_raw(metrics_snapshot),
            er_percent=normalized.er_percent,
            ctr_percent=normalized.ctr_percent,
            actual_engagement_score=score.get("actual_engagement_score"),
            status="measured",
        )
        return {
            "variant_id": variant_id,
            "er_percent": normalized.er_percent,
            "ctr_percent": normalized.ctr_percent,
            "actual_engagement_score": score.get("actual_engagement_score"),
        }

    # ------------------------------------------------------------------ #
    # Выбор winner                                                        #
    # ------------------------------------------------------------------ #

    def choose_winner(
        self,
        db: Session,
        experiment_id: int,
        method: str = "auto",
        variant_id: int | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Выбрать winner (manual клиентом или auto по метрикам) + обновить обучение."""
        experiment = self._get_experiment(db, experiment_id)
        variants = content_experiment_repository.list_variants_for_experiment(db, experiment_id)
        if not variants:
            raise ABTestingError("У эксперимента нет вариантов")

        if method == "manual":
            if variant_id is None:
                raise ABTestingError("Для ручного выбора нужен variant_id")
            winner = next((v for v in variants if v.id == variant_id), None)
            if winner is None:
                raise ABTestingError("Вариант не принадлежит эксперименту")
            reason = "manual_selection"
            confidence = 1.0
        else:
            # auto: анализ платный.
            account_id = self._account_id(db, experiment.project_id)
            units = self._economics.estimate_experiment_analysis_units()
            self._charge(
                db,
                account_id,
                units,
                USAGE_EXPERIMENT_ANALYSIS,
                f"experiment-winner-{experiment_id}",
                experiment.project_id,
            )
            decision = self._analysis.select_winner(variants)
            winner = next((v for v in variants if v.id == decision["variant_id"]), variants[0])
            reason = decision["reason"]
            confidence = float(decision["confidence"])

        losers = [v for v in variants if v.id != winner.id]
        content_experiment_repository.mark_winner(db, winner, reason)
        for loser in losers:
            content_experiment_repository.update_variant(db, loser, status="loser")

        profile_version = self._apply_winner_learning(db, experiment, winner, losers)
        content_experiment_repository.complete_experiment(
            db, experiment, winner.id, confidence, datetime.now(UTC), profile_version
        )
        self._write_audit(
            db,
            experiment.project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_WINNER_SELECTED,
            {
                "experiment_id": experiment_id,
                "variant_id": winner.id,
                "method": method,
                "reason": reason,
            },
        )
        self._write_audit(
            db,
            experiment.project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_COMPLETED,
            {"experiment_id": experiment_id, "winner_variant_id": winner.id},
        )
        try:
            from app.services.notification_service import NotificationService

            NotificationService(settings=self._settings).notify_project_owner(
                db,
                experiment.project_id,
                "experiment_winner_selected",
                "Выбран победитель A/B-теста",
                f"Эксперимент #{experiment_id}: выбран вариант #{winner.id}.",
                actor_user_id=current_user_id,
                entity_type="content_experiment",
                entity_id=experiment_id,
                action_url=f"/ui/projects/{experiment.project_id}/experiments",
            )
        except Exception:  # noqa: BLE001 — уведомление не критично
            logger.warning("experiment winner notification failed", exc_info=False)
        return self.build_experiment_summary(db, experiment_id)

    def cancel_experiment(
        self, db: Session, experiment_id: int, current_user_id: int | None = None
    ) -> dict[str, Any]:
        """Отменить эксперимент (без списаний/возвратов на MVP)."""
        experiment = self._get_experiment(db, experiment_id)
        content_experiment_repository.cancel_experiment(db, experiment)
        self._write_audit(
            db,
            experiment.project_id,
            current_user_id,
            audit_actions.ACTION_EXPERIMENT_CANCELED,
            {"experiment_id": experiment_id},
        )
        return self.build_experiment_summary(db, experiment_id)

    # ------------------------------------------------------------------ #
    # Сводка эксперимента                                                #
    # ------------------------------------------------------------------ #

    def build_experiment_summary(self, db: Session, experiment_id: int) -> dict[str, Any]:
        """Сводка эксперимента для UI: варианты, winner, различия оценок, обучение."""
        experiment = self._get_experiment(db, experiment_id)
        variants = content_experiment_repository.list_variants_for_experiment(db, experiment_id)
        ranked = self._analysis.compare_variants(variants) if variants else []
        winner = next((v for v in variants if v.is_winner), None)
        losers = [v for v in variants if not v.is_winner]
        return {
            "experiment": self._experiment_view(experiment),
            "variants": [self._variant_view(v) for v in variants],
            "ranking": ranked,
            "winner": self._variant_view(winner) if winner is not None else None,
            "winner_explanation": (
                self._analysis.explain_winner(winner, losers) if winner is not None else []
            ),
            "score_spread": self._score_spread(ranked),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _materialize_variants(
        self,
        db: Session,
        experiment: Any,
        project_id: int,
        account_id: int | None,
        platform_key: str | None,
        variants: list[dict[str, Any]],
    ) -> None:
        """Создать draft/needs_review посты для вариантов и записи вариантов."""
        for spec in variants:
            notes = {
                "source": "ab_experiment",
                "experiment_id": experiment.id,
                "experiment_variant": spec["variant_key"],
                "angle": spec.get("angle"),
                "cta_type": spec.get("cta_type"),
                "cta": spec.get("cta_text"),
                "media_type": spec.get("media_strategy"),
                "live": False,
            }
            post = post_repository.create_post(
                db,
                PostCreate(
                    project_id=project_id,
                    title=spec.get("title") or "",
                    status="needs_review",
                    hashtags=[],
                    generation_notes=notes,
                    telegram_text=spec["text"] if platform_key == "telegram" else None,
                    instagram_text=spec["text"] if platform_key == "instagram" else None,
                    vk_text=spec["text"] if platform_key not in ("telegram", "instagram") else None,
                ),
            )
            content_experiment_repository.create_variant(
                db,
                experiment_id=experiment.id,
                account_id=account_id,
                project_id=project_id,
                post_id=post.id,
                variant_key=spec["variant_key"],
                title=spec.get("title") or "",
                angle=spec.get("angle"),
                cta_type=spec.get("cta_type"),
                text_length_type=spec.get("text_length_type"),
                media_strategy=spec.get("media_strategy"),
                publish_time_strategy=spec.get("publish_time_strategy"),
                status="needs_review",
                variant_metadata={"cta_text": spec.get("cta_text")},
            )
            self._write_audit(
                db,
                project_id,
                experiment.created_by_user_id,
                audit_actions.ACTION_EXPERIMENT_VARIANT_CREATED,
                {"experiment_id": experiment.id, "variant_key": spec["variant_key"]},
            )

    def _score_experiment_variants(self, db: Session, experiment_id: int) -> None:
        """Посчитать quality/predicted/fit для каждого варианта (по профилю)."""
        variants = content_experiment_repository.list_variants_for_experiment(db, experiment_id)
        for variant in variants:
            if variant.post_id is None:
                continue
            post = post_repository.get_post_by_id(db, variant.post_id)
            if post is None:
                continue
            scored = self._learning_svc().score_content_candidate(
                db, variant.project_id, self._experiment_platform(db, experiment_id), post
            )
            content_experiment_repository.update_variant(
                db,
                variant,
                quality_score=scored["quality_score"],
                predicted_engagement_score=scored["predicted_engagement_score"],
                score_breakdown={
                    "quality_score": scored["quality_score"],
                    "predicted_engagement_score": scored["predicted_engagement_score"],
                    "fit_score": scored["fit_score"],
                },
                learning_reasons=scored.get("learning_reasons", [])[:6],
            )

    def _apply_winner_learning(
        self, db: Session, experiment: Any, winner: Any, losers: list[Any]
    ) -> int | None:
        """Winner → положительный сигнал, losers → слабые. Обновляет профиль."""
        platform = experiment.platform_key
        if winner.post_id is not None:
            self._learning_svc().record_review_feedback(
                db, winner.post_id, "approved", platform_key=platform
            )
        for loser in losers:
            if loser.post_id is not None:
                self._learning_svc().record_review_feedback(
                    db,
                    loser.post_id,
                    "rejected",
                    reason_tags=["ab_loser"],
                    platform_key=platform,
                )
        profile = client_learning_repository.get_profile(db, experiment.project_id, None)
        return profile.profile_version if profile is not None else None

    # --- Биллинг / включённость / идемпотентность ---

    def _ensure_enabled(self, db: Session, project_id: int, user_id: int | None) -> None:
        if not bool(getattr(self._resolve_settings(), "ab_testing_enabled", True)):
            self._write_audit(
                db,
                project_id,
                user_id,
                audit_actions.ACTION_AB_TEST_BLOCKED,
                {"reason": "ab_testing_disabled"},
            )
            raise ABTestingError("A/B-тестирование выключено конфигурацией")

    def _charge(
        self,
        db: Session,
        account_id: int | None,
        units: int,
        usage_type: str,
        idempotency_key: str,
        project_id: int,
    ) -> int:
        if units <= 0 or account_id is None:
            return 0
        self._billing.ensure_balance(db, account_id, units)
        ledger = self._billing.debit_for_action(
            db,
            account_id,
            units=units,
            usage_type=usage_type,
            idempotency_key=idempotency_key,
            project_id=project_id,
        )
        return units if ledger is not None else 0

    def _ensure_balance(self, db: Session, account_id: int | None, units: int) -> None:
        """Проверить баланс до создания (без списания)."""
        if units > 0 and account_id is not None:
            self._billing.ensure_balance(db, account_id, units)

    def _debit_created(
        self,
        db: Session,
        account_id: int | None,
        units: int,
        experiment_id: int,
        project_id: int,
        idempotency_key: str | None,
    ) -> int:
        """Списать за созданный эксперимент. Ключ по id эксперимента — уникален на каждый
        созданный эксперимент, поэтому дубликат без клиентского ключа не бывает бесплатным."""
        if units <= 0 or account_id is None:
            return 0
        key = idempotency_key or f"experiment-create-{experiment_id}"
        ledger = self._billing.debit_for_action(
            db,
            account_id,
            units=units,
            usage_type=USAGE_AB_EXPERIMENT_CREATE,
            idempotency_key=key,
            project_id=project_id,
        )
        return units if ledger is not None else 0

    def _find_by_idempotency(
        self, db: Session, project_id: int, idempotency_key: str | None
    ) -> Any | None:
        if not idempotency_key:
            return None
        for exp in content_experiment_repository.list_experiments_for_project(
            db, project_id, limit=200
        ):
            meta = exp.experiment_metadata or {}
            if isinstance(meta, dict) and meta.get("idempotency_key") == idempotency_key:
                return exp
        return None

    def _score_round(self, db: Session, experiment_id: int) -> int:
        # Позволяет платному re-score списывать каждый явный вызов (по числу measured).
        variants = content_experiment_repository.list_variants_for_experiment(db, experiment_id)
        return sum(1 for v in variants if v.status == "measured")

    # --- Утилиты представления ---

    @staticmethod
    def _creation_metadata(idempotency_key: str | None, units: int, origin: str) -> dict[str, Any]:
        meta: dict[str, Any] = {"origin": origin, "units_estimated": units}
        if idempotency_key:
            meta["idempotency_key"] = idempotency_key
        return meta

    @staticmethod
    def _variant_preview(spec: dict[str, Any]) -> dict[str, Any]:
        text = str(spec.get("text", ""))
        return {
            "variant_key": spec.get("variant_key"),
            "title": spec.get("title"),
            "angle": spec.get("angle"),
            "cta_type": spec.get("cta_type"),
            "text_length_type": spec.get("text_length_type"),
            "media_strategy": spec.get("media_strategy"),
            "text_preview": (text[:220] + "…") if len(text) > 220 else text,
        }

    @staticmethod
    def _experiment_view(exp: Any) -> dict[str, Any]:
        return {
            "id": exp.id,
            "project_id": exp.project_id,
            "platform_key": exp.platform_key,
            "experiment_type": exp.experiment_type,
            "title": exp.title,
            "hypothesis": exp.hypothesis,
            "status": exp.status,
            "source_post_id": exp.source_post_id,
            "winner_variant_id": exp.winner_variant_id,
            "confidence_score": round(exp.confidence_score, 3),
            "created_at": exp.created_at.isoformat() if exp.created_at else None,
            "completed_at": exp.completed_at.isoformat() if exp.completed_at else None,
        }

    @staticmethod
    def _variant_view(variant: Any) -> dict[str, Any]:
        if variant is None:
            return {}
        return {
            "id": variant.id,
            "variant_key": variant.variant_key,
            "title": variant.title,
            "angle": variant.angle,
            "cta_type": variant.cta_type,
            "text_length_type": variant.text_length_type,
            "media_strategy": variant.media_strategy,
            "status": variant.status,
            "post_id": variant.post_id,
            "quality_score": variant.quality_score,
            "predicted_engagement_score": variant.predicted_engagement_score,
            "actual_engagement_score": variant.actual_engagement_score,
            "er_percent": variant.er_percent,
            "ctr_percent": variant.ctr_percent,
            "is_winner": variant.is_winner,
            "winner_reason": variant.winner_reason,
            "learning_reasons": list(variant.learning_reasons or []),
        }

    @staticmethod
    def _score_spread(ranked: list[dict[str, Any]]) -> float:
        if len(ranked) < 2:
            return 0.0
        return round(float(ranked[0]["score"]) - float(ranked[-1]["score"]), 2)

    def _clamp_variant_count(self, count: int) -> int:
        max_v = int(getattr(self._resolve_settings(), "ab_testing_max_variants", 3))
        return max(2, min(max_v, min(3, int(count or 2))))

    @staticmethod
    def _post_platform(post: Any) -> str | None:
        if post.vk_text:
            return "vk"
        if post.telegram_text:
            return "telegram"
        if post.instagram_text:
            return "instagram"
        return None

    def _experiment_platform(self, db: Session, experiment_id: int) -> str | None:
        exp = content_experiment_repository.get_experiment_by_id(db, experiment_id)
        return exp.platform_key if exp is not None else None

    def _get_experiment(self, db: Session, experiment_id: int) -> Any:
        exp = content_experiment_repository.get_experiment_by_id(db, experiment_id)
        if exp is None:
            raise ABTestingError(f"Эксперимент id={experiment_id} не найден")
        return exp

    def _get_variant(self, db: Session, variant_id: int) -> Any:
        variant = content_experiment_repository.get_variant_by_id(db, variant_id)
        if variant is None:
            raise ABTestingError(f"Вариант id={variant_id} не найден")
        return variant

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise ABTestingError(f"Проект id={project_id} не найден")
        return project.account_id

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _write_audit(
        self,
        db: Session,
        project_id: int,
        user_id: int | None,
        action: str,
        metadata: dict[str, Any],
    ) -> None:
        if self._audit is None:
            from app.services.audit_log_service import AuditLogService

            self._audit = AuditLogService()
        account_id = self._account_id_safe(db, project_id)
        self._audit.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=project_id,
            entity_type="content_experiment",
            metadata=metadata,
        )

    @staticmethod
    def _account_id_safe(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None


def get_ab_testing_service() -> ABTestingService:
    """DI-фабрика сервиса A/B-тестирования."""
    return ABTestingService()
