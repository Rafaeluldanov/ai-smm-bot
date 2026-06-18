"""Словарь тем и SEO-кластеров для проектов.

Бот не получает темы от человека: человек задаёт стратегические направления,
а бот выбирает конкретные темы из этого словаря. Здесь нет сети, БД и AI —
только статические данные и чистые функции.

Неизвестный ``project_slug`` НЕ бросает исключение: возвращается пустой
результат (пустой словарь кластеров / пустой список кандидатов), а вызывающий
код добавляет предупреждение.
"""

from typing import Any

# slug проекта -> { кластер: [темы] }
_CLUSTERS: dict[str, dict[str, list[str]]] = {
    "teeon": {
        "футболки": [
            "Футболки с логотипом на заказ",
            "Футболки для корпоративного мерча",
            "Футболки для мероприятий",
            "Футболки для сотрудников",
            "Печать на футболках",
            "Шелкография на футболках",
            "DTF-печать на футболках",
            "Как выбрать ткань для футболок",
            "Как рассчитать тираж футболок",
            "Ошибки при заказе футболок с логотипом",
        ],
        "худи": [
            "Худи с логотипом на заказ",
            "Худи для команды",
            "Худи для корпоративного мерча",
            "Шелкография на худи",
            "Вышивка на худи",
            "Жаккардовые элементы на худи",
            "Как сделать худи визуально дороже",
            "Худи для welcome-наборов",
        ],
        "шелкография": [
            "Шелкография на одежде",
            "Когда шелкография выгоднее DTF",
            "Шелкография для средних и крупных тиражей",
            "Шелкография на футболках",
            "Шелкография на худи",
            "Стойкость шелкографии на текстиле",
        ],
        "dtf": [
            "DTF-печать на одежде",
            "DTF для малых тиражей",
            "DTF или шелкография: что выбрать",
            "DTF-печать на футболках",
            "DTF-печать на худи",
        ],
        "вышивка": [
            "Вышивка на корпоративной одежде",
            "Вышивка на худи",
            "Вышивка на поло",
            "Когда вышивка выглядит лучше печати",
            "Премиальный мерч с вышивкой",
        ],
        "жаккард": [
            "Жаккардовые бирки для одежды",
            "Жаккардовые элементы в корпоративном мерче",
            "Как детали повышают ценность мерча",
            "Жаккард на худи",
            "Бирки, шевроны и брендированные детали",
        ],
        "шопперы": [
            "Шопперы с логотипом",
            "Шопперы для мероприятий",
            "Шелкография на шопперах",
            "Шопперы как корпоративный мерч",
        ],
        "корпоративный мерч": [
            "Корпоративный мерч на заказ",
            "Мерч для команды",
            "Welcome-наборы для сотрудников",
            "Мерч для мероприятий",
            "Как собрать мерч для компании",
            "Форма и промо-одежда для бизнеса",
        ],
    },
    "fabric-souvenirs": {
        "кружки": [
            "Кружки с логотипом",
            "Кружки с УФ-печатью",
            "Кружки как корпоративный подарок",
            "Кружки для мероприятий",
            "Как выбрать кружки для промоакции",
        ],
        "ручки": [
            "Ручки с логотипом",
            "Ручки с тампопечатью",
            "Ручки для выставок",
            "Ручки как массовый сувенир",
            "Брендированные ручки для клиентов",
        ],
        "пакеты": [
            "Пакеты с логотипом",
            "Пакеты для мероприятий",
            "Пакеты как часть фирменной упаковки",
            "Шелкография на пакетах",
        ],
        "уф-печать": [
            "УФ-печать на сувенирах",
            "УФ-печать на пластике",
            "УФ-печать на кружках",
            "Когда выбирать УФ-печать",
        ],
        "тампопечать": [
            "Тампопечать на ручках",
            "Тампопечать на сувенирах",
            "Тампопечать для малых изделий",
            "Когда выгодна тампопечать",
        ],
        "гравировка": [
            "Гравировка на ручках",
            "Гравировка на ежедневниках",
            "Лазерная гравировка на металле",
            "Гравировка для корпоративных подарков",
        ],
        "корпоративные подарки": [
            "Корпоративные подарки с логотипом",
            "Сувениры для мероприятий",
            "Подарки партнёрам",
            "Welcome-наборы",
            "Брендированные наборы для сотрудников",
        ],
    },
}

