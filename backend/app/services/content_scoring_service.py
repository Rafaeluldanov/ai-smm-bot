"""Оценка контента поста относительно профиля обучения клиента (v0.4.0).

Чистый сервис (без БД/сети/AI): извлекает признаки текста и считает эвристические
оценки качества / прогнозируемого вовлечения / соответствия профилю. Используется:
- в :class:`ScheduleAutomationService` при генерации по расписанию (gate авто-режима);
- в review UI (карточка поста);
- в :class:`ClientLearningService` (score_content_candidate).

Оценки — это НЕ дообучение модели, а безопасный per-client слой эвристик поверх
собранного профиля. Все числа клампятся в [0..100].
"""

from __future__ import annotations

import re
from typing import Any

# Маркеры призыва к действию (CTA) и тона.
_CTA_MARKERS = (
    "закажи",
    "заказать",
    "купи",
    "купить",
    "оставь",
    "оставить заявку",
    "звони",
    "позвони",
    "пиши",
    "напиши",
    "переходи",
    "подпис",
    "жми",
    "успей",
    "получи",
    "забронир",
    "оформи",
    "узнай",
    "регистрируй",
    "скидка",
    "акци",
)
_QUESTION_MARKERS = ("?",)
_TONE_FRIENDLY = ("друзья", "привет", "давайте", "вместе", "рады", "любим", "😊", "🙌", "🔥", "❤")
_TONE_FORMAL = ("уважаемые", "компания", "предлагаем", "сообщаем", "гарантируем")
_URL_RE = re.compile(r"https?://|\bt\.me/|\bvk\.com/|\bwa\.me/", re.IGNORECASE)
_HASHTAG_RE = re.compile(r"#\w+", re.UNICODE)
_NUMBER_RE = re.compile(r"\d")

# Ориентиры «здоровой» длины текста поста (символы).
_MIN_HEALTHY_LEN = 120
_MAX_HEALTHY_LEN = 1200


def _clamp_score(value: float) -> int:
    """Ограничить оценку в [0..100] и округлить до int."""
    return int(max(0, min(100, round(value))))


