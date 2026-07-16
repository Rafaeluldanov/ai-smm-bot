"""PlatformRecommendationsService — статическая экспертная база SMM-рекомендаций Botfleet (v1.0.1).

READ-ONLY знание: роль платформы, частота, сигналы алгоритмов, форматы, правила, риски, KPI,
недельный ритм, чек-лист, кросс-платформенная адаптация. Данные загружаются из локального
versioned JSON-ресурса (`app/resources/botfleet_smm_recommendations_2026.json`).

ЖЁСТКИЕ ИНВАРИАНТЫ БЕЗОПАСНОСТИ:
- полностью read-only: НЕ меняет расписание/автопостинг/CRM/бюджет, НЕ публикует, НЕ шлёт сообщений,
  НЕ создаёт workflow, НЕ ходит во внешние API, НЕ пишет в БД, НЕ списывает units;
- путь к ресурсу зафиксирован в коде (не строится из пользовательского ввода) → path traversal
  невозможен; platform slug проходит whitelist-нормализацию (только [a-z0-9_]);
- секретов не хранит; HTML/скриптов в ресурсе нет (валидируется), UI экранирует весь текст.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# Путь к ресурсу ЗАФИКСИРОВАН в коде (app/resources/...); из пользовательского ввода не строится.
_RESOURCE_PATH = (
    Path(__file__).resolve().parent.parent / "resources" / "botfleet_smm_recommendations_2026.json"
)

# Обязательные корневые ключи базы знаний.
_REQUIRED_ROOT_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "product",
        "language",
        "title",
        "disclaimer",
        "universal_principles",
        "platforms",
        "cross_platform_pipeline",
        "weekly_rhythm",
        "pre_publish_checklist",
    }
)

# Канонические slug базы знаний (10 каналов).
_CANONICAL_SLUGS: tuple[str, ...] = (
    "instagram",
    "telegram",
    "vk",
    "youtube",
    "rutube",
    "dzen",
    "ok",
    "website",
    "2gis",
    "email",
)

# Алиасы → canonical slug базы знаний (в т. ч. фактические slug каталога проекта:
# odnoklassniki, two_gis). Разрешаются ТОЛЬКО внутри сервиса; canonical slug проекта не меняются.
_ALIASES: dict[str, str] = {
    "vkontakte": "vk",
    "vk_com": "vk",
    "odnoklassniki": "ok",
    "zen": "dzen",
    "yandex_dzen": "dzen",
    "site": "website",
    "web": "website",
    "gis2": "2gis",
    "two_gis": "2gis",
    "email_marketing": "email",
}

# Соответствие canonical slug → ключ в кросс-платформенном конвейере (display-имя).
_PIPELINE_KEY: dict[str, str] = {
    "instagram": "Instagram",
    "vk": "VK",
    "telegram": "Telegram",
    "youtube": "YouTube",
    "rutube": "RuTube",
    "dzen": "Дзен",
    "ok": "OK",
}

# Ключи, похожие на секреты (запрещены в ресурсе).
_SECRET_LIKE: frozenset[str] = frozenset(
    {"password", "secret", "token", "api_key", "apikey", "access_key", "refresh", "private_key"}
)


class PlatformRecommendationsError(Exception):
    """Ошибка базы рекомендаций (битый/невалидный ресурс) — API → контролируемый 500."""


class UnknownPlatformError(PlatformRecommendationsError):
    """Платформа неизвестна базе знаний — API → 404."""


class PlatformRecommendationsService:
    """Read-only доступ к экспертной базе SMM-рекомендаций Botfleet."""

    # ------------------------------------------------------------------ #
    # Загрузка / кэш                                                     #
    # ------------------------------------------------------------------ #

    def load_knowledge_base(self) -> dict[str, Any]:
        """Загрузить базу знаний из локального JSON (кэшируется). Возвращает копию (read-only)."""
        return copy.deepcopy(_load_cached())

    def normalize_platform_slug(self, platform_slug: str) -> str:
        """Нормализовать slug: whitelist [a-z0-9_] + алиасы → canonical slug базы знаний.

        Неизвестная платформа → UnknownPlatformError (API → 404). Path traversal невозможен:
        любые «/», «.», «\\» и пр. вырезаются, slug используется только как ключ словаря.
        """
        cleaned = _clean_slug(platform_slug)
        canonical = _ALIASES.get(cleaned, cleaned)
        if canonical not in _CANONICAL_SLUGS:
            raise UnknownPlatformError(f"Платформа не найдена: {platform_slug}")
        return canonical

    # ------------------------------------------------------------------ #
    # Публичные представления                                            #
    # ------------------------------------------------------------------ #

    def list_platforms(self) -> list[dict[str, Any]]:
        """Краткий список платформ: slug/title/role/frequency_summary."""
        kb = _load_cached()
        platforms = kb["platforms"]
        result: list[dict[str, Any]] = []
        for slug in _CANONICAL_SLUGS:
            node = platforms.get(slug, {})
            result.append(
                {
                    "slug": slug,
                    "title": node.get("title", slug),
                    "role": node.get("role", ""),
                    "frequency_summary": node.get("frequency_summary", ""),
                }
            )
        return result

    def get_platform_recommendations(self, platform_slug: str) -> dict[str, Any]:
        """Полные рекомендации по платформе (read-only). Неизвестная платформа → 404."""
        canonical = self.normalize_platform_slug(platform_slug)
        kb = _load_cached()
        node = kb["platforms"].get(canonical)
        if node is None:  # pragma: no cover — гарантируется validate_knowledge_base
            raise UnknownPlatformError(f"Платформа не найдена: {platform_slug}")
        weekly = kb.get("weekly_rhythm", {}).get("platforms", {}).get(canonical, {})
        return copy.deepcopy(
            {
                "version": kb.get("version", ""),
                "platform": canonical,
                "title": node.get("title", canonical),
                "role": node.get("role", ""),
                "frequency_summary": node.get("frequency_summary", ""),
                "signals": node.get("signals", []),
                "frequency": node.get("frequency", []),
                "content_rules": node.get("content_rules", []),
                "formats": node.get("formats", []),
                "risks": node.get("risks", []),
                "kpi": node.get("kpi", []),
                "extra_sections": node.get("extra_sections", []),
                "weekly_rhythm": weekly,
                "universal_principles": kb.get("universal_principles", []),
                "pre_publish_checklist": kb.get("pre_publish_checklist", []),
                "cross_platform_notes": self._cross_platform_notes(kb, canonical),
                "disclaimer": kb.get("disclaimer", ""),
            }
        )

    def get_universal_recommendations(self) -> dict[str, Any]:
        """Универсальные принципы, конвейер, недельный ритм и чек-лист (read-only)."""
        kb = _load_cached()
        return copy.deepcopy(
            {
                "version": kb.get("version", ""),
                "product": kb.get("product", ""),
                "title": kb.get("title", ""),
                "disclaimer": kb.get("disclaimer", ""),
                "universal_principles": kb.get("universal_principles", []),
                "cross_platform_pipeline": kb.get("cross_platform_pipeline", {}),
                "weekly_rhythm": kb.get("weekly_rhythm", {}),
                "pre_publish_checklist": kb.get("pre_publish_checklist", []),
            }
        )

    # ------------------------------------------------------------------ #
    # Валидация                                                          #
    # ------------------------------------------------------------------ #

    def validate_knowledge_base(self) -> bool:
        """Проверить целостность базы знаний. Ошибка → PlatformRecommendationsError."""
        kb = _load_cached()
        missing = _REQUIRED_ROOT_KEYS - set(kb)
        if missing:
            raise PlatformRecommendationsError(
                f"Нет обязательных корневых ключей: {sorted(missing)}"
            )
        if not str(kb.get("version") or "").strip():
            raise PlatformRecommendationsError("Не заполнена версия базы знаний")
        if kb.get("product") != "Botfleet":
            raise PlatformRecommendationsError("product должен быть Botfleet")

        platforms = kb.get("platforms")
        if not isinstance(platforms, dict):
            raise PlatformRecommendationsError("platforms должен быть объектом")
        missing_slugs = set(_CANONICAL_SLUGS) - set(platforms)
        if missing_slugs:
            raise PlatformRecommendationsError(f"Нет платформ: {sorted(missing_slugs)}")
        # slug уникальны by-construction (ключи dict); проверяем типы и обязательные секции.
        for slug in _CANONICAL_SLUGS:
            node = platforms[slug]
            if not isinstance(node, dict):
                raise PlatformRecommendationsError(f"Платформа {slug} должна быть объектом")
            if not str(node.get("role") or "").strip():
                raise PlatformRecommendationsError(f"У платформы {slug} нет role")
            for arr_key in ("frequency", "kpi", "content_rules", "formats", "signals", "risks"):
                if not isinstance(node.get(arr_key), list):
                    raise PlatformRecommendationsError(
                        f"Поле {arr_key} платформы {slug} должно быть массивом"
                    )
            if not node.get("frequency"):
                raise PlatformRecommendationsError(f"У платформы {slug} нет frequency")
            if not node.get("kpi"):
                raise PlatformRecommendationsError(f"У платформы {slug} нет KPI")

        if not isinstance(kb.get("universal_principles"), list) or not kb["universal_principles"]:
            raise PlatformRecommendationsError("universal_principles должен быть непустым массивом")
        if not isinstance(kb.get("pre_publish_checklist"), list) or not kb["pre_publish_checklist"]:
            raise PlatformRecommendationsError(
                "pre_publish_checklist должен быть непустым массивом"
            )

        _assert_no_secrets(kb)
        _assert_no_html(kb)
        return True

    # ------------------------------------------------------------------ #
    # Внутреннее                                                         #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _cross_platform_notes(kb: dict[str, Any], canonical: str) -> list[str]:
        """Строки «исходник → адаптация» для платформы из кросс-платформенного конвейера."""
        pipeline_key = _PIPELINE_KEY.get(canonical)
        if pipeline_key is None:
            return []
        notes: list[str] = []
        for source in kb.get("cross_platform_pipeline", {}).get("sources", []):
            adaptation = source.get("adaptations", {}).get(pipeline_key)
            if adaptation:
                notes.append(f"{source.get('source', '')} → {adaptation}")
        return notes


# ---------------------------------------------------------------------------- #
# Модульные помощники                                                          #
# ---------------------------------------------------------------------------- #


def _clean_slug(value: str) -> str:
    """Whitelist-очистка slug: только [a-z0-9_], без «/», «.», «\\» → path traversal невозможен."""
    import re

    return re.sub(r"[^a-z0-9_]", "", str(value).strip().lower())[:40]


@lru_cache(maxsize=1)
def _load_cached() -> dict[str, Any]:
    """Прочитать и распарсить локальный JSON один раз (read-only cache)."""
    try:
        raw = _RESOURCE_PATH.read_text(encoding="utf-8")
        data = json.loads(raw)
    except FileNotFoundError as exc:
        raise PlatformRecommendationsError("Ресурс рекомендаций не найден") from exc
    except (OSError, ValueError) as exc:
        logger.error("platform recommendations resource load failed: %s", type(exc).__name__)
        raise PlatformRecommendationsError("Не удалось загрузить базу рекомендаций") from exc
    if not isinstance(data, dict):
        raise PlatformRecommendationsError("Ресурс рекомендаций имеет неверный формат")
    missing = _REQUIRED_ROOT_KEYS - set(data)
    if missing:
        raise PlatformRecommendationsError(f"Нет обязательных корневых ключей: {sorted(missing)}")
    return data


def _iter_strings(obj: Any) -> Any:
    """Обойти все строковые значения структуры."""
    if isinstance(obj, dict):
        for value in obj.values():
            yield from _iter_strings(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_strings(value)
    elif isinstance(obj, str):
        yield obj


def _iter_keys(obj: Any) -> Any:
    """Обойти все ключи структуры."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield key
            yield from _iter_keys(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _iter_keys(value)


def _assert_no_secrets(kb: dict[str, Any]) -> None:
    for key in _iter_keys(kb):
        if isinstance(key, str) and key.lower() in _SECRET_LIKE:
            raise PlatformRecommendationsError(f"Секретоподобный ключ в ресурсе: {key}")


def _assert_no_html(kb: dict[str, Any]) -> None:
    for text in _iter_strings(kb):
        if "<" in text or ">" in text:
            raise PlatformRecommendationsError("В ресурсе не должно быть HTML/скриптов")


def get_platform_recommendations_service() -> PlatformRecommendationsService:
    """DI-фабрика сервиса рекомендаций (stateless, read-only)."""
    return PlatformRecommendationsService()
