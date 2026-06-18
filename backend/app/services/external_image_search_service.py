"""Сервис поиска и безопасного использования внешних изображений (Этап 9).

Ищет внешние картинки под тему/пост через провайдеров (fake на этом этапе),
фильтрует по лицензии и безопасности, сохраняет кандидатов с источником/правами
и умеет безопасно конвертировать одобренного кандидата в ``MediaAsset``.

Главное правило: внешнее изображение — НЕ наш кейс. Реальные стоки и сеть не
задействуются; изображения не скачиваются.
"""

import re

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.external_image_candidate import ExternalImageCandidate
from app.models.post import Post
from app.models.project import Project
from app.models.topic import Topic
from app.repositories import (
    external_image_repository,
    media_asset_repository,
    post_repository,
    project_repository,
    topic_repository,
)
from app.repositories.external_image_repository import ExternalImageCandidateNotFoundError
from app.repositories.post_repository import PostNotFoundError
from app.repositories.topic_repository import TopicNotFoundError
from app.schemas.external_image import (
    ExternalImageCandidateCreate,
    ExternalImageCandidateRead,
    ExternalImageCandidateUpdate,
    ExternalImageConvertRequest,
    ExternalImageConvertResult,
    ExternalImageReviewRequest,
    ExternalImageSafetyReport,
    ExternalImageSearchRequest,
    ExternalImageSearchResult,
)
from app.schemas.media_asset import MediaAssetCreate
from app.services.external_image_license_policy import (
    build_forbidden_usage,
    can_convert_to_media_asset,
    evaluate_candidate_safety,
)
from app.services.external_image_provider import (
    ExternalImageProviderError,
    ExternalImageProviderResult,
)
from app.services.external_image_provider_registry import ExternalImageProviderRegistry
from app.services.media_tagging_service import MediaTaggingService
from app.services.yandex_disk_media_sync_service import ProjectNotFoundError

logger = get_logger(__name__)

_SLUG_RE = re.compile(r"[^0-9a-zа-я]+")


class ExternalImageConversionError(Exception):
    """Кандидата нельзя сконвертировать в MediaAsset (API → 409)."""

    def __init__(self, reasons: list[str]) -> None:
        self.reasons = reasons
        super().__init__("; ".join(reasons))


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower().replace("ё", "е")).strip("-")
    return slug[:80]


