"""Автовыбор медиа для слота расписания (auto media selection) — v0.4.5.

Worker для выбранной темы подбирает media strategy (text_only/single_image/media_group/
carousel_ready/video_later/no_media_available) и конкретные media assets по тегам/теме/
платформе/обучению/A-B winners/метрикам/доступности и сохраняет «почему бот выбрал эти
медиа» (:class:`ScheduleMediaDecision`). Пост создаётся только как draft/needs_review —
live-публикаций нет; публичные ссылки автоматически не создаются.

БЕЗОПАСНОСТЬ:
- никаких live-публикаций и внешних API-вызовов; публичные ссылки не создаются по умолчанию;
- автовыбор worker-ом ВЫКЛЮЧЕН по умолчанию (config), dry-run по умолчанию;
- строгая project/account-изоляция; без секретов и внутренних путей к файлам в ответах.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    client_learning_repository,
    content_experiment_repository,
    media_asset_repository,
    post_repository,
    project_repository,
    schedule_media_decision_repository,
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

logger = get_logger(__name__)

# Пригодные к публикации статусы медиа.
_USABLE_STATUSES = ("approved", "approved_video")
# Группы тегов медиа, по которым ищем совпадение с темой.
_TAG_GROUPS = ("products", "technologies", "details", "categories", "use_cases", "topics")
_VIDEO_EXTS = ("mov", "mp4", "m4v", "avi", "mkv", "webm")

# Веса скоринга медиа-кандидата (MVP, из спецификации).
_SCORE_EXACT_TAG = 25
_SCORE_TOPIC_WORD = 15
_SCORE_CATEGORY_TAG = 15
_SCORE_HIGH_PERF = 15
_SCORE_NOVELTY = 10
_PEN_RECENT_MEDIA = 20
_PEN_VIDEO_UNSUPPORTED = 30
_PEN_HEIC = 5
# Стратегия-уровневые бонусы/штрафы.
_SCORE_AB_WINNER_STRATEGY = 15
_SCORE_GROUP_FIT = 10
_PEN_NO_MEDIA_PLAN = 20
_PEN_IG_NO_HTTPS = 25

# Платформы, поддерживающие несколько изображений одной публикацией.
_GROUP_PLATFORMS = ("telegram", "vk", "instagram")


class MediaDecisionError(Exception):
    """Ошибка автовыбора медиа (нет проекта/плана) — API → 400."""


class ScheduleMediaDecisionService:
    """Выбор media strategy + конкретных медиа для слота + запись решения (без live)."""

    def __init__(
        self,
        topic_decision_service: Any | None = None,
        learning_service: ClientLearningService | None = None,
        audit_service: AuditLogService | None = None,
        quality_service: Any | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._topic = topic_decision_service
        self._learning = learning_service
        self._audit = audit_service
        # v0.4.6: оценка качества медиа (правило-ориентированная, без внешнего AI). Ленивая.
        self._quality = quality_service
        # v0.4.7: похожесть/дедупликация медиа (fingerprint-based). Ленивая.
        self._similarity: Any | None = None
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview (без записи, без биллинга)                               #
    # ------------------------------------------------------------------ #

    def preview_media_decision_for_plan(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan_id: int | None = None,
        topic_decision_id: int | None = None,
    ) -> dict[str, Any]:
        """Предпросмотр медиа-решения (без записи и без списания)."""
        plan, category = self._resolve_plan_category(db, project_id, plan_id)
        topic_decision = self._resolve_topic_decision(db, project_id, topic_decision_id)
        decision = self.choose_media_for_schedule(
            db,
            project_id,
            platform_key,
            topic_decision=topic_decision,
            plan=plan,
            category=category,
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_DECISION_PREVIEWED,
            {"platform_key": platform_key, "selected_strategy": decision["selected_strategy"]},
        )
        return {**decision, "writes": False}

    # ------------------------------------------------------------------ #
    # 2. Создание решения (запись, без биллинга)                          #
    # ------------------------------------------------------------------ #

    def create_media_decision_for_plan(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        plan_id: int | None = None,
        topic_decision_id: int | None = None,
        idempotency_key: str | None = None,
        worker_owner_id: str | None = None,
        schedule_run_id: int | None = None,
        status: str = "selected",
    ) -> dict[str, Any]:
        """Создать запись :class:`ScheduleMediaDecision` (без поста и без live)."""
        # Ключ идемпотентности неймспейсим project_id — исключаем межарендную коллизию.
        effective_key = f"p{project_id}-{idempotency_key}" if idempotency_key is not None else None
        if effective_key is not None:
            existing = schedule_media_decision_repository.get_by_idempotency_key(db, effective_key)
            if existing is not None and existing.project_id == project_id:
                return {**self._decision_view(existing), "outcome": "skipped_duplicate"}
        plan, category = self._resolve_plan_category(db, project_id, plan_id)
        topic_decision = self._resolve_topic_decision(db, project_id, topic_decision_id)
        payload = self.choose_media_for_schedule(
            db,
            project_id,
            platform_key,
            topic_decision=topic_decision,
            plan=plan,
            category=category,
        )
        account_id = self._account_id(db, project_id)
        row = schedule_media_decision_repository.create_decision(
            db,
            account_id=account_id,
            project_id=project_id,
            platform_key=platform_key,
            publishing_plan_id=plan.id if plan is not None else plan_id,
            schedule_run_id=schedule_run_id,
            schedule_topic_decision_id=(topic_decision.get("id") if topic_decision else None),
            selected_strategy=payload["selected_strategy"],
            selected_media_asset_ids=payload["selected_media_asset_ids"],
            selected_media_variant_ids=payload.get("selected_media_variant_ids", []),
            selected_media_tags=payload.get("selected_media_tags", []),
            selected_media_count=payload["selected_media_count"],
            needs_public_image_url=payload["needs_public_image_url"],
            media_proxy_ready=payload["media_proxy_ready"],
            public_link_ids=[],
            decision_source=payload["decision_source"],
            status=status,
            confidence_score=float(payload["confidence_score"]),
            expected_media_score=payload.get("expected_media_score"),
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
            audit_actions.ACTION_MEDIA_DECISION_CREATED,
            {
                "decision_id": row.id,
                "platform_key": platform_key,
                "selected_strategy": row.selected_strategy,
                "selected_media_count": row.selected_media_count,
                "decision_source": row.decision_source,
                "confidence": row.confidence_score,
                "risk_flags": list(row.risk_flags or []),
            },
        )
        if "low_confidence" in (row.risk_flags or []):
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_DECISION_LOW_CONFIDENCE,
                {"decision_id": row.id, "confidence": row.confidence_score},
            )
        if "no_media" in (row.risk_flags or []) or row.selected_strategy == "no_media_available":
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_DECISION_NO_MEDIA,
                {"decision_id": row.id, "strategy": row.selected_strategy},
            )
        if row.decision_source in ("manual_category", "fallback"):
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_DECISION_FALLBACK_USED,
                {"decision_id": row.id, "decision_source": row.decision_source},
            )
        return {**self._decision_view(row), "outcome": "created"}

    # ------------------------------------------------------------------ #
    # 3. Основной алгоритм выбора                                         #
    # ------------------------------------------------------------------ #

    def choose_media_for_schedule(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        topic_decision: dict[str, Any] | None = None,
        plan: Any | None = None,
        category: Any | None = None,
    ) -> dict[str, Any]:
        """Подобрать media strategy + медиа для слота. Ничего не публикует."""
        context = self._build_context(db, project_id, platform_key, topic_decision, category)
        images, videos, scored = self.build_media_candidates(
            db, project_id, platform_key, topic_decision, category, context
        )
        # v0.4.7: не выбирать почти одинаковые фото в media_group (при наличии альтернатив).
        images, diversity_info = self._diversify_images(db, project_id, images)
        strategy, chosen, source, strat_reasons = self.choose_strategy(
            platform_key, images, videos, topic_decision, context
        )
        chosen_ids = [a["id"] for a in chosen]
        chosen_tags = sorted({t for a in chosen for t in a["tags"]})[:12]
        variant_ids = [a["variant_id"] for a in chosen if a.get("variant_id")]
        needs_public = platform_key == "instagram" and strategy not in (
            "text_only",
            "no_media_available",
        )
        proxy_ready = bool(context["media_proxy_ready"])
        confidence = self._confidence(strategy, chosen, context, needs_public, proxy_ready)
        risks = self._risk_flags(
            strategy, chosen, videos, context, platform_key, confidence, needs_public, proxy_ready
        )
        reasons = (
            self.explain_media_decision(strategy, chosen, context, needs_public) + strat_reasons
        )
        alternatives = self._alternatives(platform_key, images, videos, strategy, context)
        quality_summary = self._media_quality_summary(chosen)
        if quality_summary.get("weak_selected_count") and quality_summary["selected_media_scores"]:
            reasons.append("Внимание: среди выбранных есть медиа ниже порога качества.")
        risks = self._augment_quality_risks(risks, quality_summary)
        # v0.4.7: сводка разнообразия/дублей выбранных медиа + risk-флаги.
        diversity_summary = self._media_diversity_summary(
            db, project_id, chosen, strategy, diversity_info, context
        )
        risks = self._augment_diversity_risks(risks, diversity_summary, strategy)
        if diversity_summary.get("similar_media_skipped_count"):
            reasons.append(
                f"Пропущено похожих фото: {diversity_summary['similar_media_skipped_count']} "
                "(для разнообразия подборки)."
            )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "selected_strategy": strategy,
            "selected_media_asset_ids": chosen_ids,
            "selected_media_variant_ids": variant_ids,
            "selected_media_tags": chosen_tags,
            "selected_media_count": len(chosen_ids),
            "needs_public_image_url": needs_public,
            "media_proxy_ready": proxy_ready,
            "decision_source": source,
            "confidence_score": confidence,
            "expected_media_score": (
                int(sum(a["score"] for a in chosen) / len(chosen)) if chosen else None
            ),
            "learning_profile_version": context["profile_version"],
            "alternatives": alternatives,
            "source_signals": sorted(context["signals"])[:10],
            "risk_flags": risks,
            "reasons": reasons[:8],
            "media_quality_summary": quality_summary,
            "media_diversity_summary": diversity_summary,
            "decision_metadata": {
                "candidate_count": len(scored),
                "image_candidates": len(images),
                "video_candidates": len(videos),
                "min_confidence": self._min_confidence(),
                "max_images": self._max_images(platform_key),
                "media_quality_summary": quality_summary,
                "media_diversity_summary": diversity_summary,
            },
        }

    def _diversify_images(
        self, db: Session, project_id: int, images: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Убрать почти-дубли из пула изображений (жадно, canonical/лучший первым). v0.4.7."""
        if not self._diversity_enabled() or len(images) <= 1:
            return images, {"skipped": 0, "warnings": []}
        diverse: list[dict[str, Any]] = []
        skipped = 0
        warnings: list[str] = []
        cache: dict[int, Any] = {}
        for cand in images:
            dup_of = None
            for kept in diverse:
                if self._assets_similar(db, project_id, cand["id"], kept["id"], cache):
                    dup_of = kept["id"]
                    break
            if dup_of is not None:
                skipped += 1
                warnings.append(f"Похоже на уже выбранное медиа #{dup_of} — пропущено.")
            else:
                diverse.append(cand)
        return diverse, {"skipped": skipped, "warnings": warnings[:6]}

    def _assets_similar(
        self, db: Session, project_id: int, asset_a: int, asset_b: int, cache: dict[int, Any]
    ) -> bool:
        """Похожи ли два ассета по fingerprint/кластеру (в пределах проекта)."""
        from app.repositories import (
            media_duplicate_cluster_repository,
            media_fingerprint_repository,
        )

        cluster = media_duplicate_cluster_repository.find_cluster_for_media_asset(
            db, project_id, asset_a
        )
        if cluster is not None and asset_b in (cluster.member_media_asset_ids or []):
            return True
        if asset_a not in cache:
            cache[asset_a] = media_fingerprint_repository.get_latest_for_asset(
                db, project_id, asset_a
            )
        if asset_b not in cache:
            cache[asset_b] = media_fingerprint_repository.get_latest_for_asset(
                db, project_id, asset_b
            )
        fpa, fpb = cache[asset_a], cache[asset_b]
        if fpa is None or fpb is None:
            return False
        cmp = self._similarity_svc().compare_fingerprints(fpa, fpb)
        return bool(cmp["similarity_score"] >= self._diversity_threshold())

    def _media_diversity_summary(
        self,
        db: Session,
        project_id: int,
        chosen: list[dict[str, Any]],
        strategy: str,
        diversity_info: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Свод разнообразия: diversity_score, пропущенные похожие, кластеры, предупреждения."""
        from app.repositories import media_duplicate_cluster_repository

        skipped = int(diversity_info.get("skipped", 0))
        cluster_ids: set[int] = set()
        similar_recent = False
        recent = context.get("recent_media_ids") or set()
        for cand in chosen:
            cluster = media_duplicate_cluster_repository.find_cluster_for_media_asset(
                db, project_id, cand["id"]
            )
            if cluster is not None:
                cluster_ids.add(cluster.id)
                if any(mid in recent for mid in (cluster.member_media_asset_ids or [])):
                    similar_recent = True
        chosen_n = len(chosen)
        diversity_score = round(chosen_n / max(1, chosen_n + skipped), 3)
        return {
            "diversity_score": diversity_score,
            "similar_media_skipped_count": skipped,
            "duplicate_cluster_ids": sorted(cluster_ids),
            "selected_similarity_warnings": list(diversity_info.get("warnings", []))[:6],
            "similar_media_recently_used": similar_recent,
        }

    @staticmethod
    def _augment_diversity_risks(
        risks: list[str], diversity_summary: dict[str, Any], strategy: str
    ) -> list[str]:
        """Добавить risk-флаги разнообразия/дублей."""
        out = list(risks)
        if diversity_summary.get("duplicate_cluster_ids"):
            out.append("duplicate_candidate")
        if strategy in ("media_group", "carousel_ready") and (
            diversity_summary.get("similar_media_skipped_count")
            and diversity_summary.get("diversity_score", 1.0) < 0.75
        ):
            out.append("low_diversity_media_group")
        if diversity_summary.get("similar_media_recently_used"):
            out.append("similar_media_recently_used")
        return list(dict.fromkeys(out))

    def _media_quality_summary(self, chosen: list[dict[str, Any]]) -> dict[str, Any]:
        """Свод качества выбранных медиа (v0.4.6): баллы, слабые, дубли, общие проблемы."""
        scores: list[int] = []
        snapshot_ids: list[int] = []
        issues: dict[str, int] = {}
        weak = dup = 0
        min_good = self._min_good_quality()
        for cand in chosen:
            qv = cand.get("quality")
            if not qv:
                continue
            overall = int(qv.get("overall") or 0)
            scores.append(overall)
            if overall < min_good:
                weak += 1
            for issue in qv.get("issues", []) or []:
                issues[issue] = issues.get(issue, 0) + 1
                if issue in ("duplicate_candidate", "recently_used"):
                    dup += 1
            if qv.get("snapshot_id"):
                snapshot_ids.append(int(qv["snapshot_id"]))
        return {
            "selected_media_scores": scores,
            "average_selected_score": (round(sum(scores) / len(scores), 1) if scores else None),
            "weak_selected_count": weak,
            "duplicate_warning_count": dup,
            "common_issues": sorted(issues.items(), key=lambda kv: kv[1], reverse=True)[:6],
            "media_quality_snapshot_ids": snapshot_ids,
        }

    def _augment_quality_risks(
        self, risks: list[str], quality_summary: dict[str, Any]
    ) -> list[str]:
        """Добавить risk-флаги по качеству: weak_media_quality / repeated_media."""
        out = list(risks)
        avg = quality_summary.get("average_selected_score")
        if avg is not None and avg < self._min_good_quality():
            out.append("weak_media_quality")
        if quality_summary.get("duplicate_warning_count"):
            out.append("repeated_media")
        return list(dict.fromkeys(out))

    # ------------------------------------------------------------------ #
    # 4. Кандидаты                                                        #
    # ------------------------------------------------------------------ #

    def build_media_candidates(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None,
        topic_decision: dict[str, Any] | None = None,
        category: Any | None = None,
        context: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        """Отскоренные медиа-кандидаты проекта: (images, videos, all) свежие/лучшие первыми."""
        context = context or self._build_context(
            db, project_id, platform_key, topic_decision, category
        )
        assets = [
            a
            for a in media_asset_repository.list_media_assets_by_project(db, project_id)
            if a.status in _USABLE_STATUSES
        ]
        quality_on = self._media_quality_enabled()
        media_tags = sorted(context["wanted_tags"]) if context.get("wanted_tags") else None
        scored: list[dict[str, Any]] = []
        for asset in assets:
            cand = self.score_media_candidate(db, project_id, platform_key, asset, context)
            # v0.4.6: качество медиа поднимает ранг сильных ассетов (снимок → быстрый dry-run).
            if quality_on:
                try:
                    qv = self._quality_svc().quality_overall_for_asset(
                        db, project_id, asset, platform_key, media_tags=media_tags
                    )
                    cand["quality"] = qv
                    cand["overall_media_score"] = qv["overall"]
                    cand["score"] += round(int(qv["overall"]) / 12)
                except Exception:  # noqa: BLE001 — оценка качества не должна ронять подбор
                    cand["quality"] = None
            scored.append(cand)
        # Только релевантные (совпало хоть что-то) — как в PostMediaSelectionService.
        matched = [c for c in scored if c["matched"]]
        pool = matched or scored  # если совпадений нет — fallback к любым approved
        pool.sort(key=lambda c: (c["score"], c["id"]), reverse=True)
        images = [c for c in pool if not c["is_video"]]
        videos = [c for c in pool if c["is_video"]]
        return images, videos, pool

    # ------------------------------------------------------------------ #
    # 5. Скоринг кандидата                                                #
    # ------------------------------------------------------------------ #

    def score_media_candidate(
        self,
        db: Session,  # noqa: ARG002 — контекст уже собран
        project_id: int,  # noqa: ARG002
        platform_key: str | None,  # noqa: ARG002
        asset: Any,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Отскорить один media asset по тегам/теме/новизне; вернуть breakdown."""
        breakdown: dict[str, int] = {}
        asset_tags = _asset_tags(asset)
        file_lower = str(getattr(asset, "file_name", "") or "").lower()
        is_video = _is_video_name(file_lower)

        exact = _SCORE_EXACT_TAG if (asset_tags & context["wanted_tags"]) else 0
        topic = 0
        if context["topic_tokens"] and (
            (asset_tags & context["topic_tokens"])
            or any(tok in file_lower for tok in context["topic_tokens"] if len(tok) >= 4)
        ):
            topic = _SCORE_TOPIC_WORD
        cat = _SCORE_CATEGORY_TAG if (asset_tags & context["category_tags"]) else 0
        high = _SCORE_HIGH_PERF if (asset_tags & context["high_media_tags"]) else 0
        breakdown["tag_match"] = exact
        breakdown["topic_match"] = topic
        breakdown["category_tag"] = cat
        breakdown["high_perf"] = high

        recent = asset.id in context["recent_media_ids"]
        novelty = -_PEN_RECENT_MEDIA if recent else _SCORE_NOVELTY
        breakdown["novelty"] = novelty

        video_pen = (
            -_PEN_VIDEO_UNSUPPORTED if (is_video and not context["platform_video_ok"]) else 0
        )
        heic_pen = -_PEN_HEIC if file_lower.endswith(".heic") else 0
        breakdown["video_penalty"] = video_pen
        breakdown["heic_penalty"] = heic_pen

        total = exact + topic + cat + high + novelty + video_pen + heic_pen
        matched = bool(exact or topic or cat or high)
        return {
            "id": asset.id,
            "tags": sorted(asset_tags),
            "is_video": is_video,
            "heic": file_lower.endswith(".heic"),
            "recent": recent,
            "score": total,
            "matched": matched,
            "breakdown": breakdown,
            "variant_id": context["variant_by_asset"].get(asset.id),
        }

    # ------------------------------------------------------------------ #
    # 6. Выбор стратегии                                                  #
    # ------------------------------------------------------------------ #

    def choose_strategy(
        self,
        platform_key: str | None,
        images: list[dict[str, Any]],
        videos: list[dict[str, Any]],
        topic_decision: dict[str, Any] | None,
        context: dict[str, Any],
    ) -> tuple[str, list[dict[str, Any]], str, list[str]]:
        """Выбрать media strategy и набор медиа под платформу.

        Возвращает кортеж ``(strategy, chosen, source, reasons)``.
        """
        reasons: list[str] = []
        max_images = self._max_images(platform_key)
        platform = str(platform_key or "").lower()
        source = self._decision_source(images, context)

        if not images and videos:
            reasons.append("Есть только видео — публикуем позже (video_later).")
            return "video_later", videos[:1], source, reasons
        if not images:
            if platform == "instagram":
                reasons.append("Instagram требует изображение, но подходящего медиа нет.")
                return "no_media_available", [], source, reasons
            reasons.append("Подходящих изображений нет — текстовый пост.")
            return "text_only", [], source, reasons

        if len(images) == 1:
            return "single_image", images[:1], source, reasons

        # 2+ изображений: групповая стратегия под платформу.
        capped = images[:max_images]
        if len(images) > max_images:
            reasons.append(f"Изображений больше лимита {max_images} — усечено.")
        if platform == "instagram":
            return "carousel_ready", capped, source, reasons
        if platform in ("telegram", "vk"):
            return "media_group", capped, source, reasons
        # Website/blog/прочее — одна картинка предпочтительнее.
        reasons.append("Для этой площадки предпочтителен single_image.")
        return "single_image", images[:1], source, reasons

    # ------------------------------------------------------------------ #
    # 7. Объяснение                                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def explain_media_decision(
        strategy: str,
        chosen: list[dict[str, Any]],
        context: dict[str, Any],
        needs_public: bool,
    ) -> list[str]:
        """Человекочитаемые причины выбора медиа."""
        reasons: list[str] = []
        if chosen:
            tags = sorted({t for a in chosen for t in a["tags"]})[:3]
            if tags:
                reasons.append(f"Медиа выбрано по тегам: {', '.join(tags)}.")
        if strategy in ("media_group", "carousel_ready"):
            reasons.append(
                f"Формат {strategy} выбран: доступно {len(chosen)} подходящих изображений."
            )
        elif strategy == "single_image":
            reasons.append("Одно подходящее изображение — single_image.")
        elif strategy == "text_only":
            reasons.append("Подходящих изображений нет — текстовый пост.")
        elif strategy == "no_media_available":
            reasons.append("Instagram требует изображение — медиа недоступно.")
        elif strategy == "video_later":
            reasons.append("Есть видео — публикация медиа отложена.")
        if needs_public:
            reasons.append("Instagram требует public image_url (media proxy).")
        if chosen and all(not a["recent"] for a in chosen):
            reasons.append("Медиа не использовалось недавно.")
        if any(a["heic"] for a in chosen):
            reasons.append("Есть риск: HEIC нужно конвертировать перед публикацией.")
        return reasons

    # ------------------------------------------------------------------ #
    # 8. Применение решения к драфту                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def apply_media_decision_to_draft_payload(
        decision: dict[str, Any], base_payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Наложить выбранные медиа/стратегию на payload драфта (без live-публикации)."""
        payload = dict(base_payload)
        asset_ids = list(decision.get("selected_media_asset_ids") or [])
        payload["media_asset_ids"] = asset_ids
        payload["media_strategy"] = decision.get("selected_strategy")
        notes = dict(payload.get("generation_notes", {}) or {})
        notes.update(
            {
                "schedule_media_decision_id": decision.get("id"),
                "selected_media_asset_ids": asset_ids,
                "selected_media_tags": (decision.get("selected_media_tags") or [])[:12],
                "selected_media_strategy": decision.get("selected_strategy"),
                "media_decision_confidence": decision.get("confidence_score"),
                "media_decision_reasons": (decision.get("reasons") or [])[:8],
                "media_decision_source_signals": (decision.get("source_signals") or [])[:8],
                "media_decision_risk_flags": (decision.get("risk_flags") or [])[:8],
                "needs_public_image_url": bool(decision.get("needs_public_image_url")),
                "media_quality_summary": decision.get("media_quality_summary") or {},
                "media_diversity_summary": decision.get("media_diversity_summary") or {},
            }
        )
        payload["generation_notes"] = notes
        return payload

    def mark_decision_applied_to_draft(
        self, db: Session, decision_id: int, schedule_run_id: int | None, post_id: int | None
    ) -> None:
        """Отметить решение как использованное для драфта (+ аудит)."""
        decision = schedule_media_decision_repository.get_by_id(db, decision_id)
        if decision is None:
            return
        schedule_media_decision_repository.mark_applied_to_draft(
            db, decision, schedule_run_id, post_id
        )
        self._write_audit(
            db,
            decision.project_id,
            audit_actions.ACTION_MEDIA_DECISION_APPLIED_TO_DRAFT,
            {"decision_id": decision_id, "post_id": post_id, "schedule_run_id": schedule_run_id},
        )

    def mark_decision_failed(self, db: Session, decision_id: int, error: str) -> None:
        """Отметить решение как failed (без секретов/путей)."""
        decision = schedule_media_decision_repository.get_by_id(db, decision_id)
        if decision is None:
            return
        schedule_media_decision_repository.mark_failed(db, decision, error)
        self._write_audit(
            db,
            decision.project_id,
            audit_actions.ACTION_MEDIA_DECISION_FAILED,
            {"decision_id": decision_id, "error": error[:120]},
        )

    # ------------------------------------------------------------------ #
    # 9. Дашборд                                                          #
    # ------------------------------------------------------------------ #

    def build_media_decision_dashboard(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Сводка медиа-решений проекта для UI."""
        decisions = schedule_media_decision_repository.list_for_project(
            db, project_id, platform_key=platform_key, limit=200
        )
        by_strategy: dict[str, int] = {}
        by_tag: dict[str, int] = {}
        confidences: list[float] = []
        low_conf = no_media = 0
        risks: dict[str, int] = {}
        for d in decisions:
            by_strategy[d.selected_strategy] = by_strategy.get(d.selected_strategy, 0) + 1
            for tag in d.selected_media_tags or []:
                by_tag[tag] = by_tag.get(tag, 0) + 1
            confidences.append(d.confidence_score)
            if "low_confidence" in (d.risk_flags or []):
                low_conf += 1
            if d.selected_strategy == "no_media_available" or "no_media" in (d.risk_flags or []):
                no_media += 1
            for flag in d.risk_flags or []:
                risks[flag] = risks.get(flag, 0) + 1
        avg_conf = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "total": len(decisions),
            "low_confidence_count": low_conf,
            "no_media_count": no_media,
            "avg_confidence": avg_conf,
            "top_strategies": sorted(by_strategy.items(), key=lambda kv: kv[1], reverse=True)[:6],
            "top_media_tags": sorted(by_tag.items(), key=lambda kv: kv[1], reverse=True)[:8],
            "risk_flags": sorted(risks.items(), key=lambda kv: kv[1], reverse=True)[:8],
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
        topic_decision: dict[str, Any] | None,
        category: Any | None,
    ) -> dict[str, Any]:
        """Собрать сигналы: желаемые теги, тема, high-perf медиа, A/B, усталость, media proxy."""
        signals: set[str] = set()
        wanted: set[str] = set()
        topic_tokens: set[str] = set()
        if topic_decision:
            for t in topic_decision.get("selected_media_strategy_tags", []) or []:
                wanted.add(_norm(t))
            topic = str(topic_decision.get("selected_topic") or "")
            for tok in topic.lower().replace("#", " ").split():
                if len(tok) >= 4:
                    topic_tokens.add(tok)
            signals.add("topic_decision")
        category_tags: set[str] = set()
        if category is not None:
            category_tags = {_norm(t) for t in (category.media_tags or [])}
            wanted |= category_tags
            if category_tags:
                signals.add("media_tags")

        # Learning: предпочитаемые медиа-типы и сильные теги.
        summary = self._learning_svc().summarize_learning(db, project_id, platform_key)
        profile = client_learning_repository.get_profile(db, project_id, None)
        profile_version = int(getattr(profile, "profile_version", 0) or 0) if profile else 0
        high_media_tags: set[str] = set()
        if self._use_client_feedback():
            high_media_tags = {_norm(t) for t in summary.get("high_performing_tags", [])} | {
                _norm(t) for t in summary.get("preferred_media_types", [])
            }
            if high_media_tags:
                signals.add("learning_profile")

        # A/B winners: победившая media_strategy.
        ab_strategy = None
        if self._use_ab_winners():
            for variant in content_experiment_repository.list_winners_for_project(db, project_id):
                if variant.media_strategy:
                    ab_strategy = variant.media_strategy
                    signals.add("ab_winner")
                    break

        # Enhanced-варианты (для variant_ids).
        variant_by_asset = self._variant_by_asset(db, project_id)

        # Усталость: недавно использованные media asset id.
        recent_media_ids = self._recent_media_ids(db, project_id)

        # Media proxy готовность (без сети): enabled + https_ready.
        s = self._resolve_settings()
        media_proxy_ready = bool(
            getattr(s, "media_proxy_enabled_effective", False)
            and getattr(s, "media_proxy_https_ready", False)
        )
        return {
            "wanted_tags": wanted,
            "topic_tokens": topic_tokens,
            "category_tags": category_tags,
            "high_media_tags": high_media_tags,
            "ab_strategy": ab_strategy,
            "variant_by_asset": variant_by_asset,
            "recent_media_ids": recent_media_ids,
            "media_proxy_ready": media_proxy_ready,
            "platform_video_ok": False,  # видео в live не грузим на этом этапе
            "profile_version": profile_version or None,
            "profile_confidence": float(summary.get("confidence_score", 0.0) or 0.0),
            "has_media_tags": bool(category_tags or wanted),
            "signals": signals,
        }

    def _variant_by_asset(self, db: Session, project_id: int) -> dict[int, int]:
        from app.repositories import media_asset_variant_repository

        out: dict[int, int] = {}
        for asset in media_asset_repository.list_media_assets_by_project(db, project_id):
            try:
                variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(
                    db, asset.id
                )
            except Exception:  # noqa: BLE001 — вариантов может не быть
                variant = None
            if variant is not None and getattr(variant, "output_path", None):
                out[asset.id] = variant.id
        return out

    def _recent_media_ids(self, db: Session, project_id: int) -> set[int]:
        recent: set[int] = set()
        for post in post_repository.list_recent_posts(db, project_id, limit=self._recency_window()):
            if post.media_asset_id:
                recent.add(post.media_asset_id)
            notes = post.generation_notes or {}
            if isinstance(notes, dict):
                for mid in notes.get("media_asset_ids", []) or []:
                    if isinstance(mid, int):
                        recent.add(mid)
        for d in schedule_media_decision_repository.list_for_project(
            db, project_id, status="applied_to_draft", limit=self._recency_window()
        ):
            for mid in d.selected_media_asset_ids or []:
                if isinstance(mid, int):
                    recent.add(mid)
        return recent

    @staticmethod
    def _decision_source(images: list[dict[str, Any]], context: dict[str, Any]) -> str:
        if not images:
            return "media_availability"
        top = images[0]["breakdown"]
        if top.get("high_perf"):
            return "learning_profile"
        if context.get("ab_strategy"):
            return "ab_winner"
        if top.get("tag_match") or top.get("category_tag"):
            return "media_tags"
        if top.get("topic_match"):
            return "topic_decision"
        return "media_availability"

    def _confidence(
        self,
        strategy: str,
        chosen: list[dict[str, Any]],
        context: dict[str, Any],
        needs_public: bool,
        proxy_ready: bool,
    ) -> float:
        if strategy in ("no_media_available",):
            return round(max(0.0, 0.2 + float(context["profile_confidence"]) * 0.1), 3)
        if strategy == "text_only":
            # Текст — уверенное решение, если у категории нет медиа-тегов (медиа не нужно).
            base = 0.55 if not context["has_media_tags"] else 0.35
            return round(base, 3)
        avg = sum(a["score"] for a in chosen) / len(chosen) if chosen else 0.0
        raw = 0.30 + 0.010 * avg
        if strategy in ("media_group", "carousel_ready"):
            raw += 0.05
        if context.get("ab_strategy") == strategy:
            raw += 0.05
        if needs_public and not proxy_ready:
            raw -= 0.10
        return round(max(0.0, min(1.0, raw)), 3)

    def _risk_flags(
        self,
        strategy: str,
        chosen: list[dict[str, Any]],
        videos: list[dict[str, Any]],
        context: dict[str, Any],
        platform_key: str | None,
        confidence: float,
        needs_public: bool,
        proxy_ready: bool,
    ) -> list[str]:
        flags: list[str] = []
        if strategy in ("no_media_available", "text_only") and context["has_media_tags"]:
            flags.append("no_media")
        if confidence < self._min_confidence():
            flags.append("low_confidence")
        if chosen and all(a["recent"] for a in chosen):
            flags.append("repeated_media")
        if needs_public:
            flags.append("platform_requires_public_url")
            if not proxy_ready:
                flags.append("media_proxy_not_https")
        if any(a["heic"] for a in chosen):
            flags.append("heic_conversion_needed")
        if strategy in ("media_group", "carousel_ready") and len(chosen) >= self._max_images(
            platform_key
        ):
            flags.append("too_many_images")
        if videos and strategy != "video_later":
            flags.append("video_not_supported")
        if not context["has_media_tags"] and strategy in ("no_media_available",):
            flags.append("missing_media_tags")
        if chosen and max((a["score"] for a in chosen), default=0) < _SCORE_TOPIC_WORD:
            flags.append("weak_media_match")
        return list(dict.fromkeys(flags))

    def _alternatives(
        self,
        platform_key: str | None,
        images: list[dict[str, Any]],
        videos: list[dict[str, Any]],
        strategy: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        alts: list[dict[str, Any]] = []
        if len(images) >= 1 and strategy != "single_image":
            alts.append({"strategy": "single_image", "media_count": 1})
        if not images:
            alts.append({"strategy": "text_only", "media_count": 0})
        if videos:
            alts.append({"strategy": "video_later", "media_count": len(videos)})
        return alts[: self._settings_max_alt()]

    def _decision_view(self, decision: Any) -> dict[str, Any]:
        # ВНИМАНИЕ: только безопасные поля. Никаких yandex_disk_path/внутренних путей.
        return {
            "id": decision.id,
            "project_id": decision.project_id,
            "platform_key": decision.platform_key,
            "publishing_plan_id": decision.publishing_plan_id,
            "schedule_run_id": decision.schedule_run_id,
            "schedule_topic_decision_id": decision.schedule_topic_decision_id,
            "selected_strategy": decision.selected_strategy,
            "selected_media_asset_ids": list(decision.selected_media_asset_ids or []),
            "selected_media_variant_ids": list(decision.selected_media_variant_ids or []),
            "selected_media_tags": list(decision.selected_media_tags or []),
            "selected_media_count": decision.selected_media_count,
            "needs_public_image_url": decision.needs_public_image_url,
            "media_proxy_ready": decision.media_proxy_ready,
            "decision_source": decision.decision_source,
            "status": decision.status,
            "confidence_score": round(decision.confidence_score, 3),
            "expected_media_score": decision.expected_media_score,
            "learning_profile_version": decision.learning_profile_version,
            "alternatives": list(decision.alternatives or []),
            "source_signals": list(decision.source_signals or []),
            "risk_flags": list(decision.risk_flags or []),
            "reasons": list(decision.reasons or []),
            "media_quality_summary": (decision.decision_metadata or {}).get(
                "media_quality_summary", {}
            ),
            "media_diversity_summary": (decision.decision_metadata or {}).get(
                "media_diversity_summary", {}
            ),
            "created_at": decision.created_at.isoformat() if decision.created_at else None,
        }

    def _resolve_topic_decision(
        self, db: Session, project_id: int, topic_decision_id: int | None
    ) -> dict[str, Any] | None:
        if topic_decision_id is None:
            return None
        row = schedule_topic_decision_repository.get_by_id(db, topic_decision_id)
        if row is None or row.project_id != project_id:
            raise MediaDecisionError("Topic decision не принадлежит проекту")
        return {
            "id": row.id,
            "selected_topic": row.selected_topic,
            "selected_media_strategy_tags": [row.selected_topic] if row.selected_topic else [],
        }

    def _resolve_plan_category(
        self, db: Session, project_id: int, plan_id: int | None
    ) -> tuple[Any | None, Any | None]:
        plan = None
        category = None
        if plan_id is not None:
            plan = crm_repo.get_plan_by_id(db, plan_id)
            if plan is not None and plan.project_id != project_id:
                raise MediaDecisionError("План не принадлежит проекту")
            if plan is not None:
                category = crm_repo.get_category_by_id(db, plan.category_id)
        if category is None:
            config = crm_repo.get_config_by_project_id(db, project_id)
            if config is not None:
                cats = crm_repo.list_categories_by_config(db, config.id)
                category = cats[0] if cats else None
        if category is not None and category.project_id != project_id:
            raise MediaDecisionError("Категория не принадлежит проекту")
        return plan, category

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise MediaDecisionError(f"Проект id={project_id} не найден")
        return project.account_id

    # --- Настройки ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _enabled(self) -> bool:
        return bool(self._resolve_settings().auto_media_selection_enabled_effective)

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().auto_media_selection_worker_enabled_effective)

    def _min_confidence(self) -> float:
        return float(self._resolve_settings().auto_media_selection_min_confidence_safe)

    def _recency_window(self) -> int:
        return max(10, int(self._resolve_settings().auto_media_selection_recency_days_safe))

    def _max_images(self, platform_key: str | None) -> int:
        return int(
            self._resolve_settings().auto_media_selection_max_images_for_platform(platform_key)
        )

    def _settings_max_alt(self) -> int:
        return 5

    def _use_ab_winners(self) -> bool:
        return bool(getattr(self._resolve_settings(), "auto_media_selection_use_ab_winners", True))

    def _use_client_feedback(self) -> bool:
        return bool(
            getattr(self._resolve_settings(), "auto_media_selection_use_client_feedback", True)
        )

    def _media_quality_enabled(self) -> bool:
        return bool(
            getattr(self._resolve_settings(), "media_quality_scoring_enabled_effective", False)
        )

    def _min_good_quality(self) -> int:
        return int(getattr(self._resolve_settings(), "media_quality_min_good_score_safe", 70))

    def _diversity_enabled(self) -> bool:
        s = self._resolve_settings()
        return bool(
            getattr(s, "media_fingerprinting_enabled_effective", False)
            and getattr(s, "media_similarity_dedup_enabled", True)
        )

    def _diversity_threshold(self) -> float:
        return float(
            getattr(self._resolve_settings(), "media_duplicate_cluster_min_score_safe", 0.82)
        )

    # --- Ленивые зависимости ---

    def _quality_svc(self) -> Any:
        if self._quality is None:
            from app.services.media_quality_service import MediaQualityService

            self._quality = MediaQualityService(settings=self._settings)
        return self._quality

    def _similarity_svc(self) -> Any:
        if self._similarity is None:
            from app.services.media_similarity_service import MediaSimilarityService

            self._similarity = MediaSimilarityService(settings=self._settings)
        return self._similarity

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

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
            entity_type="schedule_media_decision",
            metadata=metadata,
        )


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _asset_tags(asset: Any) -> set[str]:
    tags = getattr(asset, "tags", None) or {}
    values: set[str] = set()
    for group in _TAG_GROUPS:
        for value in tags.get(group, []) or []:
            norm = _norm(value)
            if norm:
                values.add(norm)
    return values


def _is_video_name(file_name: str | None) -> bool:
    name = str(file_name or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    return ext in _VIDEO_EXTS


def get_media_decision_service() -> ScheduleMediaDecisionService:
    """DI-фабрика сервиса автовыбора медиа."""
    return ScheduleMediaDecisionService()
