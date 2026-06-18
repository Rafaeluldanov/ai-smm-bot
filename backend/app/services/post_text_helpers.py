"""Помощники для текста поста: хэштеги, призывы к действию (CTA), сокращение.

Здесь нет AI и сети — только детерминированные правила. CTA и брендовые
хэштеги заданы под конкретные проекты (TEEON, «Фабрика сувениров»).
"""

import re

# Разрешённые в хэштеге символы — латиница, кириллица и цифры. Остальное удаляем.
_HASHTAG_DISALLOWED = re.compile(r"[^0-9a-zа-я]+")

# Отображаемое имя бренда по slug проекта.
_BRAND_NAMES: dict[str, str] = {
    "teeon": "TEEON",
    "fabric-souvenirs": "Фабрика сувениров",
}

# Брендовые и тематические хэштеги, добавляемые в каждый пост проекта.
_BRAND_HASHTAGS: dict[str, list[str]] = {
    "teeon": ["#teeon", "#корпоративныймерч"],
    "fabric-souvenirs": ["#фабрикасувениров", "#корпоративныеподарки"],
}

# Варианты CTA по проектам (выбор детерминирован форматом).
_CTAS: dict[str, list[str]] = {
    "teeon": [
        "Напишите нам — подберём изделие, нанесение и рассчитаем тираж.",
        "Оставьте заявку — поможем собрать мерч под задачу и бюджет.",
        "Пришлите логотип и тираж — предложим варианты нанесения.",
    ],
    "fabric-souvenirs": [
        "Напишите нам — подберём сувениры и рассчитаем нанесение.",
        "Пришлите задачу и тираж — предложим варианты брендирования.",
        "Оставьте заявку — соберём корпоративный подарок под ваш бюджет.",
    ],
}

# CTA для неизвестного проекта (без обещаний и брендовых деталей).
_DEFAULT_CTAS: list[str] = [
    "Напишите нам — поможем с задачей и расчётом.",
    "Оставьте заявку — предложим подходящее решение.",
    "Свяжитесь с нами — подберём вариант под ваш бюджет.",
]

# Индекс CTA в списке проекта по формату поста.
_FORMAT_CTA_INDEX: dict[str, int] = {
    "product": 0,
    "selling": 1,
    "case": 0,
    "expert": 2,
    "faq": 2,
    "technology": 2,
}

# Максимальная длина «тела» одного хэштега (без учёта решётки).
_MAX_HASHTAG_LEN = 40
# Сколько тематических хэштегов берём до добавления брендовых.
_MAX_CONTENT_HASHTAGS = 6


def get_brand_name(project_slug: str) -> str:
    """Вернуть отображаемое имя бренда по slug проекта."""
    return _BRAND_NAMES.get(project_slug, "наша команда")


def clean_hashtag(value: str) -> str:
    """Привести строку к одному хэштегу без пробелов.

    Кириллица разрешена, регистр приводится к нижнему, ё→е, лишние символы
    удаляются. Пустой результат возвращается как пустая строка.
    """
    text = value.strip().lstrip("#").lower().replace("ё", "е")
    cleaned = _HASHTAG_DISALLOWED.sub("", text)
    if not cleaned:
        return ""
    return "#" + cleaned[:_MAX_HASHTAG_LEN]


def build_hashtags(
    project_slug: str,
    topic_title: str,
    cluster: str,
    seo_keywords: list[str],
) -> list[str]:
    """Собрать список хэштегов: тематические из SEO + кластера + бренд.

    Без дублей, без пустых, порядок стабильный: сначала тематические
    (до ``_MAX_CONTENT_HASHTAGS``), затем брендовые проекта.
    """
    hashtags: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        tag = clean_hashtag(raw)
        if tag and tag not in seen:
            seen.add(tag)
            hashtags.append(tag)

    for keyword in seo_keywords:
        if len(hashtags) >= _MAX_CONTENT_HASHTAGS:
            break
        _add(keyword)
    if len(hashtags) < _MAX_CONTENT_HASHTAGS:
        _add(cluster)
    if len(hashtags) < _MAX_CONTENT_HASHTAGS:
        _add(topic_title)

    for brand_tag in _BRAND_HASHTAGS.get(project_slug, []):
        _add(brand_tag)

    return hashtags


def build_cta(project_slug: str, format_name: str) -> str:
    """Вернуть призыв к действию под проект и формат поста."""
    variants = _CTAS.get(project_slug, _DEFAULT_CTAS)
    index = _FORMAT_CTA_INDEX.get(format_name, 0)
    return variants[index % len(variants)]


def shorten_text(text: str, max_len: int) -> str:
    """Сократить текст до ``max_len`` символов, не разрывая слова грубо.

    Если текст помещается — возвращается как есть (после strip). Иначе
    обрезается по границе слова и дополняется многоточием, итог не длиннее
    ``max_len``.
    """
    if max_len <= 0:
        return ""
    stripped = text.strip()
    if len(stripped) <= max_len:
        return stripped

    ellipsis = "…"
    budget = max_len - len(ellipsis)
    if budget <= 0:
        return ellipsis[:max_len]

    truncated = stripped[:budget].rstrip()
    space = truncated.rfind(" ")
    if space > budget // 2:
        truncated = truncated[:space].rstrip()
    return truncated.rstrip(" .,;:—-") + ellipsis
