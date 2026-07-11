"""Нормализация метрик разных платформ в единый формат Botfleet (v0.4.1).

Telegram/VK/Instagram называют метрики по-разному — сервис приводит их к единому
:class:`NormalizedPostMetrics`. Чистый сервис (без БД/сети/AI).

ПРАВИЛА:
- если метрика неизвестна — ``None`` (а НЕ 0);
- ER считается от reach → impressions → views (fallback);
- CTR требует impressions (иначе None);
- ``raw_sanitized`` не содержит токенов/секретов;
- всегда сохраняется ``source`` и ``confidence_score`` (api > manual > internal >
  estimated > demo).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Порядок доверия к источнику метрик (выше — надёжнее). Используется в обучении.
SOURCE_CONFIDENCE: dict[str, float] = {
    "api": 1.0,
    "manual": 0.8,
    "internal": 0.6,
    "estimated": 0.4,
    "demo": 0.2,
}
METRIC_SOURCES: tuple[str, ...] = ("internal", "manual", "estimated", "api", "demo")

# Ключи, похожие на секреты — вырезаются из raw_sanitized.
_SECRET_HINTS = ("token", "secret", "password", "api_key", "access", "cookie", "auth", "key")

# Целочисленные метрики единого формата Botfleet.
_INT_FIELDS = (
    "views",
    "reach",
    "impressions",
    "likes",
    "comments",
    "shares",
    "reposts",
    "saves",
    "clicks",
    "followers_delta",
)


@dataclass
class NormalizedPostMetrics:
    """Единый формат метрик поста Botfleet (None = метрика неизвестна)."""

    views: int | None = None
    reach: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    reposts: int | None = None
    saves: int | None = None
    clicks: int | None = None
    followers_delta: int | None = None
    er_percent: float | None = None
    ctr_percent: float | None = None
    engagement_per_1000: float | None = None
    source: str = "manual"
    confidence_score: float = 0.0
    raw_sanitized: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def snapshot_metrics(self) -> dict[str, int]:
        """Целочисленные метрики для PostAnalyticsSnapshot (None → 0 только для хранения)."""
        return {
            "impressions": int(self.impressions or 0),
            "reach": int(self.reach or 0),
            "views": int(self.views or 0),
            "likes": int(self.likes or 0),
            "comments": int(self.comments or 0),
            "shares": int(self.shares or self.reposts or 0),
            "saves": int(self.saves or 0),
            "clicks": int(self.clicks or 0),
        }


class MetricsNormalizationService:
    """Приведение сырых метрик платформ к единому формату + расчёт ER/CTR."""

    # --- Публичное API ---

    def normalize_platform_metrics(
        self, platform_key: str | None, raw_metrics: dict[str, Any], source: str
    ) -> NormalizedPostMetrics:
        """Нормализовать сырые метрики площадки в единый формат."""
        platform = (platform_key or "").strip().lower()
        raw = raw_metrics or {}
        if platform == "telegram":
            mapped = self._map_telegram(raw)
        elif platform == "vk":
            mapped = self._map_vk(raw)
        elif platform == "instagram":
            mapped = self._map_instagram(raw)
        else:
            mapped = self._map_generic(raw)

        metrics = NormalizedPostMetrics(
            source=source if source in METRIC_SOURCES else "manual",
            confidence_score=SOURCE_CONFIDENCE.get(source, 0.2),
            raw_sanitized=self.sanitize_raw(raw),
        )
        for key in _INT_FIELDS:
            setattr(metrics, key, mapped.get(key))
        metrics.er_percent = self.calculate_er(mapped)
        metrics.ctr_percent = self.calculate_ctr(mapped)
        metrics.engagement_per_1000 = self.calculate_engagement_per_1000(mapped)
        return metrics

    def calculate_er(self, metrics: dict[str, Any]) -> float | None:
        """ER (%) = вовлечения / база (reach → impressions → views). None если базы нет."""
        base = self._first_positive(
            metrics.get("reach"), metrics.get("impressions"), metrics.get("views")
        )
        if base is None:
            return None
        engagements = self._engagements(metrics)
        if engagements is None:
            return None
        return round(engagements / base * 100, 3)

    def calculate_ctr(self, metrics: dict[str, Any]) -> float | None:
        """CTR (%) = clicks / impressions. Требует impressions (иначе None)."""
        impressions = self._as_int(metrics.get("impressions"))
        clicks = self._as_int(metrics.get("clicks"))
        if impressions is None or impressions <= 0 or clicks is None:
            return None
        return round(clicks / impressions * 100, 3)

    def calculate_engagement_per_1000(self, metrics: dict[str, Any]) -> float | None:
        """Вовлечения на 1000 показов (по reach → impressions → views)."""
        base = self._first_positive(
            metrics.get("reach"), metrics.get("impressions"), metrics.get("views")
        )
        engagements = self._engagements(metrics)
        if base is None or engagements is None:
            return None
        return round(engagements / base * 1000, 2)

    def calculate_actual_engagement_score(self, metrics: dict[str, Any]) -> int:
        """Фактическая оценка вовлечения 0..100 из ER + saves/shares-бонуса."""
        er = self.calculate_er(metrics)
        score = 0.0
        if er is not None:
            # ER 0..15% → 0..80 баллов (насыщение).
            score += min(80.0, er / 15.0 * 80.0)
        saves = self._as_int(metrics.get("saves")) or 0
        shares = self._as_int(metrics.get("shares")) or self._as_int(metrics.get("reposts")) or 0
        base = self._first_positive(
            metrics.get("reach"), metrics.get("impressions"), metrics.get("views")
        )
        if base:
            useful = (saves + shares) / base * 100
            score += min(20.0, useful * 4)  # «полезный» контент (сохранения/репосты)
        return int(max(0, min(100, round(score))))

    def merge_metrics(
        self,
        existing: dict[str, Any] | None,
        incoming: dict[str, Any] | None,
        priority_order: tuple[str, ...] = ("api", "manual", "internal", "estimated", "demo"),
    ) -> dict[str, Any]:
        """Слить метрики: значение от более доверенного источника не перетирается менее доверенным.

        ``existing``/``incoming`` — dict с ключами метрик и обязательным ``source``.
        None-значения не перетирают известные значения.
        """
        existing = dict(existing or {})
        incoming = dict(incoming or {})
        ex_src = str(existing.get("source", "demo"))
        in_src = str(incoming.get("source", "demo"))
        ex_rank = priority_order.index(ex_src) if ex_src in priority_order else len(priority_order)
        in_rank = priority_order.index(in_src) if in_src in priority_order else len(priority_order)
        # Меньший индекс = выше приоритет. Побеждает более доверенный источник.
        primary, secondary = (incoming, existing) if in_rank <= ex_rank else (existing, incoming)
        merged: dict[str, Any] = {}
        keys = set(existing) | set(incoming)
        for key in keys:
            if key == "source":
                continue
            pv = primary.get(key)
            merged[key] = pv if pv is not None else secondary.get(key)
        merged["source"] = primary.get("source", secondary.get("source"))
        return merged

    def build_metrics_quality(self, metrics: dict[str, Any], source: str) -> dict[str, Any]:
        """Оценка полноты/доверия к метрикам: сколько полей известно + confidence."""
        known = sum(1 for key in _INT_FIELDS if self._as_int(metrics.get(key)) is not None)
        completeness = round(known / len(_INT_FIELDS), 3)
        return {
            "source": source,
            "confidence_score": SOURCE_CONFIDENCE.get(source, 0.2),
            "known_fields": known,
            "total_fields": len(_INT_FIELDS),
            "completeness": completeness,
            "has_reach": self._as_int(metrics.get("reach")) is not None,
            "has_impressions": self._as_int(metrics.get("impressions")) is not None,
        }

    def sanitize_raw(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Убрать из сырых метрик любые токен-подобные ключи (без секретов).

        Рекурсивно чистит вложенные dict и списки — секрет в списке словарей тоже
        вырезается (не стрингифицируется целиком).
        """
        clean: dict[str, Any] = {}
        for key, value in (raw or {}).items():
            lowered = str(key).lower()
            if any(hint in lowered for hint in _SECRET_HINTS):
                continue
            clean[key] = self._sanitize_value(value)
        return clean

    def _sanitize_value(self, value: Any) -> Any:
        """Очистить одно значение (dict → рекурсия по ключам; list → поэлементно)."""
        if isinstance(value, dict):
            return self.sanitize_raw(value)
        if isinstance(value, (list, tuple)):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, (int, float, str, bool)) or value is None:
            return value
        return str(value)

    # --- Маппинг платформ ---

    def _map_telegram(self, raw: dict[str, Any]) -> dict[str, int | None]:
        """Telegram: forwards → shares/reposts; views → views/impressions при отсутствии reach."""
        views = self._pick(raw, "views", "view_count")
        forwards = self._pick(raw, "forwards", "forward_count")
        return {
            "views": views,
            "impressions": self._pick(raw, "impressions") or views,
            "reach": self._pick(raw, "reach"),
            "likes": self._pick(raw, "likes", "reactions"),
            "comments": self._pick(raw, "comments", "replies"),
            "shares": forwards,
            "reposts": forwards,
            "saves": self._pick(raw, "saves"),
            "clicks": self._pick(raw, "clicks", "link_clicks"),
            "followers_delta": self._pick(raw, "followers_delta", "subscribers_delta"),
        }

    def _map_vk(self, raw: dict[str, Any]) -> dict[str, int | None]:
        """VK: reposts → shares/reposts; views/impressions/reach если есть."""
        reposts = self._pick(raw, "reposts", "reposts_count")
        return {
            "views": self._pick(raw, "views", "views_count"),
            "impressions": self._pick(raw, "impressions"),
            "reach": self._pick(raw, "reach", "reach_total", "reach_subscribers"),
            "likes": self._pick(raw, "likes", "likes_count"),
            "comments": self._pick(raw, "comments", "comments_count"),
            "shares": reposts,
            "reposts": reposts,
            "saves": self._pick(raw, "saves"),
            "clicks": self._pick(raw, "clicks", "links"),
            "followers_delta": self._pick(raw, "followers_delta", "members_delta"),
        }

    def _map_instagram(self, raw: dict[str, Any]) -> dict[str, int | None]:
        """Instagram: impressions/reach/saves/profile_actions/clicks если есть."""
        return {
            "views": self._pick(raw, "views", "video_views", "plays"),
            "impressions": self._pick(raw, "impressions"),
            "reach": self._pick(raw, "reach"),
            "likes": self._pick(raw, "likes", "like_count"),
            "comments": self._pick(raw, "comments", "comments_count"),
            "shares": self._pick(raw, "shares"),
            "reposts": self._pick(raw, "shares"),
            "saves": self._pick(raw, "saves", "saved"),
            "clicks": self._pick(raw, "clicks", "website_clicks", "profile_actions"),
            "followers_delta": self._pick(raw, "followers_delta", "follows"),
        }

    def _map_generic(self, raw: dict[str, Any]) -> dict[str, int | None]:
        """Общий маппинг (manual/estimated/internal): прямые ключи Botfleet."""
        out: dict[str, int | None] = {key: self._pick(raw, key) for key in _INT_FIELDS}
        if out.get("shares") is None and raw.get("reposts") is not None:
            out["shares"] = self._as_int(raw.get("reposts"))
        if out.get("reposts") is None and raw.get("shares") is not None:
            out["reposts"] = self._as_int(raw.get("shares"))
        return out

    # --- Утилиты ---

    def _engagements(self, metrics: dict[str, Any]) -> int | None:
        """Сумма вовлечений (likes+comments+shares/reposts+saves). None если все неизвестны."""
        parts = [
            self._as_int(metrics.get("likes")),
            self._as_int(metrics.get("comments")),
            self._as_int(metrics.get("shares")) or self._as_int(metrics.get("reposts")),
            self._as_int(metrics.get("saves")),
        ]
        known = [p for p in parts if p is not None]
        if not known:
            return None
        return sum(known)

    @staticmethod
    def _pick(raw: dict[str, Any], *keys: str) -> int | None:
        for key in keys:
            if key in raw and raw[key] is not None:
                value = MetricsNormalizationService._as_int(raw[key])
                if value is not None:
                    return value
        return None

    @staticmethod
    def _first_positive(*values: Any) -> int | None:
        for value in values:
            iv = MetricsNormalizationService._as_int(value)
            if iv is not None and iv > 0:
                return iv
        return None

    @staticmethod
    def _as_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None


def get_metrics_normalization_service() -> MetricsNormalizationService:
    """DI-фабрика сервиса нормализации метрик."""
    return MetricsNormalizationService()
