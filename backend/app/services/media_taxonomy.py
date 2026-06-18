"""Словари терминов и правила анализа названий медиафайлов.

Здесь нет обращений к БД, сети или AI — только текстовый разбор имени файла
по словарям предметной области (TEEON и «Фабрика сувениров»).

Сопоставление морфологическое (без внешних стеммеров):
- однословные термины сравниваются с токенами текста по точному совпадению,
  по префиксу (словоформа: «жаккардами» → «жаккард») и по общему префиксу
  с расхождением в хвосте не более 2 символов («шелкографией» → «шелкография»);
- многословные термины ищутся как подстрока в нормализованном тексте;
- короткие коды (≤3 символов: dtf, dtg, uv, hr, b2b) — только точное совпадение
  токена, чтобы избежать ложных срабатываний.
"""

import re
from typing import Any

# --- Словари терминов: канонический тег -> список синонимов/словоформ ---

PRODUCT_TERMS: dict[str, list[str]] = {
    "футболка": ["футболка", "футболки", "футболку", "t-shirt", "tshirt"],
    "худи": ["худи", "hoodie", "толстовка", "толстовки", "толстовка с капюшоном"],
    "свитшот": ["свитшот", "свитшоты", "sweatshirt"],
    "лонгслив": ["лонгслив", "лонгсливы", "long sleeve"],
    "поло": ["поло", "polo"],
    "жилет": ["жилет", "жилеты"],
    "ветровка": ["ветровка", "ветровки"],
    "дождевик": ["дождевик", "дождевики"],
    "сумка": ["сумка", "сумки"],
    "шоппер": ["шоппер", "шопперы", "shopper"],
    "кепка": ["кепка", "кепки", "бейсболка"],
    "кружка": ["кружка", "кружки"],
    "ручка": ["ручка", "ручки"],
    "пакет": ["пакет", "пакеты"],
    "ежедневник": ["ежедневник", "ежедневники"],
    "флешка": ["флешка", "флешки"],
}

TECHNOLOGY_TERMS: dict[str, list[str]] = {
    "шелкография": [
        "шелкография",
        "шелкуха",
        "трафаретная печать",
        "screen printing",
        "silkscreen",
    ],
    "dtf": ["dtf", "дтф", "dtf печать"],
    "dtg": ["dtg", "дтг", "прямая печать"],
    "вышивка": ["вышивка", "вышивкой", "embroidery"],
    "уф-печать": ["уф", "уф печать", "уф-печать", "uv", "uv print"],
    "тампопечать": ["тампопечать", "тампо", "pad printing"],
    "гравировка": ["гравировка", "лазерная гравировка", "engraving"],
    "сублимация": ["сублимация", "sublimation"],
    "тиснение": ["тиснение", "embossing"],
    "термотрансфер": ["термотрансфер", "thermal transfer"],
}

# Элементы/детали изделия. Жаккард, бирка и шеврон — декоративные элементы,
# поэтому хранятся как detail (это сохраняет совместимость со старыми тестами,
# где «жаккард» относился к details).
DETAIL_TERMS: dict[str, list[str]] = {
    "карман": ["карман", "карманы", "кенгуру"],
    "жаккард": ["жаккард", "жаккарды", "жакард", "жакарды", "жаккардовая бирка"],
    "бирка": ["бирка", "бирки", "ярлык", "ярлыки", "этикетка", "этикетки"],
    "шеврон": ["шеврон", "шевроны", "нашивка", "нашивки"],
    "капюшон": ["капюшон", "капюшоны"],
    "молния": ["молния", "молнии", "zip", "zipper"],
    "шнурок": ["шнурок", "шнурки"],
    "логотип": ["логотип", "лого", "logo"],
    "принт": ["принт", "печать", "нанесение"],
    "горловина": ["горловина", "ворот", "воротник"],
    "рукав": ["рукав", "рукава"],
    "грудь": ["грудь", "на груди"],
    "спина": ["спина", "на спине"],
    "упаковка": ["упаковка", "коробка", "коробки"],
    "партия": ["партия", "тираж"],
}

MATERIAL_TERMS: dict[str, list[str]] = {
    "хлопок": ["хлопок", "хлопковый", "хлопковая"],
    "футер": ["футер"],
    "кулирка": ["кулирка"],
    "трикотаж": ["трикотаж"],
    "полиэстер": ["полиэстер"],
    "флис": ["флис"],
    "ткань": ["ткань"],
    "металл": ["металл", "металлический"],
    "пластик": ["пластик", "пластиковый"],
    "керамика": ["керамика", "керамический", "керамическая"],
    "бумага": ["бумага", "бумажный"],
    "картон": ["картон", "картонный"],
    "кожа": ["кожа", "кожаный"],
    "экокожа": ["экокожа"],
}

