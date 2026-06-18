"""Автономный pipeline (Этап 10).

Связывает уже готовые модули в управляемый прогон: выбор тем → контент-план →
генерация постов → подбор медиа → внешние картинки → согласование → планирование
→ публикация → аналитика → отчёт. Каждый шаг логируется в ``AutonomousRunStep``;
одна проблема не роняет весь прогон. Реальные публикации и AI выполняются только
при явном разрешении в настройках; сеть в тестах не вызывается.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.autonomous_run import AutonomousRun
from app.models.project import Project
from app.repositories import (
    autonomous_run_repository as repo,
)
from app.repositories import (
    media_asset_repository,
    post_repository,
    project_repository,
)
from app.schemas.autonomous import (
    AutonomousModeSettings,
    AutonomousRunCreate,
    AutonomousRunRead,
    AutonomousRunReport,
    AutonomousRunRequest,
    AutonomousRunResult,
    AutonomousRunStepCreate,
    AutonomousRunStepRead,
    AutonomousRunStepUpdate,
    AutonomousRunSummary,
    AutonomousRunUpdate,
)
from app.schemas.post import WeeklyPostGenerationRequest
from app.schemas.post_publication import PostPublishRequest, PostScheduleRequest
from app.schemas.post_review import PostReviewDecisionRequest
from app.schemas.topic import TopicSelectionRequest
from app.services.analytics_service import AnalyticsService
from app.services.autonomous_safety_service import AutonomousSafetyService
from app.services.external_image_search_service import ExternalImageSearchService
from app.services.post_generation_service import PostGenerationService
from app.services.post_publication_service import (
    PostNotPublishableError,
    PostPublicationService,
)
from app.services.post_review_service import PostReviewService, ReviewActionNotAllowedError
from app.services.topic_selection_service import TopicSelectionService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

_BOT_DECISION = PostReviewDecisionRequest(
    actor_name="autonomous-bot", actor_role="bot", comment="Автономный прогон"
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AutonomousValidationError(Exception):
    """Запрос автономного прогона не прошёл проверку (API → 422)."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


class AutonomousRunNotFoundError(Exception):
    """Автономный прогон не найден (API → 404)."""

    def __init__(self, run_id: int) -> None:
        self.run_id = run_id
        super().__init__(f"Автономный прогон id={run_id} не найден")


