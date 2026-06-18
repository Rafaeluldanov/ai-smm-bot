"""Таксономия форматов постов: правила генерации текста по форматам.

Бот не пишет тексты через AI: он собирает черновик по детерминированным
шаблонам. Здесь задаются форматы публикаций (что это, какая структура, какой
тон и тип призыва к действию) и функции выбора формата под конкретную тему.

Модуль чистый: без БД, сети и AI — только данные и функции.
"""

from typing import Any

# Форматы публикаций: назначение, структура блоков, тон, тип CTA.
_FORMATS: dict[str, dict[str, Any]] = {
    "expert": {
        "purpose": "Показать экспертизу и помочь разобраться в теме до заказа.",
        "structure": ["hook", "explanation", "practical_value", "soft_cta"],
        "tone": "экспертный, спокойный, без давления",
        "cta_type": "soft",
    },
    "product": {
        "purpose": "Представить изделие и его применение и подвести к заказу.",
        "structure": ["product_intro", "use_cases", "benefits", "cta"],
        "tone": "дружелюбный и конкретный",
        "cta_type": "direct",
    },
    "technology": {
        "purpose": "Объяснить технологию нанесения и когда её стоит выбирать.",
        "structure": ["what_it_is", "when_to_use", "advantages", "cta"],
        "tone": "разъясняющий и профессиональный",
        "cta_type": "direct",
    },
    "case": {
        "purpose": "Показать на практике, как решается типовая задача клиента.",
        "structure": ["task", "solution", "result", "cta"],
        "tone": "повествовательный и доказательный",
        "cta_type": "direct",
    },
    "faq": {
        "purpose": "Ответить на частые вопросы клиентов простым языком.",
        "structure": ["question", "answer", "recommendation", "cta"],
        "tone": "понятный и дружелюбный",
        "cta_type": "soft",
    },
    "selling": {
        "purpose": "Прямо предложить услугу под задачу, тираж и бюджет.",
        "structure": ["offer", "benefits", "proof", "direct_cta"],
        "tone": "продающий, но без неподтверждённых обещаний",
        "cta_type": "direct",
    },
}

# Ключевые слова для определения формата по теме (порядок задаёт приоритет).
_FORMAT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("faq", ["ошибк", "когда ", "что выбрать", " или ", "?", "вопрос"]),
    ("expert", ["как ", "почему", "чем отличается", "гид", "разбор", "стоит ли"]),
    (
        "technology",
        [
            "шелкограф",
            "dtf",
            "dtg",
            "вышивк",
            "гравировк",
            "уф-печать",
            "уф печать",
            "тампопечат",
            "печать",
            "технолог",
            "нанесени",
        ],
    ),
    ("case", ["кейс", "пример", "как мы", "результат"]),
    ("selling", ["акци", "скидк", "успей", "под ключ", "распродаж"]),
]


def _normalize(value: str) -> str:
    """Нижний регистр, ё→е, схлопывание пробелов (для сопоставления ключей)."""
    return " ".join(value.lower().replace("ё", "е").split())


def get_available_formats() -> list[str]:
    """Вернуть список доступных форматов в каноническом порядке."""
    return list(_FORMATS.keys())


def get_template_for_format(format_name: str) -> dict[str, Any]:
    """Вернуть правила формата (копию). Бросает ValueError для неизвестного."""
    template = _FORMATS.get(format_name)
    if template is None:
        raise ValueError(f"Неизвестный формат поста: '{format_name}'")
    return {**template, "structure": list(template["structure"])}


def infer_format_from_topic(
    topic_title: str,
    cluster: str,
    recommended_formats: list[str] | None = None,
) -> str:
    """Определить формат под тему.

    Приоритет: 1) первый известный формат из ``recommended_formats``;
    2) формат по ключевым словам заголовка/кластера; 3) ``product`` по умолчанию.
    """
    available = set(_FORMATS)
    if recommended_formats:
        for fmt in recommended_formats:
            if fmt in available:
                return fmt

    text = _normalize(f"{topic_title} {cluster}")
    for fmt, keywords in _FORMAT_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            return fmt
    return "product"
