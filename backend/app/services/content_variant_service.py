"""Генерация вариантов поста для A/B-теста (v0.4.2, rule-based, без внешнего AI).

Варианты отличаются заголовком/первым абзацем, CTA, длиной, углом и структурой.
Используются существующие тексты, brand tone и предпочтения/анти-предпочтения профиля.
Никаких внешних вызовов — чистый детерминированный сервис.
"""

from __future__ import annotations

from typing import Any

# Шаблоны CTA по типам (нейтральные, без обещаний недоступного).
_CTA_TEMPLATES: dict[str, str] = {
    "soft": "Узнайте подробности — напишите нам.",
    "direct": "Оставьте заявку — рассчитаем стоимость.",
    "urgency": "Успейте заказать на этой неделе — количество ограничено.",
    "offer": "Закажите со скидкой — предложение действует ограниченно.",
    "catalog": "Переходите в каталог и выбирайте свой вариант.",
}

# Углы подачи: ключ → человекочитаемая рамка первого абзаца.
_ANGLES: dict[str, str] = {
    "baseline": "{topic}.",
    "benefit": "{topic}: выгода для вашего бизнеса — экономия времени и предсказуемый результат.",
    "case": "Кейс: как «{topic}» решает задачу клиента на практике.",
    "product": "Продукт в фокусе: {topic} — что входит и чем отличается.",
    "technology": "Технология и производство: как мы делаем «{topic}» и почему это качественно.",
    "urgency": "Сейчас самое время: {topic} — успейте оформить в этом сезоне.",
    "expert": "Экспертный разбор: {topic} — на что смотреть при выборе.",
    "roundup": "Подборка: несколько решений вокруг «{topic}».",
}

# Специфика вариантов по порядковому индексу (A=0, B=1, C=2).
_VARIANT_SPECS: list[dict[str, str]] = [
    {"key": "A", "angle": "baseline", "cta": "soft", "length": "medium", "media": "with_media"},
    {"key": "B", "angle": "benefit", "cta": "offer", "length": "medium", "media": "with_media"},
    {"key": "C", "angle": "case", "cta": "direct", "length": "short", "media": "text_only"},
]

_LENGTH_TARGET = {"short": 220, "medium": 480, "long": 900}