class AutonomousPipelineService:
    """Оркестрирует автономный прогон по проекту с safety-guardrails."""

    def __init__(
        self,
        topic_selection_service: TopicSelectionService,
        post_generation_service: PostGenerationService,
        post_review_service: PostReviewService,
        post_publication_service: PostPublicationService,
        external_image_search_service: ExternalImageSearchService,
        analytics_service: AnalyticsService,
        safety_service: AutonomousSafetyService,
    ) -> None:
        self._topic = topic_selection_service
        self._generation = post_generation_service
        self._review = post_review_service
        self._publication = post_publication_service
        self._external = external_image_search_service
        self._analytics = analytics_service
        self._safety = safety_service

    # --- Публичные методы ---

    def run_pipeline(self, db: Session, request: AutonomousRunRequest) -> AutonomousRunResult:
        """Выполнить автономный прогон по запросу."""
        project = self._resolve_project(db, request.project_id, request.project_slug)
        report = self._safety.validate_request(request)
        if not report.allowed:
            raise AutonomousValidationError(report.errors)
        settings = report.effective_settings

        run = repo.create_run(
            db,
            AutonomousRunCreate(
                project_id=project.id,
                mode=request.mode,
                status="running",
                weeks=request.weeks,
                posts_per_week=request.posts_per_week,
                business_priorities=request.business_priorities or {},
                settings=settings.model_dump(),
                started_at=_utcnow(),
            ),
        )

        summary = AutonomousRunSummary()
        warnings = list(report.warnings)
        errors: list[str] = []

        try:
            if settings.dry_run:
                self._run_dry(db, run.id, request, summary, warnings)
            else:
                self._run_live(db, run.id, project, request, settings, summary, warnings, errors)
            terminal = "completed_with_warnings" if (warnings or errors) else "completed"
        except Exception as exc:
            errors.append(f"pipeline: {exc}")
            terminal = "failed"

        steps = repo.list_steps(db, run.id)
        summary.failed_steps_count = sum(1 for step in steps if step.status == "failed")
        if summary.failed_steps_count and terminal == "completed":
            terminal = "completed_with_warnings"

        run = repo.update_run(
            db,
            run,
            AutonomousRunUpdate(
                status=terminal,
                finished_at=_utcnow(),
                summary=summary.model_dump(),
                warnings=warnings,
                errors=errors,
            ),
        )
        logger.info(
            "Автономный прогон id=%s завершён: режим=%s статус=%s", run.id, run.mode, terminal
        )
        return self._build_result(db, run, summary, warnings, errors)

    def run_for_project_slug(
        self, db: Session, slug: str, request: AutonomousRunRequest
    ) -> AutonomousRunResult:
        """Запустить прогон по slug проекта."""
        return self.run_pipeline(
            db, request.model_copy(update={"project_slug": slug, "project_id": None})
        )

    def dry_run_pipeline(self, db: Session, request: AutonomousRunRequest) -> AutonomousRunResult:
        """Выполнить прогон в режиме dry_run (без создания тем/постов/публикаций)."""
        return self.run_pipeline(db, request.model_copy(update={"mode": "dry_run"}))

    def build_report(self, db: Session, run_id: int) -> AutonomousRunReport:
        """Построить отчёт по прогону с рекомендациями (next_actions)."""
        run = repo.get_run_by_id(db, run_id)
        if run is None:
            raise AutonomousRunNotFoundError(run_id)
        project = project_repository.get_project_by_id(db, run.project_id)
        steps = repo.list_steps(db, run.id)
        summary = AutonomousRunSummary(**run.summary) if run.summary else AutonomousRunSummary()
        return AutonomousRunReport(
            run_id=run.id,
            project_id=run.project_id,
            project_slug=project.slug if project is not None else "",
            mode=run.mode,
            status=run.status,
            summary=summary,
            warnings=list(run.warnings or []),
            errors=list(run.errors or []),
            steps=[AutonomousRunStepRead.model_validate(step) for step in steps],
            next_actions=self._next_actions(summary, run.mode),
        )

    # --- Pipeline (live) ---

    def _run_live(
        self,
        db: Session,
        run_id: int,
        project: Project,
        request: AutonomousRunRequest,
        settings: AutonomousModeSettings,
        summary: AutonomousRunSummary,
        warnings: list[str],
        errors: list[str],
    ) -> None:
        selection_request = TopicSelectionRequest(
            business_priorities=request.business_priorities,
            weeks=request.weeks,
            posts_per_week=request.posts_per_week,
        )

        # 1. select_topics (без тем продолжать нельзя).
        try:
            selection = self._topic.select_topics_for_project(db, project.id, selection_request)
            summary.selected_topics_count = selection.selected_count
            self._record_step(
                db,
                run_id,
                "select_topics",
                "completed",
                {"weeks": request.weeks, "posts_per_week": request.posts_per_week},
                {"selected_count": selection.selected_count, "created": selection.created},
                list(selection.warnings),
            )
            warnings.extend(selection.warnings)
        except Exception as exc:
            self._record_step(db, run_id, "select_topics", "failed", {}, {}, [], [str(exc)])
            errors.append(f"select_topics: {exc}")
            return

        # 2. build_content_plan.
        try:
            plan = self._topic.build_weekly_content_plan(db, project.id, selection_request)
            self._record_step(
                db,
                run_id,
                "build_content_plan",
                "completed",
                {},
                {"items": len(plan.items)},
                list(plan.warnings),
            )
            warnings.extend(plan.warnings)
        except Exception as exc:
            self._record_step(db, run_id, "build_content_plan", "failed", {}, {}, [], [str(exc)])
            warnings.append(f"build_content_plan: {exc}")

        # 3. generate_posts (без постов продолжать нечего).
        try:
            generation = self._generation.generate_weekly_posts(
                db,
                WeeklyPostGenerationRequest(
                    project_id=project.id,
                    weeks=request.weeks,
                    posts_per_week=request.posts_per_week,
                    business_priorities=request.business_priorities,
                ),
            )
            summary.generated_posts_count = generation.generated_count
            post_ids = [post.id for post in generation.posts]
            needs_media_ids = [p.id for p in generation.posts if p.status == "needs_media"]
            summary.posts_needing_media_count = len(needs_media_ids)
            self._record_step(
                db,
                run_id,
                "generate_posts",
                "completed",
                {},
                {"generated": generation.generated_count, "needs_media": len(needs_media_ids)},
                list(generation.warnings),
            )
            warnings.extend(generation.warnings)
        except Exception as exc:
            self._record_step(db, run_id, "generate_posts", "failed", {}, {}, [], [str(exc)])
            errors.append(f"generate_posts: {exc}")
            return

        # 4. select_media (информационный шаг).
        self._record_step(
            db,
            run_id,
            "select_media",
            "completed",
            {},
            {
                "with_media": len(post_ids) - len(needs_media_ids),
                "needs_media": len(needs_media_ids),
            },
            [],
        )

        # 5. search_external_images (фолбэк при нехватке медиа).
        self._step_external_images(db, run_id, settings, summary, warnings, needs_media_ids)

        # 6. submit_for_review / auto_approve.
        self._step_review(db, run_id, settings, summary, warnings, post_ids)

        # 7. schedule_posts.
        self._step_schedule(db, run_id, settings, summary, warnings, post_ids)

        # 8. publish_posts.
        self._step_publish(db, run_id, settings, summary, warnings, post_ids)

        # 9. collect_analytics (реальная аналитика не запрашивается).
        self._record_step(
            db,
            run_id,
            "collect_analytics",
            "skipped",
            {},
            {"note": "Аналитика собирается после реальных публикаций (Этап 8)"},
            [],
        )

        # 10. build_report.
        self._record_step(db, run_id, "build_report", "completed", {}, summary.model_dump(), [])

    def _step_external_images(
        self,
        db: Session,
        run_id: int,
        settings: AutonomousModeSettings,
        summary: AutonomousRunSummary,
        warnings: list[str],
        needs_media_ids: list[int],
    ) -> None:
        if not needs_media_ids:
            self._record_step(
                db,
                run_id,
                "search_external_images",
                "skipped",
                {},
                {"note": "Нет постов без медиа"},
                [],
            )
            return
        if not settings.allow_external_images:
            warning = (
                "Есть посты без медиа (needs_media) — нужна досъёмка (внешние картинки отключены)"
            )
            warnings.append(warning)
            self._record_step(
                db,
                run_id,
                "search_external_images",
                "skipped",
                {},
                {"note": "Поиск внешних картинок отключён настройками"},
                [warning],
            )
            return

        candidates = 0
        step_warnings: list[str] = []
        for post_id in needs_media_ids:
            try:
                result = self._external.search_for_post(db, post_id, limit=5)
                candidates += result.created
            except Exception as exc:
                step_warnings.append(f"post {post_id}: {exc}")
        summary.external_candidates_count = candidates
        step_warnings.append(
            "Есть посты без медиа — проверьте внешние картинки (не выдавать за свой кейс) "
            "или добавьте своё фото/видео"
        )
        self._record_step(
            db,
            run_id,
            "search_external_images",
            "completed",
            {"posts": len(needs_media_ids)},
            {"candidates": candidates},
            step_warnings,
        )
        warnings.extend(step_warnings)

    def _step_review(
        self,
        db: Session,
        run_id: int,
        settings: AutonomousModeSettings,
        summary: AutonomousRunSummary,
        warnings: list[str],
        post_ids: list[int],
    ) -> None:
        submitted = 0
        approved = 0
        step_warnings: list[str] = []
        for post_id in post_ids:
            post = post_repository.get_post_by_id(db, post_id)
            if post is None or post.status != "draft":
                continue
            media = (
                media_asset_repository.get_media_asset_by_id(db, post.media_asset_id)
                if post.media_asset_id is not None
                else None
            )
            if settings.allow_auto_approve:
                can_approve, reasons = self._safety.can_auto_approve(post, media)
                if can_approve:
                    self._review.approve_post(db, post_id, _BOT_DECISION)
                    approved += 1
                    continue
                step_warnings.extend(reasons)
            try:
                self._review.submit_for_review(db, post_id, _BOT_DECISION)
                submitted += 1
            except ReviewActionNotAllowedError as exc:
                step_warnings.append(str(exc))
        summary.submitted_for_review_count = submitted
        self._record_step(
            db,
            run_id,
            "submit_for_review",
            "completed",
            {},
            {"submitted": submitted, "approved": approved},
            step_warnings,
        )
        warnings.extend(step_warnings)

    def _step_schedule(
        self,
        db: Session,
        run_id: int,
        settings: AutonomousModeSettings,
        summary: AutonomousRunSummary,
        warnings: list[str],
        post_ids: list[int],
    ) -> None:
        if not settings.allow_auto_schedule:
            self._record_step(
                db,
                run_id,
                "schedule_posts",
                "skipped",
                {},
                {"note": "auto_schedule выключен"},
                [],
            )
            return
        scheduled = 0
        step_warnings: list[str] = []
        for post_id in post_ids:
            post = post_repository.get_post_by_id(db, post_id)
            if post is None:
                continue
            can_schedule, _reasons = self._safety.can_auto_schedule(post)
            if not can_schedule:
                continue
            try:
                result = self._publication.schedule_post(
                    db, post_id, PostScheduleRequest(platforms=settings.platforms)
                )
                scheduled += len(result.publications)
            except PostNotPublishableError as exc:
                step_warnings.append(str(exc))
        summary.scheduled_publications_count = scheduled
        self._record_step(
            db, run_id, "schedule_posts", "completed", {}, {"scheduled": scheduled}, step_warnings
        )
        warnings.extend(step_warnings)

    def _step_publish(
        self,
        db: Session,
        run_id: int,
        settings: AutonomousModeSettings,
        summary: AutonomousRunSummary,
        warnings: list[str],
        post_ids: list[int],
    ) -> None:
        if not settings.allow_auto_publish:
            self._record_step(
                db,
                run_id,
                "publish_posts",
                "skipped",
                {},
                {"note": "auto_publish выключен"},
                [],
            )
            return
        published = 0
        step_warnings: list[str] = []
        for post_id in post_ids:
            post = post_repository.get_post_by_id(db, post_id)
            if post is None:
                continue
            can_publish, _reasons = self._safety.can_auto_publish(post)
            if not can_publish:
                continue
            try:
                result = self._publication.publish_post(
                    db, post_id, PostPublishRequest(platforms=settings.platforms)
                )
                published += result.published_count
                step_warnings.extend(result.warnings)
            except PostNotPublishableError as exc:
                step_warnings.append(str(exc))
        summary.published_publications_count = published
        self._record_step(
            db, run_id, "publish_posts", "completed", {}, {"published": published}, step_warnings
        )
        warnings.extend(step_warnings)

    # --- Pipeline (dry_run) ---

    def _run_dry(
        self,
        db: Session,
        run_id: int,
        request: AutonomousRunRequest,
        summary: AutonomousRunSummary,
        warnings: list[str],
    ) -> None:
        planned = max(request.weeks, 1) * max(request.posts_per_week, 1)
        steps: list[tuple[str, dict[str, object]]] = [
            ("select_topics", {"would_select": planned}),
            ("build_content_plan", {"would_plan_items": planned}),
            ("generate_posts", {"would_generate": planned}),
            ("select_media", {"note": "подбор approved-медиа (симуляция)"}),
            ("search_external_images", {"note": "поиск внешних картинок при нехватке медиа"}),
            ("submit_for_review", {"note": "посты ушли бы на согласование (needs_review)"}),
            ("schedule_posts", {"note": "планирование отключено в dry_run"}),
            ("publish_posts", {"note": "публикация отключена в dry_run"}),
            ("collect_analytics", {"note": "аналитика не запрашивается"}),
            ("build_report", {"would_generate": planned}),
        ]
        for step_name, output in steps:
            self._record_step(db, run_id, step_name, "skipped", {"dry_run": True}, output, [])
        warnings.append("dry_run: изменения не сохранены (темы/посты/публикации не создаются)")

    # --- Внутреннее ---

    def _resolve_project(
        self, db: Session, project_id: int | None, project_slug: str | None
    ) -> Project:
        if project_id is not None:
            project = project_repository.get_project_by_id(db, project_id)
            if project is None:
                raise ProjectNotFoundError(project_id)
            return project
        if project_slug:
            project = project_repository.get_project_by_slug(db, project_slug)
            if project is None:
                raise ProjectNotFoundError(project_slug)
            return project
        raise ProjectNotFoundError("не задан project_id или project_slug")

    def _record_step(
        self,
        db: Session,
        run_id: int,
        step_name: str,
        status: str,
        input_payload: dict[str, object],
        output_payload: dict[str, object],
        warnings: list[str],
        errors: list[str] | None = None,
    ) -> None:
        step = repo.create_step(
            db,
            AutonomousRunStepCreate(
                run_id=run_id,
                step_name=step_name,
                status="running",
                input_payload=input_payload,
                started_at=_utcnow(),
            ),
        )
        repo.update_step(
            db,
            step,
            AutonomousRunStepUpdate(
                status=status,
                output_payload=output_payload,
                warnings=warnings,
                errors=errors or [],
                finished_at=_utcnow(),
            ),
        )

    def _build_result(
        self,
        db: Session,
        run: AutonomousRun,
        summary: AutonomousRunSummary,
        warnings: list[str],
        errors: list[str],
    ) -> AutonomousRunResult:
        steps = repo.list_steps(db, run.id)
        return AutonomousRunResult(
            run=AutonomousRunRead.model_validate(run),
            steps=[AutonomousRunStepRead.model_validate(step) for step in steps],
            selected_topics=summary.selected_topics_count,
            generated_posts=summary.generated_posts_count,
            posts_needing_media=summary.posts_needing_media_count,
            external_candidates=summary.external_candidates_count,
            submitted_for_review=summary.submitted_for_review_count,
            scheduled_publications=summary.scheduled_publications_count,
            published_publications=summary.published_publications_count,
            warnings=warnings,
            errors=errors,
        )

    @staticmethod
    def _next_actions(summary: AutonomousRunSummary, mode: str) -> list[str]:
        actions: list[str] = []
        if mode != "dry_run" and summary.generated_posts_count == 0:
            actions.append("Посты не созданы — проверьте бизнес-приоритеты и словарь тем")
        if summary.posts_needing_media_count > 0:
            actions.append(
                f"Добавьте/одобрите медиа для {summary.posts_needing_media_count} постов"
            )
        if summary.external_candidates_count > 0:
            actions.append(
                "Проверьте внешние картинки в /external-images (не выдавать за свой кейс)"
            )
        if summary.submitted_for_review_count > 0:
            actions.append(
                f"Согласуйте {summary.submitted_for_review_count} постов в /post-reviews"
            )
        if summary.scheduled_publications_count > 0:
            actions.append("Проверьте запланированные публикации в /post-publications")
        if summary.published_publications_count > 0:
            actions.append("Соберите аналитику опубликованных постов в /analytics")
        if mode == "dry_run":
            actions.append("Это был dry_run — запустите live-прогон для создания тем и постов")
        if not actions:
            actions.append("Действий не требуется")
        return actions