# Профиль кластера: рыночные сигналы (0..1), медиа-теги, форматы, приоритет, SEO.
_CLUSTER_PROFILE: dict[str, dict[str, Any]] = {
    # TEEON
    "футболки": {
        "search_demand": 0.95,
        "commercial_intent": 0.90,
        "seasonality": 0.55,
        "trend": 0.60,
        "competition": 0.80,
        "default_business_priority": 90,
        "related_media_tags": ["футболка"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["футболки с логотипом", "футболки на заказ", "корпоративные футболки"],
    },
    "худи": {
        "search_demand": 0.80,
        "commercial_intent": 0.95,
        "seasonality": 0.70,
        "trend": 0.70,
        "competition": 0.70,
        "default_business_priority": 85,
        "related_media_tags": ["худи"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["худи с логотипом", "худи на заказ", "корпоративные худи"],
    },
    "шелкография": {
        "search_demand": 0.60,
        "commercial_intent": 0.70,
        "seasonality": 0.40,
        "trend": 0.50,
        "competition": 0.50,
        "default_business_priority": 70,
        "related_media_tags": ["шелкография"],
        "recommended_formats": ["technology", "expert", "faq"],
        "seo_keywords": ["шелкография на одежде", "трафаретная печать", "шелкография на заказ"],
    },
    "dtf": {
        "search_demand": 0.60,
        "commercial_intent": 0.70,
        "seasonality": 0.40,
        "trend": 0.75,
        "competition": 0.50,
        "default_business_priority": 65,
        "related_media_tags": ["dtf"],
        "recommended_formats": ["technology", "expert", "faq"],
        "seo_keywords": ["dtf печать", "dtf на одежде", "dtf или шелкография"],
    },
    "вышивка": {
        "search_demand": 0.50,
        "commercial_intent": 0.70,
        "seasonality": 0.50,
        "trend": 0.40,
        "competition": 0.40,
        "default_business_priority": 60,
        "related_media_tags": ["вышивка"],
        "recommended_formats": ["technology", "expert", "case"],
        "seo_keywords": ["вышивка на одежде", "вышивка логотипа", "вышивка на заказ"],
    },
    "жаккард": {
        "search_demand": 0.30,
        "commercial_intent": 0.60,
        "seasonality": 0.40,
        "trend": 0.40,
        "competition": 0.30,
        "default_business_priority": 50,
        "related_media_tags": ["жаккард"],
        "recommended_formats": ["expert", "product", "case"],
        "seo_keywords": ["жаккардовые бирки", "брендированные детали одежды", "жаккард на заказ"],
    },
    "шопперы": {
        "search_demand": 0.55,
        "commercial_intent": 0.75,
        "seasonality": 0.60,
        "trend": 0.60,
        "competition": 0.50,
        "default_business_priority": 60,
        "related_media_tags": ["шоппер"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["шопперы с логотипом", "сумки шопперы на заказ", "брендированные шопперы"],
    },
    "корпоративный мерч": {
        "search_demand": 0.70,
        "commercial_intent": 0.95,
        "seasonality": 0.60,
        "trend": 0.65,
        "competition": 0.60,
        "default_business_priority": 80,
        "related_media_tags": ["футболка", "худи", "шоппер"],
        "recommended_formats": ["selling", "case", "product"],
        "seo_keywords": ["корпоративный мерч", "мерч на заказ", "мерч для компании"],
    },
    # Фабрика сувениров
    "кружки": {
        "search_demand": 0.85,
        "commercial_intent": 0.90,
        "seasonality": 0.60,
        "trend": 0.50,
        "competition": 0.70,
        "default_business_priority": 85,
        "related_media_tags": ["кружка"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["кружки с логотипом", "кружки на заказ", "промо кружки"],
    },
    "ручки": {
        "search_demand": 0.75,
        "commercial_intent": 0.85,
        "seasonality": 0.50,
        "trend": 0.40,
        "competition": 0.70,
        "default_business_priority": 80,
        "related_media_tags": ["ручка"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["ручки с логотипом", "ручки на заказ", "брендированные ручки"],
    },
    "пакеты": {
        "search_demand": 0.60,
        "commercial_intent": 0.80,
        "seasonality": 0.50,
        "trend": 0.40,
        "competition": 0.50,
        "default_business_priority": 65,
        "related_media_tags": ["пакет"],
        "recommended_formats": ["product", "selling", "case"],
        "seo_keywords": ["пакеты с логотипом", "пакеты на заказ", "фирменная упаковка"],
    },
    "уф-печать": {
        "search_demand": 0.55,
        "commercial_intent": 0.70,
        "seasonality": 0.40,
        "trend": 0.50,
        "competition": 0.50,
        "default_business_priority": 65,
        "related_media_tags": ["уф-печать"],
        "recommended_formats": ["technology", "expert", "faq"],
        "seo_keywords": ["уф-печать на сувенирах", "уф печать на пластике", "уф-печать на заказ"],
    },
    "тампопечать": {
        "search_demand": 0.45,
        "commercial_intent": 0.65,
        "seasonality": 0.40,
        "trend": 0.40,
        "competition": 0.40,
        "default_business_priority": 55,
        "related_media_tags": ["тампопечать"],
        "recommended_formats": ["technology", "expert", "faq"],
        "seo_keywords": ["тампопечать на ручках", "тампопечать сувениров", "тампопечать на заказ"],
    },
    "гравировка": {
        "search_demand": 0.60,
        "commercial_intent": 0.75,
        "seasonality": 0.50,
        "trend": 0.60,
        "competition": 0.50,
        "default_business_priority": 70,
        "related_media_tags": ["гравировка"],
        "recommended_formats": ["technology", "expert", "case"],
        "seo_keywords": ["гравировка на сувенирах", "лазерная гравировка", "гравировка на заказ"],
    },
    "корпоративные подарки": {
        "search_demand": 0.80,
        "commercial_intent": 0.95,
        "seasonality": 0.80,
        "trend": 0.60,
        "competition": 0.70,
        "default_business_priority": 85,
        "related_media_tags": ["кружка", "ручка", "ежедневник"],
        "recommended_formats": ["selling", "case", "product"],
        "seo_keywords": ["корпоративные подарки", "подарки с логотипом", "сувениры на заказ"],
    },
}

# Профиль по умолчанию для неизвестного кластера.
_DEFAULT_PROFILE: dict[str, Any] = {
    "search_demand": 0.40,
    "commercial_intent": 0.40,
    "seasonality": 0.40,
    "trend": 0.40,
    "competition": 0.50,
    "default_business_priority": 40,
    "related_media_tags": [],
    "recommended_formats": ["expert", "product"],
    "seo_keywords": [],
}

# Канонический медиа-тег -> кластер (для infer_cluster_from_tags).
_TAG_TO_CLUSTER: dict[str, str] = {
    "футболка": "футболки",
    "худи": "худи",
    "шоппер": "шопперы",
    "сумка": "шопперы",
    "шелкография": "шелкография",
    "dtf": "dtf",
    "вышивка": "вышивка",
    "жаккард": "жаккард",
    "кружка": "кружки",
    "ручка": "ручки",
    "пакет": "пакеты",
    "ежедневник": "корпоративные подарки",
    "уф-печать": "уф-печать",
    "тампопечать": "тампопечать",
    "гравировка": "гравировка",
}

# Допустимые форматы публикаций.
RECOMMENDED_FORMATS: list[str] = ["expert", "technology", "product", "case", "faq", "selling"]


def normalize_topic_key(value: str) -> str:
    """Нормализовать ключ темы/кластера: нижний регистр, ё→е, схлопывание пробелов."""
    return " ".join(value.lower().replace("ё", "е").split())


def get_cluster_profile(cluster: str) -> dict[str, Any]:
    """Вернуть профиль кластера (или профиль по умолчанию)."""
    return _CLUSTER_PROFILE.get(normalize_topic_key(cluster), _DEFAULT_PROFILE)


def get_topic_clusters(project_slug: str) -> dict[str, list[str]]:
    """Вернуть кластеры и их темы для проекта (пустой dict для неизвестного slug)."""
    return _CLUSTERS.get(project_slug, {})


def get_cluster_topics(project_slug: str, cluster: str) -> list[str]:
    """Вернуть темы кластера (пустой список, если не найдено)."""
    return get_topic_clusters(project_slug).get(cluster, [])


def get_all_topic_candidates(project_slug: str) -> list[dict[str, Any]]:
    """Вернуть плоский список кандидатов-тем проекта с метаданными."""
    candidates: list[dict[str, Any]] = []
    for cluster, titles in get_topic_clusters(project_slug).items():
        profile = get_cluster_profile(cluster)
        for title in titles:
            base_seo = list(dict.fromkeys([*profile["seo_keywords"], normalize_topic_key(title)]))
            candidates.append(
                {
                    "title": title,
                    "cluster": cluster,
                    "base_seo_keywords": base_seo,
                    "related_media_tags": list(profile["related_media_tags"]),
                    "recommended_formats": list(profile["recommended_formats"]),
                    "default_business_priority": int(profile["default_business_priority"]),
                    "commercial_intent_score": float(profile["commercial_intent"]),
                    "base_search_demand_score": float(profile["search_demand"]),
                }
            )
    return candidates


def infer_cluster_from_tags(tags: dict[str, Any]) -> list[str]:
    """Определить кластеры по медиа-тегам (products/technologies/details)."""
    clusters: list[str] = []
    for group in ("products", "technologies", "details"):
        for value in tags.get(group, []) or []:
            cluster = _TAG_TO_CLUSTER.get(normalize_topic_key(value))
            if cluster is not None and cluster not in clusters:
                clusters.append(cluster)
    return clusters
