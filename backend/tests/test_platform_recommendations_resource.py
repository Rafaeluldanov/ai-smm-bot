"""Тесты JSON-ресурса базы SMM-рекомендаций Botfleet (v1.0.1, offline).

Структурные инварианты ресурса: валидный UTF-8 JSON, версия, product=Botfleet, нет TEEON, все 10
каналов, уникальные canonical slug, 8 принципов, 8 пунктов чек-листа, 7 дней недельного ритма,
нет HTML/скриптов, нет секретов.
"""

import json
from pathlib import Path

_RESOURCE = (
    Path(__file__).resolve().parent.parent
    / "app"
    / "resources"
    / "botfleet_smm_recommendations_2026.json"
)

_CHANNELS = {
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
}
_DAYS = {"Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"}
_SECRET_KEYS = {"password", "secret", "token", "api_key", "apikey", "access_key", "refresh"}


def _load() -> dict:
    return json.loads(_RESOURCE.read_text(encoding="utf-8"))


def test_resource_is_valid_utf8_json() -> None:
    data = _load()
    assert isinstance(data, dict)


def test_version_present() -> None:
    assert str(_load().get("version") or "").strip()


def test_product_is_botfleet() -> None:
    assert _load()["product"] == "Botfleet"


def test_no_teeon_anywhere() -> None:
    blob = _RESOURCE.read_text(encoding="utf-8").lower()
    assert "teeon" not in blob
    assert "тион" not in blob


def test_all_ten_channels_present() -> None:
    assert set(_load()["platforms"].keys()) == _CHANNELS


def test_canonical_slugs_unique() -> None:
    keys = list(_load()["platforms"].keys())
    assert len(keys) == len(set(keys)) == 10


def test_universal_principles_exactly_eight() -> None:
    assert len(_load()["universal_principles"]) == 8


def test_checklist_has_eight_items() -> None:
    assert len(_load()["pre_publish_checklist"]) == 8


def test_weekly_rhythm_seven_days() -> None:
    platforms = _load()["weekly_rhythm"]["platforms"]
    assert platforms
    for slug, row in platforms.items():
        assert set(row.keys()) == _DAYS, slug


def test_no_html_or_script() -> None:
    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)
        elif isinstance(obj, str):
            assert "<" not in obj and ">" not in obj

    walk(_load())


def test_no_secret_like_keys() -> None:
    def keys(obj: object) -> list:
        out: list = []
        if isinstance(obj, dict):
            for k, v in obj.items():
                out.append(k)
                out.extend(keys(v))
        elif isinstance(obj, list):
            for v in obj:
                out.extend(keys(v))
        return out

    assert not [k for k in keys(_load()) if isinstance(k, str) and k.lower() in _SECRET_KEYS]
