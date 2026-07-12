"""Похожесть медиа и кластеры дублей (visual dedup) — v0.4.7.

Сравнивает fingerprint медиа ВНУТРИ проекта (sha256 / perceptual hash / hamming-дистанция /
подпись тегов / хэш имени/пути) и группирует похожие/дублирующиеся медиа в кластеры с
canonical-ассетом. Без внешнего AI/vision, без сети, без удаления файлов.

БЕЗОПАСНОСТЬ:
- сравнение строго в пределах одного проекта (без межклиентского смешивания);
- в ответах нет секретов, raw bytes и внутренних путей (только хэши/сигнатуры);
- авто-скрытие/удаление дублей выключено по умолчанию.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.repositories import (
    media_asset_repository,
    media_duplicate_cluster_repository,
    media_fingerprint_repository,
    media_quality_repository,
    project_repository,
)
from app.services import audit_log_service as audit_actions

if TYPE_CHECKING:
    from app.config import Settings
    from app.services.audit_log_service import AuditLogService

logger = get_logger(__name__)

_USABLE_STATUSES = ("approved", "approved_video")


class MediaSimilarityService:
    """Сравнение fingerprint и построение кластеров дублей (в пределах проекта, без AI)."""

    def __init__(
        self,
        audit_service: AuditLogService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._audit = audit_service
        self._settings = settings

    # ------------------------------------------------------------------ #
    # 1-2. Сравнение fingerprint                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def hamming_distance(hash_a: str | None, hash_b: str | None) -> int:
        """Hamming-дистанция двух hex-хэшей (число различающихся бит). 64 при несопоставимости."""
        if not hash_a or not hash_b:
            return 64
        try:
            return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")
        except (ValueError, TypeError):
            return 64

    def compare_fingerprints(self, left: Any, right: Any) -> dict[str, Any]:
        """Сравнить два fingerprint. Возвращает score/type/reasons/подскоры/hash_distance/risk."""
        lsha, rsha = _get(left, "file_sha256"), _get(right, "file_sha256")
        lmeta, rmeta = (
            _get(left, "metadata_signature") or {},
            _get(right, "metadata_signature") or {},
        )
        ltag, rtag = _get(left, "tag_signature") or {}, _get(right, "tag_signature") or {}
        lavg, ravg = _get(left, "average_hash"), _get(right, "average_hash")
        ldh, rdh = _get(left, "difference_hash"), _get(right, "difference_hash")

        # Визуальный подскор: минимальная hamming-дистанция по average/difference hash.
        dists: list[int] = []
        if lavg and ravg:
            dists.append(self.hamming_distance(lavg, ravg))
        if ldh and rdh:
            dists.append(self.hamming_distance(ldh, rdh))
        hash_distance = min(dists) if dists else None
        near = self._near_distance()
        visual_score = 0.0
        if hash_distance is not None:
            if hash_distance <= 2:
                visual_score = 0.95
            elif hash_distance <= near:
                visual_score = 0.85
            else:
                visual_score = max(0.0, round(1.0 - hash_distance / 16.0, 3))

        # Тег-подскор: Jaccard подписей тегов.
        lset = {t for t in (ltag.get("signature") or "").split("|") if t}
        rset = {t for t in (rtag.get("signature") or "").split("|") if t}
        tag_score = round(len(lset & rset) / len(lset | rset), 3) if (lset or rset) else 0.0

        # Метаданные: совпадение хэша имени/базового имени/пути.
        same_name = bool(lmeta.get("name_hash")) and lmeta.get("name_hash") == rmeta.get(
            "name_hash"
        )
        same_base = bool(lmeta.get("base_name_hash")) and lmeta.get("base_name_hash") == rmeta.get(
            "base_name_hash"
        )
        same_path = bool(lmeta.get("yandex_path_hash")) and lmeta.get(
            "yandex_path_hash"
        ) == rmeta.get("yandex_path_hash")
        metadata_score = 1.0 if same_path else (0.7 if same_name else (0.4 if same_base else 0.0))

        reasons: list[str] = []
        risk_flags: list[str] = []

        # Точные дубли (байты / путь хранилища) — score 1.0.
        if lsha and rsha and lsha == rsha:
            return self._result(
                1.0,
                "exact_duplicate",
                ["Одинаковый file hash — точный дубль байтов."],
                1.0,
                tag_score,
                metadata_score,
                hash_distance,
                ["exact_duplicate"],
            )
        if same_path:
            return self._result(
                1.0,
                "same_yandex_path",
                ["Одинаковый путь хранилища — один и тот же файл."],
                visual_score,
                tag_score,
                1.0,
                hash_distance,
                ["exact_duplicate"],
            )

        # HEIC/JPEG-пара одного изображения (то же базовое имя, разные расширения).
        if same_base and lmeta.get("extension") != rmeta.get("extension"):
            reasons.append("Одно изображение в разных форматах (HEIC/JPEG).")
            sim_type = "heic_jpeg_pair"
            combined = max(0.9, visual_score, self._combine(visual_score, tag_score))
            if hash_distance is not None:
                reasons.append(f"Hash-дистанция {hash_distance}.")
            return self._result(
                round(min(1.0, combined), 3),
                sim_type,
                reasons,
                visual_score,
                tag_score,
                metadata_score,
                hash_distance,
                risk_flags,
            )

        # Сильный визуальный сигнал доминирует; иначе — взвешенное смешение visual+tag.
        combined = max(visual_score, self._combine(visual_score, tag_score))

        # Классификация по визуальной похожести/имени/тегам.
        if visual_score >= 0.95:
            sim_type = "near_duplicate"
            reasons.append("Почти одинаковый perceptual hash.")
        elif visual_score >= 0.85:
            sim_type = "visually_similar"
            reasons.append(f"Малая hash-дистанция ({hash_distance}) — визуально похожи.")
        elif same_name and tag_score >= 0.5:
            sim_type = "near_duplicate"
            reasons.append("Одинаковое имя файла и совпадение тегов.")
            combined = max(combined, 0.82)
        elif same_name:
            sim_type = "same_file_name"
            reasons.append("Одинаковое нормализованное имя файла.")
            combined = max(combined, 0.6)
        elif tag_score >= 0.99:
            sim_type = "same_series"
            reasons.append("Одинаковая подпись тегов — однотипная серия.")
            combined = max(combined, 0.6)
        elif tag_score > 0:
            sim_type = "same_tag_signature"
            reasons.append("Частичное совпадение тегов.")
        else:
            sim_type = "unknown"

        score = round(min(1.0, combined), 3)
        if score < self._cluster_min_score() and sim_type not in (
            "same_series",
            "same_tag_signature",
        ):
            risk_flags.append("weak_similarity")
        return self._result(
            score,
            sim_type,
            reasons,
            visual_score,
            tag_score,
            metadata_score,
            hash_distance,
            risk_flags,
        )

    @staticmethod
    def explain_similarity(left: Any, right: Any, scores: dict[str, Any]) -> list[str]:
        """Человекочитаемые причины похожести (без путей/имён файлов)."""
        return list(scores.get("reasons", []))[:6]

    # ------------------------------------------------------------------ #
    # 3-4. Кандидаты и кластеры                                           #
    # ------------------------------------------------------------------ #

    def build_similarity_candidates(
        self, db: Session, project_id: int, media_asset_id: int | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Пары похожих медиа в пределах проекта (score выше порога). Без межпроектного."""
        fingerprints = media_fingerprint_repository.latest_per_asset_for_project(db, project_id)[
            : max(1, int(limit))
        ]
        pairs: list[dict[str, Any]] = []
        min_score = self._cluster_min_score()
        for i, left in enumerate(fingerprints):
            if media_asset_id is not None and left.media_asset_id != media_asset_id:
                continue
            for right in fingerprints[i + 1 :]:
                if left.media_asset_id == right.media_asset_id:
                    continue
                cmp = self.compare_fingerprints(left, right)
                if cmp["similarity_score"] >= min_score:
                    pairs.append(
                        {
                            "left_media_asset_id": left.media_asset_id,
                            "right_media_asset_id": right.media_asset_id,
                            "left_fingerprint_id": left.id,
                            "right_fingerprint_id": right.id,
                            **cmp,
                        }
                    )
        pairs.sort(key=lambda p: p["similarity_score"], reverse=True)
        return pairs

    def find_duplicate_clusters(
        self, db: Session, project_id: int, dry_run: bool = True
    ) -> dict[str, Any]:
        """Построить кластеры дублей из fingerprint (union-find по парам). Без удаления файлов."""
        pairs = self.build_similarity_candidates(db, project_id, limit=1000)
        # Union-find по media_asset_id.
        parent: dict[int, int] = {}

        def find(x: int) -> int:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: int, b: int) -> None:
            parent[find(a)] = find(b)

        edge_meta: dict[frozenset[int], dict[str, Any]] = {}
        for pair in pairs:
            a, b = pair["left_media_asset_id"], pair["right_media_asset_id"]
            union(a, b)
            edge_meta[frozenset((a, b))] = pair

        groups: dict[int, list[int]] = {}
        for asset_id in list(parent.keys()):
            groups.setdefault(find(asset_id), []).append(asset_id)

        created = 0
        previews: list[dict[str, Any]] = []
        for members in groups.values():
            if len(members) < 2:
                continue
            member_ids = sorted(set(members))
            # Собрать причины/тип/score по рёбрам внутри кластера.
            edges = [edge_meta[k] for k in edge_meta if k <= set(member_ids)]
            best = max(edges, key=lambda e: e["similarity_score"]) if edges else {}
            cluster_type = best.get("similarity_type", "unknown")
            similarity = (
                round(sum(e["similarity_score"] for e in edges) / len(edges), 3) if edges else 0.0
            )
            reasons = list(dict.fromkeys(r for e in edges for r in (e.get("reasons") or [])))[:6]
            canonical = self.choose_canonical_media(db, project_id, member_ids)
            fp_ids = self._fingerprint_ids_for(db, project_id, member_ids)
            actions = self._recommend_actions(cluster_type, member_ids, canonical)
            view = {
                "cluster_type": cluster_type,
                "canonical_media_asset_id": canonical,
                "member_media_asset_ids": member_ids,
                "member_fingerprint_ids": fp_ids,
                "similarity_score": similarity,
                "reasons": reasons,
                "recommended_actions": actions,
            }
            if not dry_run:
                account_id = self._account_id(db, project_id)
                row = media_duplicate_cluster_repository.create_cluster(
                    db,
                    account_id=account_id,
                    project_id=project_id,
                    status="active",
                    cluster_type=cluster_type,
                    canonical_media_asset_id=canonical,
                    member_media_asset_ids=member_ids,
                    member_fingerprint_ids=fp_ids,
                    similarity_score=similarity,
                    reasons=reasons,
                    recommended_actions=actions,
                    cluster_metadata={"member_count": len(member_ids)},
                )
                created += 1
                view["id"] = row.id
                self._write_audit(
                    db,
                    project_id,
                    audit_actions.ACTION_MEDIA_DUPLICATE_CLUSTER_CREATED,
                    {
                        "cluster_id": row.id,
                        "cluster_type": cluster_type,
                        "similarity_score": similarity,
                        "member_count": len(member_ids),
                    },
                )
            previews.append(view)
        if dry_run:
            self._write_audit(
                db,
                project_id,
                audit_actions.ACTION_MEDIA_DUPLICATE_PREVIEWED,
                {"clusters": len(previews), "dry_run": True},
            )
        return {
            "project_id": project_id,
            "dry_run": dry_run,
            "clusters_found": len(previews),
            "clusters_created": created,
            "clusters": previews[:50],
        }

    # ------------------------------------------------------------------ #
    # 5-6. Canonical и объяснения                                         #
    # ------------------------------------------------------------------ #

    def choose_canonical_media(
        self, db: Session, project_id: int, member_ids: list[int]
    ) -> int | None:
        """Выбрать canonical: approved > качество > теги > не недавнее > меньший id."""
        best: tuple[Any, ...] | None = None
        best_id: int | None = None
        for asset_id in member_ids:
            asset = media_asset_repository.get_media_asset_by_id(db, asset_id)
            if asset is None or asset.project_id != project_id:
                continue
            approved = 1 if asset.status in _USABLE_STATUSES else 0
            snap = media_quality_repository.get_latest_for_asset(db, project_id, asset_id)
            quality = snap.overall_score if snap and snap.overall_score is not None else 0
            tag_count = sum(
                len(v or []) for v in (asset.tags or {}).values() if isinstance(v, list)
            )
            not_recent = 0 if getattr(asset, "last_used_at", None) else 1
            # Больше — лучше; id меньше — лучше (поэтому -asset_id).
            key = (approved, quality, tag_count, not_recent, -asset_id)
            if best is None or key > best:
                best = key
                best_id = asset_id
        return best_id

    # ------------------------------------------------------------------ #
    # 7. Дашборд                                                          #
    # ------------------------------------------------------------------ #

    def build_duplicate_dashboard(self, db: Session, project_id: int) -> dict[str, Any]:
        """Сводка fingerprint и кластеров дублей проекта для UI."""
        fingerprints = media_fingerprint_repository.list_for_project(db, project_id, limit=2000)
        clusters = media_duplicate_cluster_repository.list_for_project(db, project_id, limit=500)
        by_type: dict[str, int] = {}
        exact = near = series = 0
        active = reviewed = 0
        for cluster in clusters:
            by_type[cluster.cluster_type] = by_type.get(cluster.cluster_type, 0) + 1
            if cluster.cluster_type == "exact_duplicate":
                exact += 1
            elif cluster.cluster_type in ("near_duplicate", "visually_similar", "heic_jpeg_pair"):
                near += 1
            elif cluster.cluster_type in ("same_series", "same_tag_signature"):
                series += 1
            if cluster.status == "active":
                active += 1
            elif cluster.status == "reviewed":
                reviewed += 1
        return {
            "project_id": project_id,
            "total_fingerprints": len(fingerprints),
            "exact_duplicates": exact,
            "near_duplicates": near,
            "same_series": series,
            "active_clusters": active,
            "reviewed_clusters": reviewed,
            "cluster_types": sorted(by_type.items(), key=lambda kv: kv[1], reverse=True),
            "worker_enabled": self._worker_enabled(),
        }

    # ------------------------------------------------------------------ #
    # Внутреннее                                                          #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _recommend_actions(
        cluster_type: str, member_ids: list[int], canonical: int | None
    ) -> list[str]:
        actions: list[str] = ["keep_canonical"]
        if cluster_type in (
            "exact_duplicate",
            "near_duplicate",
            "same_yandex_path",
            "heic_jpeg_pair",
        ):
            actions.append("hide_duplicate")
            actions.append("replace_in_schedule")
        if cluster_type in ("same_series", "same_tag_signature"):
            actions.append("merge_series")
        if cluster_type in ("same_tag_signature",):
            actions.append("retag_duplicate")
        actions.append("needs_review")
        return list(dict.fromkeys(actions))

    def _fingerprint_ids_for(
        self, db: Session, project_id: int, member_ids: list[int]
    ) -> list[int]:
        out: list[int] = []
        for asset_id in member_ids:
            fp = media_fingerprint_repository.get_latest_for_asset(db, project_id, asset_id)
            if fp is not None:
                out.append(fp.id)
        return out

    @staticmethod
    def _result(
        score: float,
        sim_type: str,
        reasons: list[str],
        visual_score: float,
        tag_score: float,
        metadata_score: float,
        hash_distance: int | None,
        risk_flags: list[str],
    ) -> dict[str, Any]:
        return {
            "similarity_score": round(float(score), 3),
            "similarity_type": sim_type,
            "reasons": reasons,
            "visual_score": round(float(visual_score), 3),
            "tag_score": round(float(tag_score), 3),
            "metadata_score": round(float(metadata_score), 3),
            "hash_distance": hash_distance,
            "risk_flags": risk_flags,
        }

    def _combine(self, visual_score: float, tag_score: float) -> float:
        return self._visual_weight() * visual_score + self._tag_weight() * tag_score

    def _account_id(self, db: Session, project_id: int) -> int | None:
        project = project_repository.get_project_by_id(db, project_id)
        return project.account_id if project is not None else None

    def _resolve_settings(self) -> Any:
        if self._settings is None:
            from app.config import get_settings

            self._settings = get_settings()
        return self._settings

    def _near_distance(self) -> int:
        return int(self._resolve_settings().media_similarity_near_hash_distance_safe)

    def _cluster_min_score(self) -> float:
        return float(self._resolve_settings().media_duplicate_cluster_min_score_safe)

    def _tag_weight(self) -> float:
        return float(getattr(self._resolve_settings(), "media_similarity_tag_weight", 0.2))

    def _visual_weight(self) -> float:
        return float(getattr(self._resolve_settings(), "media_similarity_visual_weight", 0.8))

    def _worker_enabled(self) -> bool:
        return bool(self._resolve_settings().media_fingerprinting_worker_enabled_effective)

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
            entity_type="media_duplicate_cluster",
            metadata=metadata,
        )


def _get(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def get_media_similarity_service() -> MediaSimilarityService:
    """DI-фабрика сервиса похожести/дедупликации медиа."""
    return MediaSimilarityService()