COLOR_TERMS: dict[str, list[str]] = {
    "белый": ["белый", "белая", "белое"],
    "черный": ["черный", "чёрный", "черная", "чёрная"],
    "красный": ["красный", "красная"],
    "синий": ["синий", "синяя"],
    "зеленый": ["зеленый", "зелёный", "зеленая", "зелёная"],
    "серый": ["серый", "серая"],
    "бежевый": ["бежевый", "бежевая"],
    "желтый": ["желтый", "жёлтый"],
    "оранжевый": ["оранжевый"],
    "фиолетовый": ["фиолетовый"],
    "розовый": ["розовый"],
}

USE_CASE_TERMS: dict[str, list[str]] = {
    "корпоративный мерч": ["корпоративный мерч"],
    "мерч": ["мерч"],
    "промо": ["промо"],
    "мероприятие": ["мероприятие"],
    "выставка": ["выставка"],
    "конференция": ["конференция"],
    "welcome pack": ["welcome pack", "welcome-набор", "welcome набор"],
    "сотрудники": ["сотрудники"],
    "команда": ["команда"],
    "event": ["event"],
    "подарок": ["подарок"],
    "корпоративный подарок": ["корпоративный подарок"],
    "промоакция": ["промоакция"],
    "форма": ["форма"],
    "униформа": ["униформа"],
}

AUDIENCE_TERMS: dict[str, list[str]] = {
    "hr": ["hr"],
    "маркетолог": ["маркетолог", "маркетологи"],
    "event": ["event"],
    "бизнес": ["бизнес"],
    "b2b": ["b2b"],
    "сотрудники": ["сотрудники"],
    "партнёры": ["партнёры", "партнеры"],
    "клиенты": ["клиенты"],
    "команда": ["команда"],
}

# Слова, указывающие на производственный процесс (категория production).
PRODUCTION_WORDS: list[str] = ["цех", "производство", "станок", "процесс"]

# Изделия, относящиеся к одежде / к сувенирам (для категорий).
_APPAREL_PRODUCTS = {
    "футболка",
    "худи",
    "свитшот",
    "лонгслив",
    "поло",
    "жилет",
    "ветровка",
    "дождевик",
    "кепка",
}
_SOUVENIR_PRODUCTS = {"кружка", "ручка", "пакет", "ежедневник", "флешка", "сумка", "шоппер"}
_EVENT_USE_CASES = {"мероприятие", "выставка", "конференция", "event", "промоакция"}

_EXTENSION_RE = re.compile(r"\.[a-z0-9]{1,5}$")
_SEPARATORS_RE = re.compile(r"[_\-.]+")


def normalize_text(text: str) -> str:
    """Привести текст к нормальной форме для разбора.

    Нижний регистр, ``ё`` → ``е``, удаление расширения файла, замена
    ``_ - .`` на пробелы, схлопывание пробелов.
    """
    lowered = text.lower().replace("ё", "е")
    without_ext = _EXTENSION_RE.sub("", lowered)
    spaced = _SEPARATORS_RE.sub(" ", without_ext)
    return " ".join(spaced.split())


def _normalize_term(term: str) -> str:
    """Нормализовать словарный термин (без удаления расширения)."""
    lowered = term.lower().replace("ё", "е")
    spaced = _SEPARATORS_RE.sub(" ", lowered)
    return " ".join(spaced.split())


def _build_normalized(terms: dict[str, list[str]]) -> dict[str, list[str]]:
    return {canonical: [_normalize_term(s) for s in syns] for canonical, syns in terms.items()}


_PRODUCTS_N = _build_normalized(PRODUCT_TERMS)
_TECHNOLOGIES_N = _build_normalized(TECHNOLOGY_TERMS)
_DETAILS_N = _build_normalized(DETAIL_TERMS)
_MATERIALS_N = _build_normalized(MATERIAL_TERMS)
_COLORS_N = _build_normalized(COLOR_TERMS)
_USE_CASES_N = _build_normalized(USE_CASE_TERMS)
_AUDIENCES_N = _build_normalized(AUDIENCE_TERMS)


def _common_prefix_len(a: str, b: str) -> int:
    limit = min(len(a), len(b))
    i = 0
    while i < limit and a[i] == b[i]:
        i += 1
    return i


def _term_matches(normalized_text: str, tokens: list[str], synonym: str) -> bool:
    """Проверить, встречается ли (нормализованный) синоним в тексте."""
    if " " in synonym:  # многословный термин — ищем как подстроку
        return synonym in normalized_text
    if len(synonym) <= 3:  # короткие коды — только точное совпадение токена
        return synonym in tokens
    for token in tokens:
        if token == synonym:
            return True
        if token.startswith(synonym) and (len(token) - len(synonym)) <= 3:
            return True
        lcp = _common_prefix_len(token, synonym)
        if lcp >= 4 and (len(synonym) - lcp) <= 2 and (len(token) - lcp) <= 2:
            return True
    return False