class ExternalImageSearchService:
    """Поиск внешних изображений, review и конвертация в MediaAsset."""

    def __init__(
        self,
        registry: ExternalImageProviderRegistry,
        tagging_service: MediaTaggingService,
    ) -> None:
        self._registry = registry
        self._tagging = tagging_service

    # --- Поиск ---

    def search_images(
        self, db: Session, request: ExternalImageSearchRequest
    ) -> ExternalImageSearchResult:
        """Найти внешние изображения под тему/пост и сохранить кандидатов."""
        project, topic, post = self._resolve_context(db, request)
        warnings: list[str] = []
        query = self._resolve_query(request, topic, post)
        if not query:
            warnings.append("Не задан query и его не удалось вывести из темы/поста")
            return ExternalImageSearchResult(
                project_id=project.id, project_slug=project.slug, query="", warnings=warnings
            )

        available = set(self._registry.get_available_providers())
        for name in request.providers:
            if name not in available:
                warnings.append(f"Провайдер '{name}' недоступен — пропущен")
        providers = self._registry.get_providers(request.providers)

        found = created = skipped = 0
        candidates: list[ExternalImageCandidateRead] = []
        for provider in providers:
            try:
                results = provider.search(query, request.limit)
            except ExternalImageProviderError as exc:
                warnings.append(f"Провайдер {provider.name}: {exc}")
                continue
            for result in results:
                found += 1
                if self._filtered_out(result, request):
                    skipped += 1
                    continue
                candidate, action = self._store_candidate(
                    db, project_id=project.id, topic=topic, post=post, query=query, result=result
                )
                if action == "created":
                    created += 1
                else:
                    skipped += 1
                candidates.append(ExternalImageCandidateRead.model_validate(candidate))

        return ExternalImageSearchResult(
            project_id=project.id,
            project_slug=project.slug,
            query=query,
            found_count=found,
            created=created,
            skipped=skipped,
            candidates=candidates,
            warnings=warnings,
        )

    def search_for_post(
        self, db: Session, post_id: int, limit: int = 10
    ) -> ExternalImageSearchResult:
        """Найти внешние изображения под пост."""
        return self.search_images(db, ExternalImageSearchRequest(post_id=post_id, limit=limit))

    def search_for_topic(
        self, db: Session, topic_id: int, limit: int = 10
    ) -> ExternalImageSearchResult:
        """Найти внешние изображения под тему."""
        return self.search_images(db, ExternalImageSearchRequest(topic_id=topic_id, limit=limit))

    # --- Review / конвертация ---

    def review_candidate(
        self, db: Session, candidate_id: int, request: ExternalImageReviewRequest
    ) -> ExternalImageCandidateRead:
        """Сменить статус review кандидата."""
        candidate = external_image_repository.mark_review_status(
            db,
            candidate_id,
            request.review_status,
            reviewed_by=request.reviewed_by,
            rejection_reason=request.rejection_reason,
        )
        return ExternalImageCandidateRead.model_validate(candidate)

    def get_safety_report(self, db: Session, candidate_id: int) -> ExternalImageSafetyReport:
        """Вернуть оценку безопасности кандидата."""
        candidate = external_image_repository.get_candidate_by_id(db, candidate_id)
        if candidate is None:
            raise ExternalImageCandidateNotFoundError(candidate_id)
        return evaluate_candidate_safety(candidate)

    def convert_candidate_to_media_asset(
        self, db: Session, candidate_id: int, request: ExternalImageConvertRequest
    ) -> ExternalImageConvertResult:
        """Безопасно конвертировать одобренного кандидата в MediaAsset."""
        candidate = external_image_repository.get_candidate_by_id(db, candidate_id)
        if candidate is None:
            raise ExternalImageCandidateNotFoundError(candidate_id)

        can_convert, reasons = can_convert_to_media_asset(candidate)
        if not can_convert:
            raise ExternalImageConversionError(reasons)

        file_name = self._build_file_name(candidate, request)
        disk_path = request.save_to_yandex_disk_path or (
            f"external://{candidate.provider}/{candidate.id}"
        )
        # Внешнее изображение НИКОГДА не company_owned.
        license_type = (
            "external_needs_review" if candidate.attribution_required else "commercial_use_required"
        )
        media_asset = media_asset_repository.create_media_asset(
            db,
            MediaAssetCreate(
                project_id=candidate.project_id,
                file_name=file_name,
                yandex_disk_path=disk_path,
                source_type="external_stock",
                license_type=license_type,
                title=request.title or candidate.title or candidate.query,
                description=request.description or candidate.description,
                tags=dict(candidate.tags or {}),
                status=request.status or "needs_license_review",
            ),
        )

        updated = external_image_repository.update_candidate(
            db,
            candidate,
            ExternalImageCandidateUpdate(
                media_asset_id=media_asset.id, review_status="converted_to_media_asset"
            ),
        )

        warnings = ["Внешнее изображение нельзя использовать как наш кейс/портфолио"]
        if candidate.attribution_required:
            author = candidate.author_name or "автор не указан"
            warnings.append(f"Требуется указание автора: {author} ({candidate.license_name})")

        logger.info(
            "Кандидат id=%s сконвертирован в MediaAsset id=%s (license=%s)",
            candidate.id,
            media_asset.id,
            license_type,
        )
        return ExternalImageConvertResult(
            candidate=ExternalImageCandidateRead.model_validate(updated),
            media_asset_id=media_asset.id,
            warnings=warnings,
        )

    # --- Внутреннее ---

    def _resolve_context(
        self, db: Session, request: ExternalImageSearchRequest
    ) -> tuple[Project, Topic | None, Post | None]:
        topic: Topic | None = None
        post: Post | None = None
        project: Project | None
        if request.post_id is not None:
            post = post_repository.get_post_by_id(db, request.post_id)
            if post is None:
                raise PostNotFoundError(request.post_id)
            if post.topic_id is not None:
                topic = topic_repository.get_topic_by_id(db, post.topic_id)
            project = project_repository.get_project_by_id(db, post.project_id)
        elif request.topic_id is not None:
            topic = topic_repository.get_topic_by_id(db, request.topic_id)
            if topic is None:
                raise TopicNotFoundError(request.topic_id)
            project = project_repository.get_project_by_id(db, topic.project_id)
        elif request.project_id is not None:
            project = project_repository.get_project_by_id(db, request.project_id)
        elif request.project_slug:
            project = project_repository.get_project_by_slug(db, request.project_slug)
        else:
            raise ProjectNotFoundError("не задан project_id/project_slug/topic_id/post_id")

        if project is None:
            identifier: object = (
                request.project_id if request.project_id is not None else request.project_slug
            )
            raise ProjectNotFoundError(identifier if identifier is not None else "проект")
        return project, topic, post

    @staticmethod
    def _resolve_query(
        request: ExternalImageSearchRequest, topic: Topic | None, post: Post | None
    ) -> str:
        if request.query:
            return request.query
        if topic is not None and topic.title:
            return topic.title
        if post is not None and post.title:
            return post.title
        return ""

    @staticmethod
    def _filtered_out(
        result: ExternalImageProviderResult, request: ExternalImageSearchRequest
    ) -> bool:
        return (
            (request.require_commercial_use and not result.commercial_use_allowed)
            or (request.require_no_logo and result.contains_logo)
            or (request.require_safe_for_business and not result.safe_for_business)
        )

    @staticmethod
    def _auto_review_status(result: ExternalImageProviderResult) -> str:
        if not result.commercial_use_allowed or not result.safe_for_business:
            return "rejected"
        if result.attribution_required or result.contains_people or result.contains_logo:
            return "needs_review"
        return "approved"

    def _store_candidate(
        self,
        db: Session,
        project_id: int,
        topic: Topic | None,
        post: Post | None,
        query: str,
        result: ExternalImageProviderResult,
    ) -> tuple[ExternalImageCandidate, str]:
        tags = self._tagging.analyze_file_name(
            f"{query} {result.title or ''}", source_type="external_stock"
        )
        data = ExternalImageCandidateCreate(
            project_id=project_id,
            topic_id=topic.id if topic is not None else None,
            post_id=post.id if post is not None else None,
            query=query,
            provider=result.provider,
            source_url=result.source_url,
            preview_url=result.preview_url,
            download_url=result.download_url,
            title=result.title,
            description=result.description,
            author_name=result.author_name,
            author_url=result.author_url,
            license_name=result.license_name,
            license_url=result.license_url,
            commercial_use_allowed=result.commercial_use_allowed,
            modification_allowed=result.modification_allowed,
            attribution_required=result.attribution_required,
            contains_people=result.contains_people,
            contains_logo=result.contains_logo,
            safe_for_business=result.safe_for_business,
            forbidden_usage=build_forbidden_usage(result),
            tags=tags,
            review_status=self._auto_review_status(result),
        )
        return external_image_repository.upsert_candidate(db, data)

    @staticmethod
    def _build_file_name(
        candidate: ExternalImageCandidate, request: ExternalImageConvertRequest
    ) -> str:
        base = request.title or candidate.title or candidate.query
        slug = _slugify(base) if base else ""
        if slug:
            return f"{slug}.jpg"
        return f"external-{candidate.provider}-{candidate.id}.jpg"