class ContentScoringService:
    """Эвристическая оценка текста поста и соответствия профилю клиента."""

    def analyze_text_features(self, text: str | None) -> dict[str, Any]:
        """Извлечь признаки текста: длина, CTA, ссылка, хэштеги, числа, вопрос, тон."""
        text = text or ""
        stripped = text.strip()
        lowered = stripped.lower()
        hashtags = _HASHTAG_RE.findall(stripped)
        has_cta = any(marker in lowered for marker in _CTA_MARKERS)
        has_link = bool(_URL_RE.search(stripped))
        has_numbers = bool(_NUMBER_RE.search(stripped))
        has_question = any(marker in stripped for marker in _QUESTION_MARKERS)
        tone_markers: list[str] = []
        if any(marker in lowered for marker in _TONE_FRIENDLY):
            tone_markers.append("friendly")
        if any(marker in lowered for marker in _TONE_FORMAL):
            tone_markers.append("formal")
        return {
            "length": len(stripped),
            "word_count": len(stripped.split()),
            "has_cta": has_cta,
            "has_link": has_link,
            "hashtags_count": len(hashtags),
            "has_numbers": has_numbers,
            "has_question": has_question,
            "tone_markers": tone_markers,
        }

    # --- Оценка относительно профиля ---

    def score_post_against_profile(self, post: Any, profile: Any | None = None) -> dict[str, Any]:
        """Вернуть {quality_score, predicted_engagement_score, fit_score, reasons, warnings}.

        ``post`` — ORM ``Post`` или объект с полями текста/хэштегов; ``profile`` —
        ``ClientLearningProfile`` или None (тогда fit нейтрален).
        """
        text = self._primary_text(post)
        features = self.analyze_text_features(text)
        hashtags = self._hashtags(post)

        quality, q_reasons, q_warnings = self._quality(features, hashtags)
        engagement, e_reasons = self._engagement(features, hashtags)
        fit, f_reasons, f_warnings = self._fit_to_profile(features, hashtags, post, profile)

        reasons = q_reasons + e_reasons + f_reasons
        warnings = q_warnings + f_warnings
        return {
            "quality_score": _clamp_score(quality),
            "predicted_engagement_score": _clamp_score(engagement),
            "fit_score": _clamp_score(fit),
            "features": features,
            "reasons": reasons,
            "warnings": warnings,
        }

    def recommend_post_improvements(self, post: Any, profile: Any | None = None) -> list[str]:
        """Список конкретных рекомендаций по улучшению поста."""
        text = self._primary_text(post)
        features = self.analyze_text_features(text)
        hashtags = self._hashtags(post)
        recs: list[str] = []
        if features["length"] < _MIN_HEALTHY_LEN:
            recs.append("Добавьте конкретики: текст короткий, раскройте выгоду и детали.")
        if features["length"] > _MAX_HEALTHY_LEN:
            recs.append("Сократите текст — он слишком длинный для соцсети.")
        if not features["has_cta"]:
            recs.append("Добавьте призыв к действию (CTA): что сделать читателю дальше.")
        if not features["has_numbers"]:
            recs.append("Добавьте цифры/факты (цена, сроки, гарантия) — это повышает доверие.")
        if features["hashtags_count"] == 0:
            recs.append("Добавьте 2–5 релевантных хэштегов для охвата.")
        if features["hashtags_count"] > 12:
            recs.append("Уберите лишние хэштеги — их слишком много.")
        if profile is not None:
            preferred_cta = _as_str_list(getattr(profile, "preferred_cta", []))
            if preferred_cta and not features["has_cta"]:
                recs.append(f"Используйте рабочий CTA клиента: «{preferred_cta[0]}».")
            high_tags = _as_str_list(getattr(profile, "high_performing_tags", []))
            low_tags = set(_as_str_list(getattr(profile, "low_performing_tags", [])))
            post_tags = {t.lower().lstrip("#") for t in hashtags}
            if high_tags and not (post_tags & {t.lower().lstrip("#") for t in high_tags}):
                recs.append(f"Добавьте тег, который хорошо работает: #{high_tags[0].lstrip('#')}.")
            if post_tags & low_tags:
                recs.append("Замените слабые теги — они исторически давали низкий охват.")
        return recs

    # --- Внутренние оценки ---

    @staticmethod
    def _quality(
        features: dict[str, Any], hashtags: list[str]
    ) -> tuple[float, list[str], list[str]]:
        """Базовое качество текста 0..100 (длина/структура/CTA/цифры/теги)."""
        score = 40.0
        reasons: list[str] = []
        warnings: list[str] = []
        length = features["length"]
        if length == 0:
            warnings.append("Пустой текст поста")
            return 0.0, reasons, warnings
        if _MIN_HEALTHY_LEN <= length <= _MAX_HEALTHY_LEN:
            score += 20
            reasons.append("Оптимальная длина текста")
        elif length < _MIN_HEALTHY_LEN:
            score += 5
            warnings.append("Текст слишком короткий")
        else:
            score += 8
            warnings.append("Текст длиннее рекомендуемого")
        if features["has_cta"]:
            score += 15
            reasons.append("Есть призыв к действию")
        else:
            warnings.append("Нет призыва к действию (CTA)")
        if features["has_numbers"]:
            score += 8
            reasons.append("Есть конкретика/цифры")
        if 1 <= features["hashtags_count"] <= 10:
            score += 10
            reasons.append("Разумное число хэштегов")
        elif features["hashtags_count"] > 10:
            warnings.append("Слишком много хэштегов")
        if features["has_link"]:
            score += 4
        if features["has_question"]:
            score += 3
        return score, reasons, warnings

    @staticmethod
    def _engagement(features: dict[str, Any], hashtags: list[str]) -> tuple[float, list[str]]:
        """Прогноз вовлечения 0..100 (вопрос/CTA/эмоц. тон/теги)."""
        score = 45.0
        reasons: list[str] = []
        if features["has_question"]:
            score += 12
            reasons.append("Вопрос вовлекает аудиторию")
        if features["has_cta"]:
            score += 10
        if "friendly" in features["tone_markers"]:
            score += 10
            reasons.append("Дружелюбный тон повышает отклик")
        if 2 <= features["hashtags_count"] <= 8:
            score += 8
        if features["has_numbers"]:
            score += 5
        return score, reasons

    @staticmethod
    def _fit_to_profile(
        features: dict[str, Any],
        hashtags: list[str],
        post: Any,
        profile: Any | None,
    ) -> tuple[float, list[str], list[str]]:
        """Соответствие профилю клиента 0..100 (теги/CTA/длина/запреты)."""
        if profile is None:
            return 60.0, [], []
        score = 60.0
        reasons: list[str] = []
        warnings: list[str] = []
        post_tags = {t.lower().lstrip("#") for t in hashtags}

        high_tags = {
            t.lower().lstrip("#")
            for t in _as_str_list(getattr(profile, "high_performing_tags", []))
        }
        low_tags = {
            t.lower().lstrip("#") for t in _as_str_list(getattr(profile, "low_performing_tags", []))
        }
        if high_tags and (post_tags & high_tags):
            score += 15
            reasons.append("Содержит теги, которые хорошо работают у клиента")
        if low_tags and (post_tags & low_tags):
            score -= 15
            warnings.append("Содержит теги со слабой историей охвата")

        preferred_cta = _as_str_list(getattr(profile, "preferred_cta", []))
        rejected_cta = _as_str_list(getattr(profile, "rejected_cta", []))
        text_lower = (ContentScoringService._primary_text(post) or "").lower()
        if preferred_cta and any(cta.lower() in text_lower for cta in preferred_cta if cta):
            score += 10
            reasons.append("Использован предпочитаемый клиентом CTA")
        if rejected_cta and any(cta.lower() in text_lower for cta in rejected_cta if cta):
            score -= 10
            warnings.append("Использован ранее отклонённый CTA")

        # Предпочтительная длина (если профиль накопил медиану).
        preferred_len = getattr(profile, "preferred_text_length", {}) or {}
        target = preferred_len.get("target") if isinstance(preferred_len, dict) else None
        if isinstance(target, (int, float)) and target > 0:
            delta = abs(features["length"] - target) / max(target, 1)
            if delta <= 0.3:
                score += 8
                reasons.append("Длина близка к предпочтительной клиентом")
            elif delta >= 0.8:
                score -= 6
                warnings.append("Длина далека от предпочтительной клиентом")

        forbidden = _as_str_list(getattr(profile, "forbidden_patterns", []))
        for pattern in forbidden:
            if pattern and pattern.lower() in text_lower:
                score -= 20
                warnings.append(f"Найден запрещённый паттерн: «{pattern}»")
        return score, reasons, warnings

    # --- Утилиты доступа к посту ---

    @staticmethod
    def _primary_text(post: Any) -> str:
        """Основной текст поста (vk → telegram → instagram)."""
        if isinstance(post, dict):
            return str(
                post.get("vk_text")
                or post.get("telegram_text")
                or post.get("instagram_text")
                or post.get("text")
                or ""
            )
        for attr in ("vk_text", "telegram_text", "instagram_text", "text"):
            value = getattr(post, attr, None)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _hashtags(post: Any) -> list[str]:
        """Хэштеги поста списком строк."""
        if isinstance(post, dict):
            raw = post.get("hashtags") or []
        else:
            raw = getattr(post, "hashtags", None) or []
        return _as_str_list(raw)


def _as_str_list(value: Any) -> list[str]:
    """Привести значение к списку непустых строк."""
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    return [str(value)]


def get_content_scoring_service() -> ContentScoringService:
    """DI-фабрика сервиса оценки контента."""
    return ContentScoringService()