def _match_group(normalized_text: str, tokens: list[str], terms: dict[str, list[str]]) -> list[str]:
    """Вернуть канонические теги группы, найденные в тексте (стабильный порядок)."""
    found: list[str] = []
    for canonical, synonyms in terms.items():
        if canonical in found:
            continue
        if any(_term_matches(normalized_text, tokens, syn) for syn in synonyms):
            found.append(canonical)
    return found


def _derive_categories(
    products: list[str],
    technologies: list[str],
    details: list[str],
    use_cases: list[str],
    normalized_text: str,
    tokens: list[str],
) -> list[str]:
    categories: list[str] = []
    if any(p in _APPAREL_PRODUCTS for p in products):
        categories.append("apparel")
    if any(p in _SOUVENIR_PRODUCTS for p in products):
        categories.append("souvenirs")
    if technologies:
        categories.append("branding")
    if any(_term_matches(normalized_text, tokens, word) for word in PRODUCTION_WORDS):
        categories.append("production")
    if "упаковка" in details:
        categories.append("packaging")
    if any(u in _EVENT_USE_CASES for u in use_cases):
        categories.append("event_merch")
    return categories


def extract_keywords_by_taxonomy(text: str) -> dict[str, Any]:
    """Разобрать текст (имя файла) по словарям и вернуть структуру тегов."""
    normalized = normalize_text(text)
    tokens = normalized.split()

    products = _match_group(normalized, tokens, _PRODUCTS_N)
    technologies = _match_group(normalized, tokens, _TECHNOLOGIES_N)
    details = _match_group(normalized, tokens, _DETAILS_N)
    materials = _match_group(normalized, tokens, _MATERIALS_N)
    colors = _match_group(normalized, tokens, _COLORS_N)
    use_cases = _match_group(normalized, tokens, _USE_CASES_N)
    audiences = _match_group(normalized, tokens, _AUDIENCES_N)
    categories = _derive_categories(products, technologies, details, use_cases, normalized, tokens)

    matched_terms: dict[str, list[str]] = {}
    for key, values in (
        ("products", products),
        ("technologies", technologies),
        ("details", details),
        ("materials", materials),
        ("colors", colors),
        ("use_cases", use_cases),
        ("audiences", audiences),
    ):
        if values:
            matched_terms[key] = values

    return {
        "products": products,
        "technologies": technologies,
        "details": details,
        "materials": materials,
        "colors": colors,
        "categories": categories,
        "use_cases": use_cases,
        "audiences": audiences,
        "matched_terms": matched_terms,
    }


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def build_topics_from_tags(tags: dict[str, Any], project_slug: str | None = None) -> list[str]:
    """Сформировать черновые темы публикаций из тегов (стабильный порядок)."""
    products: list[str] = tags.get("products", []) or []
    technologies: list[str] = tags.get("technologies", []) or []

    topics: list[str] = []
    for product in products:
        topics.append(f"{product} с логотипом")
        for technology in technologies:
            topics.append(f"{technology} на {product}")
    if not products:
        for technology in technologies:
            topics.append(f"{technology} на заказ")
    if products or technologies:
        topics.append("корпоративный мерч")
    return _dedupe(topics)


def build_seo_keywords_from_tags(
    tags: dict[str, Any], project_slug: str | None = None
) -> list[str]:
    """Сформировать черновые SEO-фразы из тегов (стабильный порядок)."""
    products: list[str] = tags.get("products", []) or []
    technologies: list[str] = tags.get("technologies", []) or []

    keywords: list[str] = []
    for product in products:
        keywords.append(f"{product} с логотипом на заказ")
        for technology in technologies:
            keywords.append(f"{technology} на {product}")
    if not products:
        for technology in technologies:
            keywords.append(f"{technology} на заказ")
    if products or technologies:
        keywords.append("корпоративный мерч на заказ")
    return _dedupe(keywords)


def calculate_tag_confidence(tags: dict[str, Any]) -> float:
    """Оценить уверенность тегирования (0.0–1.0) по заполненности групп."""
    score = 0.0
    if tags.get("products"):
        score += 0.45
    if tags.get("technologies"):
        score += 0.30
    if tags.get("details"):
        score += 0.10
    if tags.get("materials"):
        score += 0.05
    if tags.get("colors"):
        score += 0.05
    if tags.get("use_cases"):
        score += 0.05
    return round(min(score, 1.0), 2)
