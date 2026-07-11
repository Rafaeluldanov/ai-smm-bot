"""Анализ вариантов эксперимента: скоринг, сравнение, выбор winner (v0.4.2).

Чистый сервис (без БД/сети). Считает взвешенную оценку варианта из реальных метрик и
feedback; при отсутствии метрик — fallback на approval + quality + predicted (с меньшей
уверенностью). Выбирает winner и объясняет решение.
"""

from __future__ import annotations

from typing import Any

# Веса компонентов итоговой оценки варианта.
WEIGHTS = {
    "actual_er": 0.35,
    "actual_ctr": 0.20,
    "client_approval": 0.20,
    "low_edits": 0.10,
    "quality": 0.10,
    "useful": 0.05,
}
# Нормировочные «потолки» (значение, дающее компоненту = 1.0).
_ER_CAP = 15.0  # %
_CTR_CAP = 8.0  # %

# Причина winner по доминирующему сигналу.
_REASON_BY_COMPONENT = {
    "actual_er": "higher_er",
    "actual_ctr": "higher_ctr",
    "client_approval": "client_approved",
    "low_edits": "fewer_edits",
    "quality": "better_quality_score",
    "useful": "better_conversion_signal",
}


class ExperimentAnalysisService:
    """Скоринг и выбор winner среди вариантов эксперимента."""

    def calculate_variant_score(
        self,
        variant: Any,
        metrics: dict[str, Any] | None = None,
        feedback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Взвешенная оценка варианта 0..100 + компоненты + уверенность."""
        metrics = metrics or self._variant_metrics(variant)
        feedback = feedback or {}
        er = _to_float(metrics.get("er_percent"))
        ctr = _to_float(metrics.get("ctr_percent"))
        has_actual = er is not None or ctr is not None

        quality = _to_float(_get(variant, "quality_score")) or 0.0
        predicted = _to_float(_get(variant, "predicted_engagement_score")) or 0.0

        # ER/CTR компоненты: реальные метрики или fallback на predicted.
        er_c = min(er / _ER_CAP, 1.0) if er is not None else predicted / 100.0
        ctr_c = min(ctr / _CTR_CAP, 1.0) if ctr is not None else predicted / 100.0
        approval_c = self._approval_component(feedback)
        low_edit_c = 1.0 / (1.0 + int(feedback.get("edited", 0) or 0)) if feedback else 0.7
        quality_c = min(max(quality / 100.0, 0.0), 1.0)
        useful_c = self._useful_component(metrics)

        components = {
            "actual_er": round(er_c, 4),
            "actual_ctr": round(ctr_c, 4),
            "client_approval": round(approval_c, 4),
            "low_edits": round(low_edit_c, 4),
            "quality": round(quality_c, 4),
            "useful": round(useful_c, 4),
        }
        total = 100.0 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS)
        confidence = 0.8 if has_actual else 0.4
        if feedback.get("approved") or feedback.get("rejected"):
            confidence = min(1.0, confidence + 0.1)
        return {
            "total_score": round(max(0.0, min(100.0, total)), 2),
            "components": components,
            "has_actual_metrics": has_actual,
            "confidence": round(confidence, 3),
            "actual_engagement_score": int(round(er_c * 100)) if er is not None else None,
        }

    def compare_variants(self, variants: list[Any]) -> list[dict[str, Any]]:
        """Отсортированные по итоговой оценке варианты (лучший первым)."""
        scored: list[dict[str, Any]] = []
        for variant in variants:
            result = self.calculate_variant_score(variant, feedback=self._variant_feedback(variant))
            scored.append(
                {
                    "variant_id": _get(variant, "id"),
                    "variant_key": _get(variant, "variant_key"),
                    "score": result["total_score"],
                    "components": result["components"],
                    "has_actual_metrics": result["has_actual_metrics"],
                    "confidence": result["confidence"],
                }
            )
        scored.sort(key=lambda r: r["score"], reverse=True)
        return scored

    def select_winner(self, variants: list[Any]) -> dict[str, Any]:
        """Выбрать winner: лучший по итоговой оценке. Возвращает id/ключ/причину/уверенность."""
        ranked = self.compare_variants(variants)
        if not ranked:
            return {
                "variant_id": None,
                "reason": "manual_selection",
                "confidence": 0.0,
                "ranked": [],
            }
        top = ranked[0]
        reason = self._dominant_reason(top["components"])
        # Уверенность зависит и от отрыва от второго места.
        margin = top["score"] - (ranked[1]["score"] if len(ranked) > 1 else 0.0)
        confidence = round(min(1.0, top["confidence"] * (0.6 + min(margin, 40) / 40 * 0.4)), 3)
        return {
            "variant_id": top["variant_id"],
            "variant_key": top["variant_key"],
            "reason": reason,
            "confidence": confidence,
            "ranked": ranked,
        }

    def explain_winner(self, winner: Any, losers: list[Any]) -> list[str]:
        """Человеко-читаемое объяснение выбора winner."""
        wkey = _get(winner, "variant_key") or "?"
        reasons: list[str] = []
        wer = _to_float(_get(winner, "er_percent"))
        wctr = _to_float(_get(winner, "ctr_percent"))
        wq = _to_float(_get(winner, "quality_score"))
        if wer is not None:
            reasons.append(f"Вариант {wkey}: выше вовлечённость (ER {wer}%).")
        if wctr is not None:
            reasons.append(f"Вариант {wkey}: выше кликабельность (CTR {wctr}%).")
        if wq is not None:
            reasons.append(f"Вариант {wkey}: выше оценка качества ({int(wq)}/100).")
        if not reasons:
            reasons.append(f"Вариант {wkey} выбран по совокупности сигналов (feedback + скоринг).")
        for loser in losers:
            lkey = _get(loser, "variant_key") or "?"
            reasons.append(f"Вариант {lkey} — слабее по итоговой оценке, уходит в слабые сигналы.")
        return reasons

    def build_learning_updates_from_experiment(
        self, winner: Any, losers: list[Any]
    ) -> dict[str, Any]:
        """Какие сигналы обучения применить: winner усиливает, losers ослабляют."""
        return {
            "winner": {
                "cta_type": _get(winner, "cta_type"),
                "angle": _get(winner, "angle"),
                "text_length_type": _get(winner, "text_length_type"),
                "media_strategy": _get(winner, "media_strategy"),
                "publish_time_strategy": _get(winner, "publish_time_strategy"),
            },
            "weak_signals": [
                {"variant_key": _get(v, "variant_key"), "cta_type": _get(v, "cta_type")}
                for v in losers
            ],
        }

    # --- Внутреннее ---

    @staticmethod
    def _approval_component(feedback: dict[str, Any]) -> float:
        approved = int(feedback.get("approved", 0) or 0)
        edited = int(feedback.get("edited", 0) or 0)
        rejected = int(feedback.get("rejected", 0) or 0)
        total = approved + edited + rejected
        if total == 0:
            return 0.4  # нейтрально при отсутствии решений
        return (approved * 1.0 + edited * 0.4) / total

    @staticmethod
    def _useful_component(metrics: dict[str, Any]) -> float:
        reach = _to_float(metrics.get("reach")) or 0.0
        saves = _to_float(metrics.get("saves")) or 0.0
        shares = _to_float(metrics.get("shares")) or _to_float(metrics.get("reposts")) or 0.0
        if reach <= 0:
            return 0.0
        return min((saves + shares) / reach * 20.0, 1.0)

    @staticmethod
    def _dominant_reason(components: dict[str, float]) -> str:
        # Причина по компоненту с наибольшим взвешенным вкладом.
        weighted = {k: WEIGHTS[k] * components.get(k, 0.0) for k in WEIGHTS}
        best = max(weighted, key=lambda k: weighted[k])
        return _REASON_BY_COMPONENT.get(best, "manual_selection")

    @staticmethod
    def _variant_metrics(variant: Any) -> dict[str, Any]:
        snap = _get(variant, "metrics_snapshot") or {}
        merged = dict(snap) if isinstance(snap, dict) else {}
        if _get(variant, "er_percent") is not None:
            merged.setdefault("er_percent", _get(variant, "er_percent"))
        if _get(variant, "ctr_percent") is not None:
            merged.setdefault("ctr_percent", _get(variant, "ctr_percent"))
        return merged

    @staticmethod
    def _variant_feedback(variant: Any) -> dict[str, Any]:
        meta = _get(variant, "variant_metadata") or {}
        fb = meta.get("feedback") if isinstance(meta, dict) else None
        return fb if isinstance(fb, dict) else {}


def _get(obj: Any, field: str) -> Any:
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(field)
    return getattr(obj, field, None)


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_experiment_analysis_service() -> ExperimentAnalysisService:
    """DI-фабрика сервиса анализа экспериментов."""
    return ExperimentAnalysisService()