class ContentVariantService:
    """Rule-based генерация вариантов текста поста и их различий."""

    def generate_text_variants(
        self,
        base_text: str | None,
        topic: str,
        profile: Any | None = None,
        variant_count: int = 2,
    ) -> list[dict[str, Any]]:
        """Собрать 2–3 варианта поста (A/B/C) с разными углом/CTA/длиной/медиа."""
        count = max(2, min(3, int(variant_count or 2)))
        topic = (topic or "Публикация").strip()
        preferred_cta = _as_str_list(_get(profile, "preferred_cta"))
        rejected_cta = {c.lower() for c in _as_str_list(_get(profile, "rejected_cta"))}
        forbidden = [p.lower() for p in _as_str_list(_get(profile, "forbidden_patterns"))]
        preferred_media = _as_str_list(_get(profile, "preferred_media_types"))
        best_times = _as_str_list(_get(profile, "best_publish_times"))

        variants: list[dict[str, Any]] = []
        for i in range(count):
            spec = _VARIANT_SPECS[i]
            cta = self._pick_cta(spec, i, preferred_cta, rejected_cta, forbidden)
            media = self._pick_media(spec, preferred_media)
            time_strategy = best_times[0] if best_times else "profile_best_time"
            text = self._build_text(base_text if i == 0 else None, topic, spec, cta, forbidden)
            variants.append(
                {
                    "variant_key": spec["key"],
                    "title": self._variant_title(topic, spec),
                    "angle": spec["angle"],
                    "cta_type": spec["cta"],
                    "text_length_type": spec["length"],
                    "media_strategy": media,
                    "publish_time_strategy": time_strategy,
                    "text": text,
                    "cta_text": cta,
                }
            )
        return variants

    def generate_cta_variants(self, profile: Any | None, topic: str) -> list[str]:
        """Список CTA-вариантов (предпочитаемые клиентом первыми, минус отклонённые)."""
        rejected = {c.lower() for c in _as_str_list(_get(profile, "rejected_cta"))}
        out: list[str] = []
        for cta in _as_str_list(_get(profile, "preferred_cta")):
            if cta.lower() not in rejected:
                out.append(cta)
        for template in _CTA_TEMPLATES.values():
            if template.lower() not in rejected and template not in out:
                out.append(template)
        return out

    def generate_angle_variants(self, topic: str, profile: Any | None) -> list[dict[str, str]]:
        """Углы подачи темы (ключ + первый абзац)."""
        topic = (topic or "тема").strip()
        return [{"angle": key, "lead": tmpl.format(topic=topic)} for key, tmpl in _ANGLES.items()]

    def generate_format_variants(self, text: str, profile: Any | None) -> list[dict[str, Any]]:
        """Форматы поста (короткий/экспертный/подборка/кейс) поверх текста."""
        text = (text or "").strip()
        return [
            {"format": "short", "length_type": "short", "text": self._truncate(text, 220)},
            {
                "format": "expert",
                "length_type": "long",
                "text": text + "\n\nЭкспертный разбор деталей.",
            },
            {"format": "roundup", "length_type": "medium", "text": "Подборка:\n• " + text},
            {"format": "case", "length_type": "medium", "text": "Кейс из практики.\n" + text},
        ]

    def summarize_variant_diff(
        self, variant_a: dict[str, Any], variant_b: dict[str, Any]
    ) -> dict[str, Any]:
        """Чем отличаются два варианта (длина/CTA/угол/медиа)."""
        ta = str(variant_a.get("text", ""))
        tb = str(variant_b.get("text", ""))
        return {
            "length_a": len(ta),
            "length_b": len(tb),
            "length_delta": len(tb) - len(ta),
            "cta_changed": variant_a.get("cta_type") != variant_b.get("cta_type"),
            "angle_changed": variant_a.get("angle") != variant_b.get("angle"),
            "media_changed": variant_a.get("media_strategy") != variant_b.get("media_strategy"),
            "text_changed": ta.strip() != tb.strip(),
        }

    # --- Внутреннее ---

    @staticmethod
    def _pick_cta(
        spec: dict[str, str],
        index: int,
        preferred_cta: list[str],
        rejected_cta: set[str],
        forbidden: list[str],
    ) -> str:
        # Вариант A предпочитает CTA клиента; B/C — усиленные шаблоны.
        if index == 0 and preferred_cta:
            candidate = preferred_cta[0]
            if candidate.lower() not in rejected_cta and not _contains_any(candidate, forbidden):
                return candidate
        candidate = _CTA_TEMPLATES.get(spec["cta"], _CTA_TEMPLATES["soft"])
        if candidate.lower() in rejected_cta or _contains_any(candidate, forbidden):
            # Найти любой допустимый шаблон; если все отклонены/запрещены — без CTA.
            for template in _CTA_TEMPLATES.values():
                if template.lower() not in rejected_cta and not _contains_any(template, forbidden):
                    return template
            return ""
        return candidate

    @staticmethod
    def _pick_media(spec: dict[str, str], preferred_media: list[str]) -> str:
        if spec["key"] == "A" and preferred_media:
            return preferred_media[0]
        return spec["media"]

    def _build_text(
        self,
        base_text: str | None,
        topic: str,
        spec: dict[str, str],
        cta: str,
        forbidden: list[str],
    ) -> str:
        lead = _ANGLES[spec["angle"]].format(topic=topic)
        body = (base_text or "").strip()
        if not body:
            body = self._synth_body(topic, spec)
        target = _LENGTH_TARGET[spec["length"]]
        parts = [lead]
        if body and body != lead:
            parts.append(body)
        if spec["length"] == "short":
            parts.append(cta)
        else:
            parts.append("Готовы обсудить детали под вашу задачу. " + cta)
        text = "\n\n".join(p for p in parts if p).strip()
        # Убрать запрещённые паттерны (best-effort).
        for pattern in forbidden:
            if pattern:
                text = text.replace(pattern, "").replace(pattern.capitalize(), "")
        if len(text) > target * 1.6:
            text = self._truncate(text, int(target * 1.6))
        return text.strip()

    @staticmethod
    def _synth_body(topic: str, spec: dict[str, str]) -> str:
        if spec["length"] == "short":
            return f"{topic}: коротко о главном — качество, сроки и понятная цена."
        return (
            f"{topic}. Рассказываем, что входит, как проходит работа и какой результат "
            "получает клиент. Делаем аккуратно и в срок, с прозрачной сметой."
        )

    @staticmethod
    def _variant_title(topic: str, spec: dict[str, str]) -> str:
        labels = {
            "baseline": "Базовый стиль",
            "benefit": "Акцент на выгоду",
            "case": "Кейс / пример",
            "product": "Продуктовый акцент",
            "technology": "Технология",
            "urgency": "Срочность",
            "expert": "Экспертный",
            "roundup": "Подборка",
        }
        return f"{spec['key']}: {labels.get(spec['angle'], spec['angle'])} — {topic}"[:255]

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 1)].rstrip() + "…"


def _get(profile: Any | None, field: str) -> Any:
    if profile is None:
        return None
    if isinstance(profile, dict):
        return profile.get(field)
    return getattr(profile, field, None)


def _as_str_list(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v).strip()]
    return [str(value)]


def _contains_any(text: str, patterns: list[str]) -> bool:
    lowered = text.lower()
    return any(p and p in lowered for p in patterns)


def get_content_variant_service() -> ContentVariantService:
    """DI-фабрика сервиса генерации вариантов."""
    return ContentVariantService()
