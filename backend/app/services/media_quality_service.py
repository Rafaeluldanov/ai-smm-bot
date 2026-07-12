"""Оценка качества медиа (media quality scoring) — v0.4.6.

Botfleet оценивает каждое медиа проекта по пяти измерениям (качество / релевантность /
свежесть / уникальность / пригодность к платформе), выявляет проблемы и повторы и сохраняет
снимок (:class:`MediaQualitySnapshot`). Оценка **правило-ориентированная**: без внешнего AI,
без image embeddings, без сети и без live-публикаций.

БЕЗОПАСНОСТЬ:
- никаких внешних API/AI и live-публикаций; авто-ретегирование выключено;
- оценка worker-ом ВЫКЛЮЧЕНА по умолчанию (config), dry-run по умолчанию;
- строгая project/account-изоляция; без секретов и внутренних путей к файлам в ответах.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    crm_bot_smm_repository as crm_repo,
)
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    media_quality_repository,
    project_repository,
    schedule_media_decision_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService
    from app.services.client_learning_service import ClientLearningService

logger = get_logger(__name__)

_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "gif")
_HEIC_EXTS = ("heic", "heif")
_VIDEO_EXTS = ("mov", "mp4", "m4v", "avi", "mkv", "webm")
_TAG_GROUPS = ("products", "technologies", "details", "categories", "use_cases", "topics")
_USABLE_STATUSES = ("approved", "approved_video")
# Видимости, скрытые из авто-подбора (v0.4.8): низкая пригодность/overall для quality.
_HIDDEN_VISIBILITIES = ("hidden_duplicate", "hidden_weak", "hidden_manual", "archived")
# Границы размеров изображения (пиксели по меньшей стороне), если известны из варианта.
_MIN_SIDE = 600
_MAX_SIDE = 6000

# Веса overall (MVP, из спецификации): quality 30 / relevance 25 / freshness 20 /
# uniqueness 15 / platform_fit 10.
_WEIGHTS = {
    "quality": 0.30,
    "relevance": 0.25,
    "freshness": 0.20,
    "uniqueness": 0.15,
    "platform_fit": 0.10,
}


class MediaQualityError(Exception):
    """Ошибка оценки качества медиа (нет проекта/медиа) — API → 400."""


class MediaQualityService:
    """Правило-ориентированная оценка качества медиа + выявление дублей (без внешнего AI)."""

    def __init__(
        self,
        learning_service: ClientLearningService | None = None,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._learning = learning_service
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Оценка одного медиа                                              #
    # ------------------------------------------------------------------ #

    def score_media_asset(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        platform_key: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Оценить одно медиа. ``dry_run`` не пишет снимок; write-mode создаёт снимок."""
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise MediaQualityError("Медиа не принадлежит проекту")
        payload = self._evaluate(db, project_id, asset, platform_key)
        if dry_run:
            return {**payload, "writes": False}

        account_id = self._account_id(db, project_id)
        row = media_quality_repository.create_snapshot(
            db,
            account_id=account_id,
            project_id=project_id,
            media_asset_id=asset.id,
            media_asset_variant_id=payload["_variant_id"],
            platform_key=platform_key,
            status=payload["status"],
            quality_score=payload["quality_score"],
            relevance_score=payload["relevance_score"],
            freshness_score=payload["freshness_score"],
            uniqueness_score=payload["uniqueness_score"],
            platform_fit_score=payload["platform_fit_score"],
            overall_score=payload["overall_score"],
            issue_codes=payload["issue_codes"],
            positive_signals=payload["positive_signals"],
            negative_signals=payload["negative_signals"],
            duplicate_of_media_asset_id=payload["duplicate_of_media_asset_id"],
            last_used_at=payload["_last_used_at"],
            recent_usage_count=payload["recent_usage_count"],
            recommended_tags=payload["recommended_tags"],
            recommended_actions=payload["recommended_actions"],
            source_signals=payload["source_signals"],
            snapshot_metadata=payload["snapshot_metadata"],
        )
        # Ограничить историю снимков на медиа (кросс-СУБД, без секретов).
        media_quality_repository.delete_old_snapshots(
            db, project_id, asset.id, self._max_snapshots()
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_QUALITY_SCORED,
            {
                "snapshot_id": row.id,
                "media_asset_id": asset.id,
                "platform_key": platform_key,
                "status": row.status,
                "overall_score": row.overall_score,
                "issue_codes": list(row.issue_codes or []),
            },
        )
        if row.status in ("weak", "needs_tags"):
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_QUALITY_WEAK_DETECTED,
                {"snapshot_id": row.id, "media_asset_id": asset.id, "status": row.status},
            )
        if row.status == "duplicate" or row.duplicate_of_media_asset_id is not None:
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_QUALITY_DUPLICATE_DETECTED,
                {"snapshot_id": row.id, "media_asset_id": asset.id},
            )
        return {**self._snapshot_view(row), "writes": True}

    # ------------------------------------------------------------------ #
    # 2. Оценка пачки медиа проекта                                       #
    # ------------------------------------------------------------------ #

    def score_project_media(
        self,
        db: Session,
        project_id: int,
        platform_key: str | None = None,
        limit: int = 200,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Оценить пачку медиа проекта (до ``limit``). Возвращает сводку."""
        assets = media_asset_repository.list_media_assets_by_project(db, project_id)[
            : max(1, int(limit))
        ]
        scored = 0
        snapshots_created = 0
        weak = duplicates = excellent = good = 0
        results: list[dict[str, Any]] = []
        for asset in assets:
            try:
                result = self.score_media_asset(
                    db, project_id, asset.id, platform_key, dry_run=dry_run
                )
            except MediaQualityError:
                continue
            scored += 1
            if result.get("writes"):
                snapshots_created += 1
            status = result.get("status")
            if status == "weak" or status == "needs_tags":
                weak += 1
            if status == "duplicate" or result.get("duplicate_of_media_asset_id"):
                duplicates += 1
            if status == "excellent":
                excellent += 1
            if status == "good":
                good += 1
            results.append(result)
        self._write_audit(
            db,
            project_id,
            (
                audit_actions.ACTION_MEDIA_QUALITY_PREVIEWED
                if dry_run
                else audit_actions.ACTION_MEDIA_QUALITY_SCORED
            ),
            {
                "platform_key": platform_key,
                "scored": scored,
                "snapshots_created": snapshots_created,
                "weak": weak,
                "duplicates": duplicates,
                "dry_run": dry_run,
            },
        )
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "dry_run": dry_run,
            "scanned": len(assets),
            "scored": scored,
            "snapshots_created": snapshots_created,
            "excellent": excellent,
            "good": good,
            "weak": weak,
            "duplicates": duplicates,
            "results": results[:50],
        }

    # ------------------------------------------------------------------ #
    # 3. Признаки медиа                                                   #
    # ------------------------------------------------------------------ #

    def build_media_quality_features(
        self,
        db: Session,
        media_asset: Any,
        platform_key: str | None = None,
        detect_duplicates: bool = True,
    ) -> dict[str, Any]:
        """Собрать признаки медиа для оценки (без внешних вызовов и путей в ответе).

        ``detect_duplicates=False`` пропускает O(n)-скан дублей — для быстрого инлайн-скоринга
        кандидатов в auto media selection.
        """
        project_id = media_asset.project_id
        file_name = str(getattr(media_asset, "file_name", "") or "")
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext in _VIDEO_EXTS:
            media_kind = "video"
        elif ext in _IMAGE_EXTS or ext in _HEIC_EXTS:
            media_kind = "image"
        else:
            media_kind = "unknown"
        tags = getattr(media_asset, "tags", None) or {}
        products = [str(t) for t in (tags.get("products") or [])]
        technologies = [str(t) for t in (tags.get("technologies") or [])]
        categories = [str(t) for t in (tags.get("categories") or [])]
        all_tags = {
            _norm(v) for group in _TAG_GROUPS for v in (tags.get(group) or []) if str(v).strip()
        }

        variant = None
        try:
            variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(
                db, media_asset.id
            )
        except Exception:  # noqa: BLE001 — вариантов может не быть
            variant = None

        recency_days = self._recency_days()
        recent_usage_count = schedule_media_decision_repository.count_recent_media_usage(
            db, project_id, media_asset.id
        )
        last_used_at = getattr(media_asset, "last_used_at", None)
        if last_used_at is not None and _is_recent(last_used_at, recency_days):
            recent_usage_count += 1

        duplicate_candidates = (
            self.find_duplicate_candidates(db, media_asset) if detect_duplicates else []
        )
        # v0.4.7: визуальная похожесть по сохранённым fingerprint/кластерам дублей.
        visual_type, visual_members = (
            self._visual_similarity(db, project_id, media_asset)
            if detect_duplicates
            else (None, [])
        )
        merged_dupes = sorted(set(duplicate_candidates) | set(visual_members))

        return {
            "project_id": project_id,
            "media_asset_id": media_asset.id,
            "file_name": file_name,
            "extension": ext,
            "media_kind": media_kind,
            "status": str(getattr(media_asset, "status", "") or ""),
            "title": str(getattr(media_asset, "title", "") or ""),
            "description": str(getattr(media_asset, "description", "") or ""),
            "products": products,
            "technologies": technologies,
            "categories": categories,
            "all_tags": all_tags,
            "tag_count": len(all_tags),
            "has_yandex_path": bool(getattr(media_asset, "yandex_disk_path", None)),
            "has_variant": variant is not None,
            "variant_id": getattr(variant, "id", None),
            "width": getattr(variant, "width", None),
            "height": getattr(variant, "height", None),
            "file_size": getattr(variant, "file_size", None),
            "recent_usage_count": recent_usage_count,
            "last_used_at": last_used_at,
            "duplicate_candidates": merged_dupes,
            "visual_similarity_type": visual_type,
            "media_proxy_ready": self._media_proxy_ready(),
            # v0.4.8: видимость/статус курирования (скрытые — не для авто-подбора).
            "selection_visibility": str(getattr(media_asset, "selection_visibility", "selectable")),
            "curation_status": str(getattr(media_asset, "curation_status", "new")),
        }

    def _visual_similarity(
        self, db: Session, project_id: int, media_asset: Any
    ) -> tuple[str | None, list[int]]:
        """Визуальные дубли по сохранённым fingerprint/кластерам (v0.4.7). Без inline-расчёта."""
        s = self._resolve_settings()
        if not getattr(s, "media_fingerprinting_enabled_effective", False):
            return None, []
        from app.repositories import (
            media_duplicate_cluster_repository,
            media_fingerprint_repository,
        )

        members: set[int] = set()
        visual_type: str | None = None
        fp = media_fingerprint_repository.get_latest_for_asset(db, project_id, media_asset.id)
        if fp is not None and fp.file_sha256:
            for other in media_fingerprint_repository.list_by_sha256(
                db, project_id, fp.file_sha256
            ):
                if other.media_asset_id != media_asset.id:
                    members.add(other.media_asset_id)
                    visual_type = "exact_duplicate"
        if fp is not None and fp.perceptual_hash:
            for other in media_fingerprint_repository.list_by_perceptual_hash(
                db, project_id, fp.perceptual_hash
            ):
                if other.media_asset_id != media_asset.id:
                    members.add(other.media_asset_id)
                    visual_type = visual_type or "near_duplicate"
        cluster = media_duplicate_cluster_repository.find_cluster_for_media_asset(
            db, project_id, media_asset.id
        )
        if cluster is not None:
            for mid in cluster.member_media_asset_ids or []:
                if mid != media_asset.id:
                    members.add(mid)
            visual_type = visual_type or cluster.cluster_type
        return visual_type, sorted(members)

    # ------------------------------------------------------------------ #
    # 4-9. Скоринг измерений                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def calculate_quality_score(features: dict[str, Any]) -> int:
        """Качество: формат/статус/метаданные/теги/вариант/размеры. 0..100."""
        score = 40
        ext = features["extension"]
        if ext in _IMAGE_EXTS:
            score += 20
        elif ext in _HEIC_EXTS:
            score += 6
        elif features["media_kind"] == "video":
            score += 0
        else:
            score -= 10
        if features["status"] in _USABLE_STATUSES:
            score += 15
        elif features["status"] == "new":
            score += 5
        if features["title"]:
            score += 5
        if features["description"]:
            score += 5
        if features["tag_count"] >= 3:
            score += 15
        elif features["tag_count"] >= 1:
            score += 8
        if features["has_variant"]:
            score += 5
        width, height = features.get("width"), features.get("height")
        if isinstance(width, int) and isinstance(height, int) and width and height:
            if min(width, height) < _MIN_SIDE:
                score -= 15
            elif max(width, height) > _MAX_SIDE:
                score -= 5
        return _clamp(score)

    @staticmethod
    def calculate_relevance_score(
        features: dict[str, Any],
        topic: str | None = None,
        media_tags: list[str] | None = None,
    ) -> int:
        """Релевантность: пересечение тегов, слова темы, product/technology/category. 0..100."""
        wanted = {_norm(t) for t in (media_tags or []) if str(t).strip()}
        score = 45 if (wanted or topic) else 55  # без контекста — нейтрально
        if wanted and (features["all_tags"] & wanted):
            score += 30
        topic_tokens = {
            tok for tok in str(topic or "").lower().replace("#", " ").split() if len(tok) >= 4
        }
        file_lower = features["file_name"].lower()
        if topic_tokens and (
            (features["all_tags"] & topic_tokens) or any(tok in file_lower for tok in topic_tokens)
        ):
            score += 25
        if features["products"]:
            score += 10
        if features["technologies"]:
            score += 8
        if (
            features["categories"]
            and wanted
            and ({_norm(c) for c in features["categories"]} & wanted)
        ):
            score += 7
        return _clamp(score)

    @staticmethod
    def calculate_freshness_score(features: dict[str, Any]) -> int:
        """Свежесть: не использовалось = высоко; повтор = штраф. 0..100."""
        used = int(features.get("recent_usage_count") or 0)
        if used <= 0:
            return 92
        if used == 1:
            return 60
        return _clamp(45 - (used - 1) * 15)

    @staticmethod
    def calculate_uniqueness_score(features: dict[str, Any]) -> int:
        """Уникальность: визуальные дубли/серии штрафуются, уникальные — высоко. 0..100.

        v0.4.7: учитывает визуальную похожесть (visual_similarity_type) поверх метаданных.
        """
        visual = features.get("visual_similarity_type")
        if visual in ("exact_duplicate", "same_yandex_path"):
            return 25  # точный дубль — очень низкая уникальность
        if visual in ("near_duplicate", "visually_similar", "heic_jpeg_pair"):
            return 45  # почти дубль — средне-низкая
        if visual in ("same_series", "same_tag_signature", "same_file_name"):
            return 70  # однотипная серия — лёгкий штраф
        dups = features.get("duplicate_candidates") or []
        if not dups:
            return 90 if features["has_yandex_path"] else 80
        return _clamp(45 - (len(dups) - 1) * 10)

    def calculate_platform_fit_score(
        self, features: dict[str, Any], platform_key: str | None
    ) -> int:
        """Пригодность к платформе (Telegram/VK/Instagram/website/planned). 0..100."""
        platform = str(platform_key or "").lower()
        kind = features["media_kind"]
        if platform in ("", "all"):
            return 80 if kind == "image" else (35 if kind == "video" else 50)
        if kind == "video":
            return 25  # видео на этом этапе — planned/limited
        if platform == "telegram":
            return 70 if features["extension"] in _HEIC_EXTS else 90
        if platform == "vk":
            return 65 if features["extension"] in _HEIC_EXTS else 85
        if platform == "instagram":
            if not features["has_yandex_path"]:
                return 40  # локальный файл не годится для public image_url
            base = 80 if features["media_proxy_ready"] else 60
            return base if features["extension"] not in _HEIC_EXTS else base - 10
        if platform in ("website", "blog"):
            return 85 if kind == "image" else 40
        return 50  # planned/неизвестная платформа — preview only

    @staticmethod
    def calculate_overall_score(
        quality: int, relevance: int, freshness: int, uniqueness: int, platform_fit: int
    ) -> int:
        """Взвешенный overall: quality 30 / relevance 25 / freshness 20 / uniqueness 15 / fit 10."""
        total = (
            quality * _WEIGHTS["quality"]
            + relevance * _WEIGHTS["relevance"]
            + freshness * _WEIGHTS["freshness"]
            + uniqueness * _WEIGHTS["uniqueness"]
            + platform_fit * _WEIGHTS["platform_fit"]
        )
        return _clamp(round(total))

    # ------------------------------------------------------------------ #
    # 10-11. Проблемы / рекомендации / дубли                              #
    # ------------------------------------------------------------------ #

    def _collect_issues(
        self, features: dict[str, Any], platform_key: str | None, relevance: int
    ) -> tuple[list[str], list[str], list[str]]:
        """Определить issue-коды + положительные/отрицательные сигналы (без путей)."""
        issues: list[str] = []
        positives: list[str] = []
        negatives: list[str] = []
        ext = features["extension"]
        if ext in _HEIC_EXTS:
            issues.append("heic_conversion_needed")
        if features["media_kind"] == "video":
            issues.append("video_not_supported")
        elif features["media_kind"] == "unknown" and ext:
            issues.append("unsupported_format")
        if features["tag_count"] == 0:
            issues.append("missing_tags")
        if not features["products"]:
            issues.append("missing_product_tags")
        if not features["technologies"]:
            issues.append("missing_technology_tags")
        if int(features.get("recent_usage_count") or 0) >= 1:
            issues.append("recently_used")
        # v0.4.8: медиа скрыто из подбора курированием.
        if features.get("selection_visibility") in _HIDDEN_VISIBILITIES:
            issues.append("hidden_from_selection")
        if features.get("curation_status") == "duplicate":
            issues.append("duplicate_candidate")
        # v0.4.7: визуальная похожесть уточняет тип проблемы дублей.
        visual = features.get("visual_similarity_type")
        if visual in ("exact_duplicate", "near_duplicate", "same_yandex_path", "heic_jpeg_pair"):
            issues.append("duplicate_candidate")
        elif visual == "visually_similar":
            issues.append("visually_similar")
        elif visual in ("same_series", "same_tag_signature", "same_file_name"):
            issues.append("same_series")
        elif features.get("duplicate_candidates"):
            issues.append("duplicate_candidate")
        if relevance < 50:
            issues.append("weak_topic_match")
        platform = str(platform_key or "").lower()
        if platform == "instagram":
            issues.append("instagram_public_url_required")
            if not features["media_proxy_ready"]:
                issues.append("media_proxy_not_ready")
            if not features["has_yandex_path"]:
                issues.append("internal_path_only")
        width, height = features.get("width"), features.get("height")
        if isinstance(width, int) and isinstance(height, int) and width and height:
            if min(width, height) < _MIN_SIDE:
                issues.append("too_small")
            elif max(width, height) > _MAX_SIDE:
                issues.append("too_large")

        if features["tag_count"] >= 3:
            positives.append("rich_tags")
        if features["status"] in _USABLE_STATUSES:
            positives.append("approved")
        if features["has_variant"]:
            positives.append("enhanced_variant")
        if not features.get("duplicate_candidates"):
            positives.append("unique")
        if int(features.get("recent_usage_count") or 0) == 0:
            positives.append("fresh")
        negatives = list(dict.fromkeys(issues))
        return list(dict.fromkeys(issues)), positives, negatives

    @staticmethod
    def recommend_actions(
        features: dict[str, Any], scores: dict[str, int], issues: list[str]
    ) -> list[str]:
        """Человекочитаемые рекомендации по улучшению медиа."""
        actions: list[str] = []
        issue_set = set(issues)
        if "missing_tags" in issue_set:
            actions.append("Добавьте теги к медиа — иначе бот не поймёт, о чём оно.")
        if "missing_product_tags" in issue_set:
            actions.append("Добавьте product-тег (что за товар на фото).")
        if "missing_technology_tags" in issue_set:
            actions.append("Добавьте technology-тег (техника нанесения/материал).")
        if "unsupported_format" in issue_set:
            actions.append("Загрузите изображение в JPEG/PNG.")
        if "heic_conversion_needed" in issue_set:
            actions.append("Конвертируйте HEIC/HEIF в JPEG перед публикацией.")
        if "video_not_supported" in issue_set:
            actions.append("Видео пока не публикуется — подготовьте изображение.")
        if "recently_used" in issue_set:
            actions.append("Медиа недавно использовалось — не повторяйте в ближайшее время.")
        if "hidden_from_selection" in issue_set:
            actions.append("Медиа скрыто из подбора — восстановите или замените в курировании.")
        if "duplicate_candidate" in issue_set:
            actions.append("Похоже на дубль — оставьте canonical, остальное скройте/замените.")
        if "visually_similar" in issue_set:
            actions.append("Есть визуально похожие фото — выберите другое для разнообразия.")
        if "same_series" in issue_set:
            actions.append("Однотипная серия — объедините или добавьте различающие теги.")
        if "instagram_public_url_required" in issue_set or "media_proxy_not_ready" in issue_set:
            actions.append("Для Instagram подготовьте public image_url (media proxy).")
        if "internal_path_only" in issue_set:
            actions.append("У медиа нет публичного источника — нужен media proxy.")
        if "too_small" in issue_set:
            actions.append("Загрузите изображение большего размера.")
        if "weak_topic_match" in issue_set:
            actions.append("Слабое совпадение с темой — добавьте релевантные теги или замените.")
        return actions[:8]

    @staticmethod
    def recommend_tags(features: dict[str, Any]) -> list[str]:
        """Какие группы тегов стоит добавить (названия групп, без данных клиента)."""
        recs: list[str] = []
        if not features["products"]:
            recs.append("product")
        if not features["technologies"]:
            recs.append("technology")
        if not features["categories"]:
            recs.append("category")
        return recs

    def find_duplicate_candidates(self, db: Session, media_asset: Any) -> list[int]:
        """MVP-детект дублей: одинаковое имя/путь/заголовок/подпись тегов (без embeddings)."""
        if not self._dedup_enabled():
            return []
        target_name = _norm(getattr(media_asset, "file_name", ""))
        target_title = _norm(getattr(media_asset, "title", ""))
        target_sig = _tag_signature(getattr(media_asset, "tags", None) or {})
        target_path = getattr(media_asset, "yandex_disk_path", None)
        out: list[int] = []
        for other in media_asset_repository.list_media_assets_by_project(
            db, media_asset.project_id
        ):
            if other.id == media_asset.id:
                continue
            same_name = target_name and _norm(other.file_name) == target_name
            same_title = target_title and _norm(getattr(other, "title", "")) == target_title
            same_path = (
                target_path is not None and getattr(other, "yandex_disk_path", None) == target_path
            )
            same_sig = bool(target_sig) and _tag_signature(other.tags or {}) == target_sig
            if same_name or same_title or same_path or same_sig:
                out.append(other.id)
        return out

    # ------------------------------------------------------------------ #
    # Инлайн-оценка для auto media selection (v0.4.6, Часть 6)            #
    # ------------------------------------------------------------------ #

    def quality_overall_for_asset(
        self,
        db: Session,
        project_id: int,
        asset: Any,
        platform_key: str | None = None,
        media_tags: list[str] | None = None,
    ) -> dict[str, Any]:
        """Лёгкая оценка качества медиа для ранжирования кандидатов (снимок → dry-run).

        Предпочитает существующий снимок; иначе считает быстро (без скана дублей). Возвращает
        безопасный вид: баллы, issues, recent, snapshot_id (без путей/имён файлов).
        """
        snapshot = media_quality_repository.get_latest_for_asset_platform(
            db, project_id, asset.id, platform_key
        ) or media_quality_repository.get_latest_for_asset(db, project_id, asset.id)
        if snapshot is not None and snapshot.overall_score is not None:
            return {
                "overall": snapshot.overall_score,
                "quality": snapshot.quality_score,
                "relevance": snapshot.relevance_score,
                "freshness": snapshot.freshness_score,
                "uniqueness": snapshot.uniqueness_score,
                "platform_fit": snapshot.platform_fit_score,
                "issues": list(snapshot.issue_codes or []),
                "recent": (snapshot.recent_usage_count or 0) > 0,
                "snapshot_id": snapshot.id,
            }
        features = self.build_media_quality_features(
            db, asset, platform_key, detect_duplicates=False
        )
        quality = self.calculate_quality_score(features)
        relevance = self.calculate_relevance_score(features, None, media_tags)
        freshness = self.calculate_freshness_score(features)
        uniqueness = self.calculate_uniqueness_score(features)
        platform_fit = self.calculate_platform_fit_score(features, platform_key)
        overall = self.calculate_overall_score(
            quality, relevance, freshness, uniqueness, platform_fit
        )
        issues, _positives, _negatives = self._collect_issues(features, platform_key, relevance)
        return {
            "overall": overall,
            "quality": quality,
            "relevance": relevance,
            "freshness": freshness,
            "uniqueness": uniqueness,
            "platform_fit": platform_fit,
            "issues": issues,
            "recent": int(features.get("recent_usage_count") or 0) > 0,
            "snapshot_id": None,
        }

    # ------------------------------------------------------------------ #
    # 12. Дашборд                                                         #
    # ------------------------------------------------------------------ #

    def build_media_quality_dashboard(
        self, db: Session, project_id: int, platform_key: str | None = None
    ) -> dict[str, Any]:
        """Сводка качества медиа проекта для UI (последний снимок на медиа)."""
        rows = media_quality_repository.list_for_project(
            db, project_id, platform_key=platform_key, limit=1000
        )
        latest: dict[int, Any] = {}
        for row in rows:  # rows свежие первыми → первый на медиа = последний снимок
            latest.setdefault(row.media_asset_id, row)
        snapshots = list(latest.values())
        total_media = len(media_asset_repository.list_media_assets_by_project(db, project_id))
        excellent = good = weak = duplicates = 0
        issues: dict[str, int] = {}
        scores: list[int] = []
        for row in snapshots:
            if row.status == "excellent":
                excellent += 1
            elif row.status == "good":
                good += 1
            elif row.status in ("weak", "needs_tags"):
                weak += 1
            if row.status == "duplicate" or row.duplicate_of_media_asset_id is not None:
                duplicates += 1
            if row.overall_score is not None:
                scores.append(row.overall_score)
            for issue in row.issue_codes or []:
                issues[issue] = issues.get(issue, 0) + 1
        best = media_quality_repository.list_best_for_project(db, project_id, limit=10)
        weak_rows = media_quality_repository.list_weak_for_project(
            db, project_id, max_score=self._min_good(), limit=10
        )
        dup_rows = media_quality_repository.list_duplicates_for_project(db, project_id, limit=10)
        return {
            "project_id": project_id,
            "platform_key": platform_key,
            "total_media": total_media,
            "scored": len(snapshots),
            "excellent": excellent,
            "good": good,
            "weak": weak,
            "duplicates": duplicates,
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
            "common_issues": sorted(issues.items(), key=lambda kv: kv[1], reverse=True)[:8],
            "worker_enabled": self._worker_enabled(),
            "best_media": [self._snapshot_view(r) for r in best],
            "weak_media": [self._snapshot_view(r) for r in weak_rows],
            "duplicate_media": [self._snapshot_view(r) for r in dup_rows],
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _evaluate(
        self, db: Session, project_id: int, asset: Any, platform_key: str | None
    ) -> dict[str, Any]:
        """Полная оценка медиа: признаки → баллы → issues → статус → рекомендации."""
        features = self.build_media_quality_features(db, asset, platform_key)
        media_tags = self._project_media_tags(db, project_id)
        quality = self.calculate_quality_score(features)
        relevance = self.calculate_relevance_score(features, None, media_tags)
        freshness = self.calculate_freshness_score(features)
        uniqueness = self.calculate_uniqueness_score(features)
        platform_fit = self.calculate_platform_fit_score(features, platform_key)
        # v0.4.8: скрытое из подбора медиа — сильно ниже по пригодности/overall.
        if features.get("selection_visibility") in _HIDDEN_VISIBILITIES:
            platform_fit = min(platform_fit, 20)
        overall = self.calculate_overall_score(
            quality, relevance, freshness, uniqueness, platform_fit
        )
        if features.get("selection_visibility") in _HIDDEN_VISIBILITIES:
            overall = min(overall, 30)
        scores = {
            "quality": quality,
            "relevance": relevance,
            "freshness": freshness,
            "uniqueness": uniqueness,
            "platform_fit": platform_fit,
            "overall": overall,
        }
        issues, positives, negatives = self._collect_issues(features, platform_key, relevance)
        status = self._status_for(features, overall, issues)
        duplicate_of = (
            features["duplicate_candidates"][0] if features["duplicate_candidates"] else None
        )
        signals = ["metadata", "tags", "usage_history"]
        if features["has_variant"]:
            signals.append("estimated")
        return {
            "project_id": project_id,
            "media_asset_id": asset.id,
            "platform_key": platform_key,
            "status": status,
            "quality_score": quality,
            "relevance_score": relevance,
            "freshness_score": freshness,
            "uniqueness_score": uniqueness,
            "platform_fit_score": platform_fit,
            "overall_score": overall,
            "issue_codes": issues,
            "positive_signals": positives,
            "negative_signals": negatives,
            "duplicate_of_media_asset_id": duplicate_of,
            "recent_usage_count": features["recent_usage_count"],
            "recommended_tags": self.recommend_tags(features),
            "recommended_actions": self.recommend_actions(features, scores, issues),
            "source_signals": signals,
            "snapshot_metadata": {
                "media_kind": features["media_kind"],
                "extension": features["extension"],
                "tag_count": features["tag_count"],
                "has_variant": features["has_variant"],
                "duplicate_candidate_count": len(features["duplicate_candidates"]),
                "min_good": self._min_good(),
                "min_excellent": self._min_excellent(),
            },
            "_variant_id": features["variant_id"],
            "_last_used_at": features["last_used_at"],
        }

    def _status_for(self, features: dict[str, Any], overall: int, issues: list[str]) -> str:
        if "unsupported_format" in issues:
            return "unsupported"
        if "duplicate_candidate" in issues:
            return "duplicate"
        if features["tag_count"] == 0:
            return "needs_tags"
        if overall >= self._min_excellent():
            return "excellent"
        if overall >= self._min_good():
            return "good"
        return "weak"

    def _project_media_tags(self, db: Session, project_id: int) -> list[str]:
        config = crm_repo.get_config_by_project_id(db, project_id)
        if config is None:
            return []
        tags: set[str] = set()
        for cat in crm_repo.list_categories_by_config(db, config.id):
            for tag in cat.media_tags or []:
                tags.add(str(tag))
        return sorted(tags)

    def _snapshot_view(self, row: Any) -> dict[str, Any]:
        # ВНИМАНИЕ: только безопасные поля. Никаких yandex_disk_path/имён файлов/путей.
        return {
            "id": row.id,
            "project_id": row.project_id,
            "media_asset_id": row.media_asset_id,
            "media_asset_variant_id": row.media_asset_variant_id,
            "platform_key": row.platform_key,
            "status": row.status,
            "quality_score": row.quality_score,
            "relevance_score": row.relevance_score,
            "freshness_score": row.freshness_score,
            "uniqueness_score": row.uniqueness_score,
            "platform_fit_score": row.platform_fit_score,
            "overall_score": row.overall_score,
            "issue_codes": list(row.issue_codes or []),
            "positive_signals": list(row.positive_signals or []),
            "negative_signals": list(row.negative_signals or []),
            "duplicate_of_media_asset_id": row.duplicate_of_media_asset_id,
            "recent_usage_count": row.recent_usage_count,
            "recommended_tags": list(row.recommended_tags or []),
            "recommended_actions": list(row.recommended_actions or []),
            "source_signals": list(row.source_signals or []),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise MediaQualityError(f"Проект id={project_id} не найден")
        return project.account_id

    # --- Настройки ---

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().media_quality_scoring_worker_enabled_effective)

    def _dedup_enabled(self) -> bool:
        return bool(getattr(self._resolve_settings(), "media_quality_dedup_enabled", True))

    def _min_good(self) -> int:
        return int(self._resolve_settings().media_quality_min_good_score_safe)

    def _min_excellent(self) -> int:
        return int(self._resolve_settings().media_quality_min_excellent_score_safe)

    def _recency_days(self) -> int:
        return int(self._resolve_settings().media_quality_recency_days_safe)

    def _max_snapshots(self) -> int:
        return max(
            1, int(getattr(self._resolve_settings(), "media_quality_max_snapshots_per_asset", 20))
        )

    def _media_proxy_ready(self) -> bool:
        s = self._resolve_settings()
        return bool(
            getattr(s, "media_proxy_enabled_effective", False)
            and getattr(s, "media_proxy_https_ready", False)
        )

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
            entity_type="media_quality_snapshot",
            metadata=metadata,
        )


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _clamp(value: float) -> int:
    return int(max(0, min(100, round(value))))


def _tag_signature(tags: dict[str, Any]) -> str:
    values: set[str] = set()
    for group in _TAG_GROUPS:
        for value in tags.get(group, []) or []:
            norm = _norm(value)
            if norm:
                values.add(norm)
    return "|".join(sorted(values))


def _is_recent(when: datetime, days: int) -> bool:
    try:
        ref = when if when.tzinfo else when.replace(tzinfo=UTC)
    except (AttributeError, ValueError):
        return False
    return ref >= datetime.now(UTC) - timedelta(days=days)


def get_media_quality_service() -> MediaQualityService:
    """DI-фабрика сервиса оценки качества медиа."""
    return MediaQualityService()
