"""Импорт метрик постов и обратная связь обучения (v0.4.1).

Собирает метрики публикаций из источника (demo / manual / estimated / internal / api),
нормализует их, создаёт ``PostAnalyticsSnapshot`` + событие ``analytics_imported`` и
пересчитывает ``ClientLearningProfile``. Реальные внешние API по умолчанию выключены.

БЕЗОПАСНОСТЬ:
- preview/dry-run/manual — без списаний; реальный api-импорт платный (по глубине);
- заблокированный/неуспешный импорт units НЕ списывает; повтор идемпотентен;
- секретов в ответах/логах/``import_metadata`` нет.
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    analytics_repository,
    metric_import_run_repository,
    post_publication_repository,
    post_repository,
    project_repository,
)
from app.schemas.analytics import PostAnalyticsSnapshotInsert
from app.services import audit_log_service as audit_actions
from app.services.billing_service import (
    USAGE_LEARNING_REBUILD,
    USAGE_METRICS_IMPORT,
    BillingService,
    InsufficientBalanceError,
)
from app.services.content_scoring_service import ContentScoringService
from app.services.metrics_normalization_service import (
    METRIC_SOURCES,
    MetricsNormalizationService,
)
from app.services.platform_metrics import build_metrics_adapter
from app.services.platform_metrics.base import STATUS_IMPORTED, PublicationContext
from app.services.unit_economics_service import UnitEconomicsService

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService

logger = get_logger(__name__)

# Публикации, попадающие в скан импорта (дошли/запланированы на площадку).
_SCANNABLE_STATUSES = ("published", "scheduled", "publishing")


class MetricsImportError(Exception):
    """Ошибка импорта метрик (нет проекта/публикации и т. п.) — API → 400."""


class MetricsImportService:
    """Импорт метрик, ручной ввод и пересчёт обучения по метрикам."""

    def __init__(
        self,
        normalization_service: MetricsNormalizationService | None = None,
        learning_service: ClientLearningService | None = None,
        billing_service: BillingService | None = None,
        economics: UnitEconomicsService | None = None,
        audit_service: AuditLogService | None = None,
        scoring_service: ContentScoringService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._normalize = normalization_service or MetricsNormalizationService()
        self._learning = learning_service
        self._billing = billing_service or BillingService()
        self._economics = economics or UnitEconomicsService(settings)
        self._audit = audit_service
        self._scoring = scoring_service or ContentScoringService()
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Preview / dry-run (без записи и без биллинга)                    #
    # ------------------------------------------------------------------ #

    def preview_import(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        source: str = "demo",
        period_start: str | None = None,
        period_end: str | None = None,
        depth: str = "standard",
    ) -> dict[str, Any]:
        """Что было бы импортировано (без записи и без списания units)."""
        source = self._normalize_source(source)
        contexts_by_platform = self._collect_contexts(db, project_id, platform_key)
        total_pubs = sum(len(ctxs) for ctxs in contexts_by_platform.values())
        per_platform: list[dict[str, Any]] = []
        warnings: list[str] = []
        for platform, ctxs in contexts_by_platform.items():
            adapter = self._adapter_for(source, platform)
            preview = adapter.preview_fetch(ctxs)
            per_platform.append(
                {
                    "platform": platform,
                    "supports_api_metrics": preview.supports_api_metrics,
                    "api_enabled": preview.api_enabled,
                    "publications_available": preview.publications_available,
                    "status": preview.status,
                    "warnings": list(preview.warnings),
                }
            )
            warnings.extend(preview.warnings)
        units = self._economics.estimate_metrics_import_units(source, depth, total_pubs)
        self._audit_metrics(
            db,
            project_id,
            None,
            audit_actions.ACTION_METRICS_IMPORT_PREVIEW,
            {"source": source, "platform_key": platform_key, "publication_count": total_pubs},
        )
        base_warnings = [
            "Demo/estimated метрики не являются реальными показателями площадки.",
            "Реальные API-метрики выключены по умолчанию (feature flag).",
        ]
        return {
            "project_id": project_id,
            "source": source,
            "depth": depth,
            "platform_key": platform_key,
            "publications_found": total_pubs,
            "estimated_units": units,
            "per_platform": per_platform,
            "warnings": base_warnings + [w for w in warnings if w not in base_warnings],
            "writes": False,
        }

    def run_import_dry(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        source: str = "demo",
        period_start: str | None = None,
        period_end: str | None = None,
        depth: str = "standard",
    ) -> dict[str, Any]:
        """Сухой прогон: как preview, но в форме результата прогона (без записи/биллинга)."""
        preview = self.preview_import(
            db, project_id, platform_key, source, period_start, period_end, depth
        )
        return {**preview, "dry_run": True, "status": "preview"}

    # ------------------------------------------------------------------ #
    # 2. Реальный импорт метрик (с записью и биллингом)                   #
    # ------------------------------------------------------------------ #

    def run_import(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        source: str = "demo",
        depth: str = "standard",
        period_start: str | None = None,
        period_end: str | None = None,
        idempotency_key: str | None = None,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Импортировать метрики: снимки + сигналы обучения + пересчёт профиля.

        Списывает units только на успешном импорте (api-источник). Идемпотентно.
        """
        source = self._normalize_source(source)
        account_id = self._account_id(db, project_id)

        # Идемпотентность: успешный прогон не повторяем; неуспешный (pending/failed/
        # skipped/…) — ПЕРЕИСПОЛЬЗУЕМ ту же строку (иначе повтор с тем же ключом упал бы
        # на unique-constraint). Так неуспешный импорт можно безопасно перезапустить.
        existing = None
        if idempotency_key is not None:
            existing = metric_import_run_repository.get_by_idempotency_key(db, idempotency_key)
            if existing is not None and existing.status in ("imported", "partially_imported"):
                return {**self._mask_run(existing), "outcome": "skipped_duplicate"}

        if existing is not None:
            run = metric_import_run_repository.update_run(
                db,
                existing,
                status="pending",
                source=source,
                platform_key=platform_key,
                period_start=period_start,
                period_end=period_end,
                error_message=None,
                finished_at=None,
                import_metadata={"depth": depth},
            )
        else:
            run = metric_import_run_repository.create_run(
                db,
                account_id=account_id,
                project_id=project_id,
                platform_key=platform_key,
                source=source,
                status="pending",
                period_start=period_start,
                period_end=period_end,
                idempotency_key=idempotency_key,
                created_by_user_id=current_user_id,
                import_metadata={"depth": depth},
            )
        self._audit_metrics(
            db,
            project_id,
            current_user_id,
            audit_actions.ACTION_METRICS_IMPORT_STARTED,
            {"run_id": run.id, "source": source, "platform_key": platform_key},
        )

        try:
            return self._execute_import(
                db, run, project_id, account_id, platform_key, source, depth
            )
        except InsufficientBalanceError as exc:
            metric_import_run_repository.mark_skipped(
                db,
                run,
                status="skipped",
                message="insufficient_balance",
                finished_at=datetime.now(UTC),
            )
            self._audit_metrics(
                db,
                project_id,
                current_user_id,
                audit_actions.ACTION_METRICS_IMPORT_BLOCKED,
                {"run_id": run.id, "reason": "insufficient_balance"},
            )
            raise MetricsImportError(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001 — ошибка импорта не должна ронять API
            metric_import_run_repository.mark_failed(
                db, run, f"import failed: {type(exc).__name__}", finished_at=datetime.now(UTC)
            )
            self._audit_metrics(
                db,
                project_id,
                current_user_id,
                audit_actions.ACTION_METRICS_IMPORT_FAILED,
                {"run_id": run.id},
            )
            return {**self._mask_run(run), "outcome": "failed"}

    def _execute_import(
        self,
        db: Session,
        run: Any,
        project_id: int,
        account_id: int | None,
        platform_key: str | None,
        source: str,
        depth: str,
    ) -> dict[str, Any]:
        """Собрать метрики по площадкам, создать снимки/события и списать units."""
        contexts_by_platform = self._collect_contexts(db, project_id, platform_key)
        total_pubs = sum(len(c) for c in contexts_by_platform.values())
        if total_pubs == 0:
            metric_import_run_repository.mark_skipped(
                db,
                run,
                status="skipped",
                message="no_publications",
                finished_at=datetime.now(UTC),
            )
            return {**self._mask_run(run), "outcome": "no_publications"}

        snapshots_created = 0
        learning_events = 0
        imported = 0
        statuses: set[str] = set()
        for platform, ctxs in contexts_by_platform.items():
            adapter = self._adapter_for(source, platform)
            creds = {"token_present": False}  # реальные креды в метрики не передаём
            results = adapter.fetch_metrics(ctxs, credentials=creds)
            for result in results:
                statuses.add(result.status)
                if result.status != STATUS_IMPORTED:
                    continue
                normalized = self._normalize.normalize_platform_metrics(
                    result.platform, result.raw_metrics, source
                )
                self._create_snapshot(db, project_id, result, normalized)
                snapshots_created += 1
                imported += 1
                self._learning_svc().record_publication_performance(
                    db,
                    publication_id=result.publication_id,
                    metrics=normalized.to_dict(),
                    source=source,
                    platform_key=result.platform,
                    rebuild=False,
                )
                learning_events += 1
                # Если публикация относится к варианту эксперимента — привяжем метрики.
                self._attach_variant_metrics(db, result.post_id, normalized)

        # Пересчёт профиля один раз в конце (после всех событий).
        if learning_events:
            self._learning_svc().build_learning_profile(db, project_id, platform_key=None)

        status = self._resolve_status(imported, total_pubs, statuses)
        units_charged = 0
        if status in ("imported", "partially_imported") and imported > 0:
            units = self._economics.estimate_metrics_import_units(source, depth, total_pubs)
            if units > 0 and account_id is not None:
                self._billing.ensure_balance(db, account_id, units)
                ledger = self._billing.debit_for_action(
                    db,
                    account_id,
                    units=units,
                    usage_type=USAGE_METRICS_IMPORT,
                    idempotency_key=f"metrics-import-{run.id}",
                    project_id=project_id,
                    metadata={"source": source, "depth": depth},
                )
                units_charged = units if ledger is not None else 0

        metric_import_run_repository.mark_imported(
            db,
            run,
            status=status,
            publications_scanned=total_pubs,
            metrics_imported=imported,
            snapshots_created=snapshots_created,
            learning_events_created=learning_events,
            units_charged=units_charged,
            finished_at=datetime.now(UTC),
            import_metadata={"depth": depth, "statuses": sorted(statuses)},
        )
        if "api_disabled" in statuses and imported == 0:
            self._audit_metrics(
                db,
                project_id,
                run.created_by_user_id,
                audit_actions.ACTION_METRICS_EXTERNAL_API_DISABLED,
                {"run_id": run.id, "source": source},
            )
        self._audit_metrics(
            db,
            project_id,
            run.created_by_user_id,
            audit_actions.ACTION_METRICS_IMPORT_COMPLETED,
            {
                "run_id": run.id,
                "status": status,
                "snapshots_created": snapshots_created,
                "units": units_charged,
            },
        )
        return {**self._mask_run(run), "outcome": status}

    # ------------------------------------------------------------------ #
    # 3. Ручной ввод метрик (бесплатно)                                   #
    # ------------------------------------------------------------------ #

    def save_manual_metrics(
        self,
        db: Session,
        publication_id: int,
        metrics: dict[str, Any],
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Сохранить ручные метрики: снимок source=manual + сигнал обучения (бесплатно)."""
        pub = post_publication_repository.get_publication_by_id(db, publication_id)
        if pub is None:
            raise MetricsImportError(f"Публикация id={publication_id} не найдена")
        normalized = self._normalize.normalize_platform_metrics(pub.platform, metrics, "manual")
        result_like = _SimpleResult(
            publication_id=pub.id, post_id=pub.post_id, platform=pub.platform
        )
        snapshot = self._create_snapshot(db, pub.project_id, result_like, normalized)
        self._learning_svc().record_publication_performance(
            db,
            publication_id=pub.id,
            metrics=normalized.to_dict(),
            source="manual",
            platform_key=pub.platform,
            rebuild=True,
        )
        self._audit_metrics(
            db,
            pub.project_id,
            current_user_id,
            audit_actions.ACTION_METRICS_MANUAL_SAVED,
            {"publication_id": pub.id, "snapshot_id": snapshot.id},
        )
        return {
            "publication_id": pub.id,
            "snapshot_id": snapshot.id,
            "source": "manual",
            "er_percent": normalized.er_percent,
            "ctr_percent": normalized.ctr_percent,
            "units_charged": 0,
        }

    # ------------------------------------------------------------------ #
    # 4. Пересчёт обучения по метрикам                                    #
    # ------------------------------------------------------------------ #

    def rebuild_learning_from_metrics(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        depth: str = "standard",
        idempotency_key: str | None = None,
        dry_run: bool = True,
        current_user_id: int | None = None,
    ) -> dict[str, Any]:
        """Пересчитать профиль обучения по накопленным метрикам. dry-run — бесплатно."""
        before = self._learning_svc().summarize_learning(db, project_id, platform_key)
        if dry_run:
            self._audit_metrics(
                db,
                project_id,
                current_user_id,
                audit_actions.ACTION_METRICS_LEARNING_REBUILD_PREVIEW,
                {"project_id": project_id},
            )
            profile = self._learning_svc().build_learning_profile(db, project_id, platform_key)
            after = self._learning_svc().summarize_learning(db, project_id, platform_key)
            return {
                "project_id": project_id,
                "dry_run": True,
                "profile_version": profile.profile_version,
                "confidence_score": round(profile.confidence_score, 3),
                "changes": self._learning_svc().explain_learning_changes(before, after),
                "units_charged": 0,
            }

        account_id = self._account_id(db, project_id)
        units = self._economics.estimate_learning_rebuild_units(depth)
        if units > 0 and account_id is not None:
            self._billing.ensure_balance(db, account_id, units)
        profile = self._learning_svc().rebuild_learning_profile(db, project_id, platform_key)
        units_charged = 0
        if units > 0 and account_id is not None:
            ledger = self._billing.debit_for_action(
                db,
                account_id,
                units=units,
                usage_type=USAGE_LEARNING_REBUILD,
                idempotency_key=idempotency_key
                or f"learning-rebuild-{project_id}-v{profile.profile_version}",
                project_id=project_id,
            )
            units_charged = units if ledger is not None else 0
        after = self._learning_svc().summarize_learning(db, project_id, platform_key)
        self._audit_metrics(
            db,
            project_id,
            current_user_id,
            audit_actions.ACTION_METRICS_LEARNING_REBUILT,
            {"project_id": project_id, "version": profile.profile_version, "units": units_charged},
        )
        return {
            "project_id": project_id,
            "dry_run": False,
            "profile_version": profile.profile_version,
            "confidence_score": round(profile.confidence_score, 3),
            "changes": self._learning_svc().explain_learning_changes(before, after),
            "units_charged": units_charged,
        }

    # ------------------------------------------------------------------ #
    # 5. Дашборд метрик (для UI)                                          #
    # ------------------------------------------------------------------ #

    def build_metrics_dashboard(
        self, db: Session, project_id: int, filters: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Сводка метрик и обучения проекта для UI."""
        filters = filters or {}
        platform = filters.get("platform")
        source = filters.get("source")
        snapshots = analytics_repository.list_snapshots_for_project(db, project_id)
        if platform:
            snapshots = [s for s in snapshots if s.platform == platform]
        if source:
            snapshots = [s for s in snapshots if s.source == source]

        # Последний снимок на пост (агрегируем «текущее» состояние).
        latest_by_post: dict[int, Any] = {}
        for snap in snapshots:
            latest_by_post[snap.post_id] = snap  # snapshots упорядочены по id возр.
        rows = list(latest_by_post.values())

        er_values = [s.engagement_rate for s in rows if s.engagement_rate]
        ctr_values = [s.ctr for s in rows if s.ctr]
        avg_er = round(sum(er_values) / len(er_values) * 100, 2) if er_values else None
        avg_ctr = round(sum(ctr_values) / len(ctr_values) * 100, 2) if ctr_values else None
        best = max(rows, key=lambda s: s.engagement_rate, default=None)
        worst = min(rows, key=lambda s: s.engagement_rate, default=None)

        source_breakdown: dict[str, int] = {}
        for snap in rows:
            source_breakdown[snap.source] = source_breakdown.get(snap.source, 0) + 1

        summary = self._learning_svc().summarize_learning(db, project_id, None)
        publications = self._published_publication_count(db, project_id, platform)
        return {
            "project_id": project_id,
            "posts_count": publications,
            "with_metrics_count": len(rows),
            "avg_er_percent": avg_er,
            "avg_ctr_percent": avg_ctr,
            "best_post": self._snapshot_row(best),
            "worst_post": self._snapshot_row(worst),
            "best_tags": summary.get("high_performing_tags", []),
            "weak_tags": summary.get("low_performing_tags", []),
            "best_cta": summary.get("preferred_cta", []),
            "best_media_types": summary.get("preferred_media_types", []),
            "best_times": summary.get("best_publish_times", []),
            "source_breakdown": source_breakdown,
            "confidence_score": summary.get("confidence_score", 0.0),
            "learning_recommendations": summary.get("recommendations", []),
            "posts": [self._snapshot_row(s) for s in rows],
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _collect_contexts(
        self, db: Session, project_id: int, platform_key: str | None
    ) -> dict[str, list[PublicationContext]]:
        """Собрать контексты публикаций по площадкам (published/scheduled)."""
        pubs = post_publication_repository.list_publications(
            db, project_id=project_id, platform=platform_key, limit=1000
        )
        by_platform: dict[str, list[PublicationContext]] = {}
        for pub in pubs:
            if pub.status not in _SCANNABLE_STATUSES:
                continue
            post = post_repository.get_post_by_id(db, pub.post_id)
            if post is None:
                continue
            ctx = self._build_context(pub, post)
            by_platform.setdefault(pub.platform, []).append(ctx)
        return by_platform

    def _build_context(self, pub: Any, post: Any) -> PublicationContext:
        text = post.vk_text or post.telegram_text or post.instagram_text or ""
        features = self._scoring.analyze_text_features(text)
        media_count = 1 if post.media_asset_id else 0
        notes = post.generation_notes or {}
        if isinstance(notes, dict) and notes.get("media_asset_ids"):
            media_count = len(notes["media_asset_ids"])
        published_at = pub.published_at or pub.scheduled_at
        return PublicationContext(
            publication_id=pub.id,
            post_id=pub.post_id,
            platform=pub.platform,
            published_at=published_at.isoformat() if published_at else None,
            text_length=int(features["length"]),
            hashtags_count=int(features["hashtags_count"]),
            has_cta=bool(features["has_cta"]),
            has_link=bool(features["has_link"]),
            media_count=media_count,
        )

    def _adapter_for(self, source: str, platform: str) -> Any:
        """Адаптер: demo-источник → demo-адаптер; api → адаптер площадки (gated)."""
        if source == "api":
            return build_metrics_adapter(platform, self._settings)
        return build_metrics_adapter("demo", self._settings)

    @staticmethod
    def _attach_variant_metrics(db: Session, post_id: int, normalized: Any) -> None:
        """Если пост — вариант A/B-эксперимента, привязать к нему метрики (best-effort)."""
        try:
            from app.repositories import content_experiment_repository

            variant = content_experiment_repository.get_variant_for_post(db, post_id)
            if variant is None:
                return
            content_experiment_repository.update_variant(
                db,
                variant,
                metrics_snapshot=dict(normalized.raw_sanitized or {}),
                er_percent=normalized.er_percent,
                ctr_percent=normalized.ctr_percent,
                status="measured",
            )
        except Exception:  # noqa: BLE001 — привязка метрик к варианту не должна ронять импорт
            with contextlib.suppress(Exception):
                db.rollback()

    def _create_snapshot(self, db: Session, project_id: int, result: Any, normalized: Any) -> Any:
        """Создать PostAnalyticsSnapshot из нормализованных метрик (ER/CTR — дробью)."""
        ints = normalized.snapshot_metrics()
        er_fraction = (normalized.er_percent or 0.0) / 100
        ctr_fraction = (normalized.ctr_percent or 0.0) / 100
        post = post_repository.get_post_by_id(db, result.post_id)
        insert = PostAnalyticsSnapshotInsert(
            post_id=result.post_id,
            post_publication_id=result.publication_id,
            project_id=project_id,
            topic_id=post.topic_id if post is not None else None,
            platform=result.platform,
            snapshot_at=datetime.now(UTC),
            impressions=ints["impressions"],
            reach=ints["reach"],
            views=ints["views"],
            likes=ints["likes"],
            reactions=0,
            comments=ints["comments"],
            shares=ints["shares"],
            saves=ints["saves"],
            clicks=ints["clicks"],
            ctr=round(ctr_fraction, 6),
            engagement_rate=round(er_fraction, 6),
            raw_metrics=normalized.raw_sanitized,
            source=normalized.source,
        )
        return analytics_repository.create_snapshot(db, insert)

    @staticmethod
    def _resolve_status(imported: int, total: int, statuses: set[str]) -> str:
        if imported == 0:
            if statuses == {"api_disabled"}:
                return "skipped"
            if statuses == {"no_credentials"}:
                return "no_credentials"
            if "live_disabled" in statuses:
                return "live_disabled"
            return "skipped"
        if imported < total:
            return "partially_imported"
        return "imported"

    @staticmethod
    def _snapshot_row(snap: Any) -> dict[str, Any] | None:
        if snap is None:
            return None
        return {
            "post_id": snap.post_id,
            "publication_id": snap.post_publication_id,
            "platform": snap.platform,
            "source": snap.source,
            "er_percent": round(snap.engagement_rate * 100, 2),
            "ctr_percent": round(snap.ctr * 100, 2),
            "reach": snap.reach,
            "impressions": snap.impressions,
            "likes": snap.likes,
            "comments": snap.comments,
            "shares": snap.shares,
            "saves": snap.saves,
            "clicks": snap.clicks,
            "snapshot_at": snap.snapshot_at.isoformat() if snap.snapshot_at else None,
        }

    @staticmethod
    def _published_publication_count(db: Session, project_id: int, platform: str | None) -> int:
        pubs = post_publication_repository.list_publications(
            db, project_id=project_id, platform=platform, limit=1000
        )
        return sum(1 for p in pubs if p.status in _SCANNABLE_STATUSES)

    @staticmethod
    def _mask_run(run: Any) -> dict[str, Any]:
        return {
            "id": run.id,
            "project_id": run.project_id,
            "platform_key": run.platform_key,
            "source": run.source,
            "status": run.status,
            "period_start": run.period_start,
            "period_end": run.period_end,
            "publications_scanned": run.publications_scanned,
            "metrics_imported": run.metrics_imported,
            "snapshots_created": run.snapshots_created,
            "learning_events_created": run.learning_events_created,
            "units_estimated": run.units_estimated,
            "units_charged": run.units_charged,
            "error_message": run.error_message,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        }

    @staticmethod
    def _normalize_source(source: str) -> str:
        src = (source or "demo").strip().lower()
        return src if src in METRIC_SOURCES else "demo"

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise MetricsImportError(f"Проект id={project_id} не найден")
        return project.account_id

    def _learning_svc(self) -> ClientLearningService:
        if self._learning is None:
            from app.services.client_learning_service import ClientLearningService

            self._learning = ClientLearningService()
        return self._learning

    def _audit_metrics(
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
        account_id = None
        project = project_repository.get_project_by_id(db, project_id)
        if project is not None:
            account_id = project.account_id
        self._audit.record(
            db,
            action,
            account_id=account_id,
            user_id=user_id,
            project_id=project_id,
            entity_type="metric_import_run",
            metadata=metadata,
        )


class _SimpleResult:
    """Лёгкий носитель результата для ручного ввода (без адаптера)."""

    def __init__(self, publication_id: int, post_id: int, platform: str) -> None:
        self.publication_id = publication_id
        self.post_id = post_id
        self.platform = platform


def get_metrics_import_service() -> MetricsImportService:
    """DI-фабрика сервиса импорта метрик."""
    return MetricsImportService()
