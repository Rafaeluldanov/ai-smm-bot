"""Fingerprint медиа (visual fingerprinting) — v0.4.7.

Botfleet считает безопасные ЛОКАЛЬНЫЕ fingerprint медиа: file sha256, perceptual/average/
difference hash (через Pillow), color/dimension/metadata/tag signature. Без внешнего AI/vision,
без сети по умолчанию (Yandex-скачивание выключено), без live-публикаций.

БЕЗОПАСНОСТЬ:
- НЕ хранит raw bytes, внутренние пути к файлам и секреты — только хэши/сигнатуры;
- имя файла/путь/заголовок хэшируются (name_hash/yandex_path_hash/title_hash), не хранятся сырыми;
- при недоступности байтов → graceful fallback (status partial, source metadata_only);
- строгая project/account-изоляция; авто-ретегирование/удаление не выполняется.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from io import BytesIO
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    media_asset_repository,
    media_asset_variant_repository,
    media_fingerprint_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

try:  # Pillow — уже зависимость (image enhancement). Отсутствие → graceful metadata-only.
    from PIL import Image, ImageStat

    _PIL_AVAILABLE = True
except Exception:  # noqa: BLE001 — среда без Pillow работает в metadata-only режиме
    _PIL_AVAILABLE = False

_IMAGE_EXTS = ("jpg", "jpeg", "png", "webp", "gif", "bmp")
_HEIC_EXTS = ("heic", "heif")
_VIDEO_EXTS = ("mov", "mp4", "m4v", "avi", "mkv", "webm")
_TAG_GROUPS = ("products", "technologies", "details", "categories", "use_cases", "topics")
# Ограничение размера локального файла для чтения (защита от чтения гигантских файлов).
_MAX_LOCAL_BYTES = 25 * 1024 * 1024


class MediaFingerprintError(Exception):
    """Ошибка расчёта fingerprint (нет проекта/медиа) — API → 400."""


class MediaFingerprintService:
    """Локальный расчёт fingerprint медиа (sha256 + perceptual hash + сигнатуры). Без AI."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1. Расчёт fingerprint одного медиа                                  #
    # ------------------------------------------------------------------ #

    def calculate_fingerprint_for_asset(
        self,
        db: Session,
        project_id: int,
        media_asset_id: int,
        platform_key: str | None = None,  # noqa: ARG002 — единый интерфейс с quality/decision
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Рассчитать fingerprint медиа. ``dry_run`` не пишет; write-mode создаёт запись."""
        asset = media_asset_repository.get_media_asset_by_id(db, media_asset_id)
        if asset is None or asset.project_id != project_id:
            raise MediaFingerprintError("Медиа не принадлежит проекту")
        payload = self._evaluate(db, project_id, asset)
        if dry_run:
            return {**self.fingerprint_result_to_public(payload), "writes": False}

        account_id = self._account_id(db, project_id)
        row = media_fingerprint_repository.create_fingerprint(
            db,
            account_id=account_id,
            project_id=project_id,
            media_asset_id=asset.id,
            media_asset_variant_id=payload["_variant_id"],
            status=payload["status"],
            source=payload["source"],
            file_sha256=payload["file_sha256"],
            perceptual_hash=payload["perceptual_hash"],
            average_hash=payload["average_hash"],
            difference_hash=payload["difference_hash"],
            color_signature=payload["color_signature"],
            dimension_signature=payload["dimension_signature"],
            metadata_signature=payload["metadata_signature"],
            tag_signature=payload["tag_signature"],
            fingerprint_metadata=payload["fingerprint_metadata"],
            calculated_at=datetime.now(UTC),
        )
        self._write_audit(
            db,
            project_id,
            audit_actions.ACTION_MEDIA_FINGERPRINT_CALCULATED,
            {
                "fingerprint_id": row.id,
                "media_asset_id": asset.id,
                "status": row.status,
                "source": row.source,
                "has_visual_hash": bool(row.perceptual_hash),
            },
        )
        return {**self.fingerprint_result_to_public(payload, row), "writes": True}

    # ------------------------------------------------------------------ #
    # 2. Пакетный расчёт                                                  #
    # ------------------------------------------------------------------ #

    def calculate_project_fingerprints(
        self,
        db: Session,
        project_id: int,
        limit: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Рассчитать fingerprint пачки медиа проекта (уважает MAX_ASSETS_PER_RUN)."""
        cap = self._max_per_run() if limit is None else min(int(limit), self._max_per_run())
        assets = media_asset_repository.list_media_assets_by_project(db, project_id)[: max(1, cap)]
        calculated = created = partial = unavailable = 0
        results: list[dict[str, Any]] = []
        for asset in assets:
            try:
                result = self.calculate_fingerprint_for_asset(
                    db, project_id, asset.id, dry_run=dry_run
                )
            except MediaFingerprintError:
                continue
            if result.get("writes"):
                created += 1
            status = result.get("status")
            if status == "calculated":
                calculated += 1
            elif status == "partial":
                partial += 1
            elif status == "unavailable":
                unavailable += 1
            results.append(result)
        self._write_audit(
            db,
            project_id,
            (
                audit_actions.ACTION_MEDIA_FINGERPRINT_PREVIEWED
                if dry_run
                else audit_actions.ACTION_MEDIA_FINGERPRINT_CALCULATED
            ),
            {
                "scanned": len(assets),
                "created": created,
                "calculated": calculated,
                "partial": partial,
                "dry_run": dry_run,
            },
        )
        return {
            "project_id": project_id,
            "dry_run": dry_run,
            "scanned": len(assets),
            "created": created,
            "calculated": calculated,
            "partial": partial,
            "unavailable": unavailable,
            "results": results[:50],
        }

    # ------------------------------------------------------------------ #
    # 3-8. Признаки, хэши, сигнатуры                                      #
    # ------------------------------------------------------------------ #

    def build_fingerprint_features(self, db: Session, media_asset: Any) -> dict[str, Any]:
        """Собрать признаки медиа + локальные байты (если доступны и разрешены)."""
        s = self._resolve_settings()
        file_name = str(getattr(media_asset, "file_name", "") or "")
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext in _VIDEO_EXTS:
            media_kind = "video"
        elif ext in _IMAGE_EXTS or ext in _HEIC_EXTS:
            media_kind = "image"
        else:
            media_kind = "unknown"

        variant = None
        content: bytes | None = None
        source = "metadata_only"
        if getattr(s, "media_fingerprinting_use_variants", True):
            try:
                variant = media_asset_variant_repository.get_latest_approved_enhanced_variant(
                    db, media_asset.id
                )
            except Exception:  # noqa: BLE001 — вариантов может не быть
                variant = None
            if variant is not None and getattr(variant, "output_path", None):
                content = self._read_local_bytes(str(variant.output_path))
                if content is not None:
                    source = "media_variant"
        # Yandex-скачивание по умолчанию ВЫКЛЮЧЕНО (без сети). Реализуется отдельно при
        # media_fingerprinting_use_yandex_download=true; здесь намеренно не вызываем сеть.

        dimension_signature: dict[str, Any] = {}
        if variant is not None:
            w, h = getattr(variant, "width", None), getattr(variant, "height", None)
            dimension_signature = {
                "width": w,
                "height": h,
                "file_size": getattr(variant, "file_size", None),
                "aspect_ratio": (
                    round(w / h, 3) if isinstance(w, int) and isinstance(h, int) and h else None
                ),
            }
        return {
            "file_name": file_name,
            "extension": ext,
            "media_kind": media_kind,
            "content": content,
            "source": source,
            "variant_id": getattr(variant, "id", None),
            "dimension_signature": dimension_signature,
        }

    @staticmethod
    def calculate_file_sha256(content: bytes) -> str:
        """SHA-256 байтов файла (точный дубль байтов)."""
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def calculate_perceptual_hash(content: bytes, file_name: str) -> dict[str, str]:
        """average_hash (8×8) + difference_hash (dHash 9×8) + perceptual_hash. Пусто при сбое."""
        if not _PIL_AVAILABLE:
            return {}
        try:
            with Image.open(BytesIO(content)) as img:
                gray = img.convert("L")
                small = gray.resize((8, 8))
                pixels = list(small.getdata())
                avg = sum(pixels) / len(pixels) if pixels else 0
                abits = "".join("1" if p >= avg else "0" for p in pixels)
                average_hash = f"{int(abits, 2):016x}" if abits else ""

                dimg = gray.resize((9, 8))
                dpx = list(dimg.getdata())
                dbits = "".join(
                    "1" if dpx[row * 9 + col] > dpx[row * 9 + col + 1] else "0"
                    for row in range(8)
                    for col in range(8)
                )
                difference_hash = f"{int(dbits, 2):016x}" if dbits else ""
        except Exception:  # noqa: BLE001 — недекодируемое (например, HEIC без плагина)
            return {}
        return {
            "average_hash": average_hash,
            "difference_hash": difference_hash,
            "perceptual_hash": average_hash,
        }

    @staticmethod
    def calculate_color_signature(content: bytes, file_name: str) -> dict[str, Any]:
        """Грубая цветовая сигнатура: средний RGB, яркость, aspect ratio, RGB-бакеты."""
        if not _PIL_AVAILABLE:
            return {}
        try:
            with Image.open(BytesIO(content)) as img:
                rgb = img.convert("RGB")
                stat = ImageStat.Stat(rgb)
                r, g, b = (stat.mean + [0, 0, 0])[:3]
                brightness = ImageStat.Stat(rgb.convert("L")).mean[0]
                w, h = rgb.size
        except Exception:  # noqa: BLE001
            return {}
        return {
            "avg_rgb": [round(r, 1), round(g, 1), round(b, 1)],
            "brightness": round(brightness, 1),
            "aspect_ratio": round(w / h, 3) if h else None,
            "buckets": {"r": int(r // 32), "g": int(g // 32), "b": int(b // 32)},
        }

    def build_metadata_signature(self, media_asset: Any) -> dict[str, Any]:
        """Метаданные-сигнатура. Имя файла/путь/заголовок ХЭШИРУЮТСЯ (без сырых значений/путей)."""
        file_name = str(getattr(media_asset, "file_name", "") or "")
        ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
        if ext in _VIDEO_EXTS:
            media_kind = "video"
        elif ext in _IMAGE_EXTS or ext in _HEIC_EXTS:
            media_kind = "image"
        else:
            media_kind = "unknown"
        title = str(getattr(media_asset, "title", "") or "")
        path = getattr(media_asset, "yandex_disk_path", None)
        base_name = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
        return {
            "extension": ext,
            "media_kind": media_kind,
            "name_hash": _short_hash(_norm(file_name)) if file_name else "",
            # base-name без расширения — для детекта пар HEIC/JPEG одного изображения.
            "base_name_hash": _short_hash(_norm(base_name)) if base_name else "",
            "title_hash": _short_hash(_norm(title)) if title else "",
            "yandex_path_hash": _short_hash(str(path)) if path else "",
        }

    def build_tag_signature(self, media_asset: Any) -> dict[str, Any]:
        """Тег-сигнатура (нормализованные теги + сводная подпись)."""
        tags = getattr(media_asset, "tags", None) or {}
        products = sorted({_norm(t) for t in (tags.get("products") or []) if str(t).strip()})
        technologies = sorted(
            {_norm(t) for t in (tags.get("technologies") or []) if str(t).strip()}
        )
        categories = sorted({_norm(t) for t in (tags.get("categories") or []) if str(t).strip()})
        all_tags = {
            _norm(v) for group in _TAG_GROUPS for v in (tags.get(group) or []) if str(v).strip()
        }
        return {
            "products": products,
            "technologies": technologies,
            "categories": categories,
            "signature": "|".join(sorted(all_tags)),
            "tag_count": len(all_tags),
        }

    def fingerprint_result_to_public(
        self, result: dict[str, Any], row: Any | None = None
    ) -> dict[str, Any]:
        """Безопасный публичный вид fingerprint (без raw bytes/путей/имён файлов/секретов)."""
        return {
            "id": getattr(row, "id", None),
            "project_id": result.get("project_id"),
            "media_asset_id": result.get("media_asset_id"),
            "media_asset_variant_id": result.get("_variant_id"),
            "status": result.get("status"),
            "source": result.get("source"),
            "file_sha256_prefix": (result.get("file_sha256") or "")[:16] or None,
            "perceptual_hash": result.get("perceptual_hash"),
            "average_hash": result.get("average_hash"),
            "difference_hash": result.get("difference_hash"),
            "color_signature": result.get("color_signature") or {},
            "dimension_signature": result.get("dimension_signature") or {},
            "metadata_signature": result.get("metadata_signature") or {},
            "tag_signature": result.get("tag_signature") or {},
            "calculated_at": (
                row.calculated_at.isoformat()
                if row is not None and getattr(row, "calculated_at", None)
                else None
            ),
        }

    def snapshot_view(self, row: Any) -> dict[str, Any]:
        """Публичный вид сохранённого fingerprint (из строки БД)."""
        return {
            "id": row.id,
            "project_id": row.project_id,
            "media_asset_id": row.media_asset_id,
            "media_asset_variant_id": row.media_asset_variant_id,
            "status": row.status,
            "source": row.source,
            "file_sha256_prefix": (row.file_sha256 or "")[:16] or None,
            "perceptual_hash": row.perceptual_hash,
            "average_hash": row.average_hash,
            "difference_hash": row.difference_hash,
            "color_signature": dict(row.color_signature or {}),
            "dimension_signature": dict(row.dimension_signature or {}),
            "metadata_signature": dict(row.metadata_signature or {}),
            "tag_signature": dict(row.tag_signature or {}),
            "calculated_at": row.calculated_at.isoformat() if row.calculated_at else None,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    def _evaluate(self, db: Session, project_id: int, asset: Any) -> dict[str, Any]:
        """Полный расчёт fingerprint: признаки → хэши → сигнатуры → статус."""
        features = self.build_fingerprint_features(db, asset)
        content = features["content"]
        metadata_signature = self.build_metadata_signature(asset)
        tag_signature = self.build_tag_signature(asset)

        file_sha256 = None
        perceptual = average = difference = None
        color_signature: dict[str, Any] = {}
        if content is not None:
            file_sha256 = self.calculate_file_sha256(content)
            phash = self.calculate_perceptual_hash(content, features["file_name"])
            perceptual = phash.get("perceptual_hash") or None
            average = phash.get("average_hash") or None
            difference = phash.get("difference_hash") or None
            color_signature = self.calculate_color_signature(content, features["file_name"])

        if perceptual:
            status = "calculated"
            source = features["source"]
        elif tag_signature["tag_count"] or metadata_signature["name_hash"]:
            # Есть метаданные/теги, но нет визуального хэша → частичный fingerprint.
            status = "partial"
            source = "tags_only" if not content else features["source"]
        else:
            status = "unavailable"
            source = "unavailable"

        return {
            "project_id": project_id,
            "media_asset_id": asset.id,
            "status": status,
            "source": source,
            "file_sha256": file_sha256,
            "perceptual_hash": perceptual,
            "average_hash": average,
            "difference_hash": difference,
            "color_signature": color_signature,
            "dimension_signature": features["dimension_signature"],
            "metadata_signature": metadata_signature,
            "tag_signature": tag_signature,
            "fingerprint_metadata": {
                "media_kind": features["media_kind"],
                "extension": features["extension"],
                "has_local_bytes": content is not None,
                "pil_available": _PIL_AVAILABLE,
            },
            "_variant_id": features["variant_id"],
        }

    @staticmethod
    def _read_local_bytes(path: str) -> bytes | None:
        """Безопасно прочитать локальный файл варианта (guarded; без сети). None при сбое."""
        try:
            import os

            if not path or not os.path.isfile(path):
                return None
            if os.path.getsize(path) > _MAX_LOCAL_BYTES:
                return None
            with open(path, "rb") as fh:
                return fh.read()
        except Exception:  # noqa: BLE001 — недоступность файла не должна ронять расчёт
            return None

    @staticmethod
    def _account_id(db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        if project is None:
            raise MediaFingerprintError(f"Проект id={project_id} не найден")
        return project.account_id

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _max_per_run(self) -> int:
        return int(self._resolve_settings().media_fingerprinting_max_assets_per_run_safe)

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
            entity_type="media_fingerprint",
            metadata=metadata,
        )


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def get_media_fingerprint_service() -> MediaFingerprintService:
    """DI-фабрика сервиса fingerprint медиа."""
    return MediaFingerprintService()
