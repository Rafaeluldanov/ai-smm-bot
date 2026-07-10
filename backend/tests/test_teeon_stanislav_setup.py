"""Тесты наполнения аккаунта Станислава проектом TEEON и календаря на сегодня.

Offline (SQLite in-memory), без сети/публикаций/секретов. Проверяют:
- авто-классификацию SEO-ключей (product/technology/cluster);
- полноту и совместимость примера payload + подстановку секретов;
- поиск аккаунта Станислава (успех/неоднозначность/fallback);
- preview/apply онбординга под аккаунтом;
- подготовку постов календаря (Telegram media-group + VK text-only) в dry-run/apply.
"""

import json
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.orm import Session

from app.repositories import (
    account_repository,
    media_asset_repository,
    post_repository,
    project_repository,
    user_repository,
)
from app.repositories import crm_bot_smm_repository as crm_repo
from app.schemas.media_asset import MediaAssetCreate
from app.schemas.saas_onboarding import SaasOnboardingPayload
from app.scripts import create_today_calendar_posts as cal
from app.scripts import setup_stanislav_teeon_project as setup
from app.services.media_grouping_service import MediaGroupingService

EXAMPLE_PATH = "backend/examples/saas_onboarding_teeon_stanislav_full.json"

FAKE_SETTINGS = SimpleNamespace(
    telegram_bot_token="FAKE_TG_TOKEN",
    telegram_default_channel_id="@teeon_merch",
    vk_access_token="FAKE_VK_TOKEN",
    vk_default_group_id="240102732",
    yandex_disk_public_smm_url="https://disk.yandex.ru/d/FAKE",
)


# --------------------------------------------------------------------------- #
# Классификация ключей                                                        #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("query", "product", "cluster"),
    [
        ("производство маек и футболок", "футболка", "футболки"),
        ("лонгслив оверсайз оптом", "лонгслив", "худи и толстовки"),
        ("пошив свитшотов на заказ", "свитшот", "худи и толстовки"),
        ("пошив толстовок оптом", "худи", "худи и толстовки"),
        ("производство кепок москва", "кепка", "кепки и бейсболки"),
        ("пошив бейсболок с логотипом", "бейсболка", "кепки и бейсболки"),
        ("жилетки купить опт", "жилетка", "жилетки и куртки"),
        ("куртки оптом от производителя россия", "куртка", "жилетки и куртки"),
        ("производство дождевиков на заказ", "дождевик", "дождевики"),
        ("пошив мерча в москве", "мерч", "мерч"),
    ],
)
def test_classify_products_and_clusters(query: str, product: str, cluster: str) -> None:
    got_product, _tech, got_cluster = setup.classify_keyword(query)
    assert got_product == product
    assert got_cluster == cluster


def test_classify_technology_detection() -> None:
    assert setup.classify_keyword("нанесение dtf на футболки")[1] == "DTF-печать"
    assert setup.classify_keyword("вышивка логотипа на худи")[1] == "вышивка"
    assert setup.classify_keyword("шелкография на футболках")[1] == "шелкография"


def test_all_raw_keywords_get_a_cluster() -> None:
    for query, _freq in setup.RAW_KEYWORDS:
        _p, _t, cluster = setup.classify_keyword(query)
        assert cluster  # кластер всегда заполнен


# --------------------------------------------------------------------------- #
# Пример payload и подстановка секретов                                       #
# --------------------------------------------------------------------------- #


def test_example_payload_structure() -> None:
    payload = setup.build_example_payload()
    assert payload["company"]["company_name"] == "TEEON"
    assert payload["project"]["project_slug"] == "teeon"
    assert len(payload["keywords"]) == len(setup.RAW_KEYWORDS)
    assert [p["platform_type"] for p in payload["platforms"]] == ["telegram", "vk"]
    titles = [c["title"] for c in payload["promotion_categories"]]
    assert "Футболки и майки" in titles and len(titles) == 5
    assert len(payload["publishing_plans"]) == 2
    # Каждый ключ обогащён priority=frequency и intent=commercial.
    for kw in payload["keywords"]:
        assert kw["priority"] == kw["frequency"]
        assert kw["intent"] == "commercial"


def test_example_json_file_in_sync_and_secret_free() -> None:
    text = Path(EXAMPLE_PATH).read_text(encoding="utf-8")
    on_disk = json.loads(text)
    # Файл синхронизирован с генератором (ключи, категории, планы).
    assert len(on_disk["keywords"]) == len(setup.build_example_payload()["keywords"])
    # Плейсхолдеры вместо секретов — токенов в репозитории нет.
    assert "{{telegram_bot_token}}" in text
    assert "{{vk_access_token}}" in text
    assert "{{yandex_disk_public_smm_url}}" in text
    for leak in ("FAKE_TG_TOKEN", "FAKE_VK_TOKEN"):
        assert leak not in text


def test_substitute_secrets_and_today_plans() -> None:
    payload = setup.build_example_payload()
    resolved = setup.substitute_secrets(payload, FAKE_SETTINGS)
    telegram = resolved["platforms"][0]
    assert telegram["api_key"] == "FAKE_TG_TOKEN"
    assert telegram["external_id"] == "@teeon_merch"
    assert resolved["platforms"][1]["external_id"] == "240102732"
    assert resolved["media_sources"][0]["url"] == "https://disk.yandex.ru/d/FAKE"

    today = date(2026, 7, 9)
    setup.apply_today_to_plans(resolved, today)
    for plan in resolved["publishing_plans"]:
        assert plan["start_date"] == "2026-07-09"
        assert plan["end_date"] == "2026-07-09"
        assert plan["weekdays"] == [today.weekday()]
    # Полный payload остаётся валидным для onboarding-сервиса.
    SaasOnboardingPayload.model_validate(resolved)


# --------------------------------------------------------------------------- #
# Поиск аккаунта Станислава                                                   #
# --------------------------------------------------------------------------- #


def _user(db: Session, email: str, full_name: str) -> Any:
    return user_repository.create_user(db, email, "hash", full_name=full_name)


def _account(db: Session, user_id: int, slug: str, name: str = "WS") -> Any:
    return account_repository.create_account(db, name, slug, user_id)


def test_resolve_account_by_name(db_session: Session) -> None:
    user = _user(db_session, "stan@example.com", "Станислав Шапокляк")
    account = _account(db_session, user.id, "stan-ws")
    assert setup.resolve_target_account(db_session).id == account.id


def test_resolve_account_ambiguous_stops(db_session: Session) -> None:
    u1 = _user(db_session, "s1@example.com", "Станислав Один")
    u2 = _user(db_session, "s2@example.com", "Станислав Два")
    _account(db_session, u1.id, "s1-ws")
    _account(db_session, u2.id, "s2-ws")
    with pytest.raises(setup.AccountResolutionError):
        setup.resolve_target_account(db_session)


def test_resolve_account_fallback_to_freshest(db_session: Session) -> None:
    u1 = _user(db_session, "a@example.com", "Иван")
    u2 = _user(db_session, "b@example.com", "Пётр")
    _account(db_session, u1.id, "first-ws")
    newest = _account(db_session, u2.id, "second-ws")
    # Без Станислава — берём самый свежий аккаунт.
    assert setup.resolve_target_account(db_session).id == newest.id


def test_resolve_account_none_raises(db_session: Session) -> None:
    with pytest.raises(setup.AccountResolutionError):
        setup.resolve_target_account(db_session)


# --------------------------------------------------------------------------- #
# Полный прогон: онбординг + календарь                                         #
# --------------------------------------------------------------------------- #


def _setup_account(db_session: Session) -> Any:
    user = _user(db_session, "stanislav@example.com", "Станислав")
    return _account(db_session, user.id, "teeon-ws")


def _run_setup(db_session: Session, account: Any, apply: bool) -> Any:
    args = SimpleNamespace(
        payload_path=EXAMPLE_PATH,
        account_id=account.id,
        dry_run="false" if apply else "true",
        apply="true" if apply else "false",
    )
    return setup.run(db_session, FAKE_SETTINGS, args)


def test_setup_preview_then_apply(db_session: Session) -> None:
    account = _setup_account(db_session)

    preview = _run_setup(db_session, account, apply=False)
    assert preview is not None and preview.dry_run is True
    assert preview.project_id is None
    assert preview.crm.keywords_count == len(setup.RAW_KEYWORDS)
    assert len(preview.crm.resources) == 2
    # Проект ещё не создан (dry-run).
    assert project_repository.get_project_by_slug(db_session, "teeon") is None

    applied = _run_setup(db_session, account, apply=True)
    assert applied is not None and applied.dry_run is False
    assert applied.project_id is not None
    project = project_repository.get_project_by_slug(db_session, "teeon")
    assert project is not None and project.account_id == account.id
    config = crm_repo.get_config_by_project_id(db_session, project.id)
    assert config is not None
    titles = {c.title for c in crm_repo.list_categories_by_config(db_session, config.id)}
    assert "Футболки и майки" in titles
    # Живые публикации не включены ни на одном ресурсе.
    assert all(not r.live_enabled for r in crm_repo.list_resources_by_config(db_session, config.id))


def _seed_tshirt_media(db_session: Session, project_id: int, count: int) -> None:
    for index in range(count):
        media_asset_repository.create_media_asset(
            db_session,
            MediaAssetCreate(
                project_id=project_id,
                file_name=f"tshirt_{index}.jpg",
                yandex_disk_path=f"public://yandex/teeon/teeon/tshirt_{index}.jpg",
                source_type="internal",
                license_type="company_owned",
                status="approved",
                tags={"products": ["футболка"]},
            ),
        )


def _calendar_args(account_id: int, dry_run: bool) -> SimpleNamespace:
    return SimpleNamespace(
        account_id=account_id,
        project_slug="teeon",
        date="today",
        telegram_media_posts=2,
        vk_text_posts=1,
        dry_run="true" if dry_run else "false",
    )


def test_today_calendar_dry_run_writes_nothing(db_session: Session) -> None:
    account = _setup_account(db_session)
    _run_setup(db_session, account, apply=True)
    project = project_repository.get_project_by_slug(db_session, "teeon")
    assert project is not None
    _seed_tshirt_media(db_session, project.id, 4)

    before = len(post_repository.list_posts(db_session, project_id=project.id))
    result = cal.run(db_session, MediaGroupingService(), _calendar_args(account.id, dry_run=True))
    after = len(post_repository.list_posts(db_session, project_id=project.id))

    assert result is not None and result["dry_run"] is True
    assert after == before  # dry-run ничего не пишет в БД
    assert len(result["telegram_previews"]) == 2
    assert len(result["vk_previews"]) == 1
    assert result["telegram_post_ids"] == [] and result["vk_post_ids"] == []


def test_today_calendar_apply_creates_review_posts(db_session: Session) -> None:
    account = _setup_account(db_session)
    _run_setup(db_session, account, apply=True)
    project = project_repository.get_project_by_slug(db_session, "teeon")
    assert project is not None
    _seed_tshirt_media(db_session, project.id, 4)

    result = cal.run(db_session, MediaGroupingService(), _calendar_args(account.id, dry_run=False))
    assert result is not None and result["dry_run"] is False
    assert len(result["telegram_post_ids"]) == 2
    assert len(result["vk_post_ids"]) == 1

    posts = {p.id: p for p in post_repository.list_posts(db_session, project_id=project.id)}
    # Telegram: media-group посты с media_files/media_asset_ids/media_count.
    for pid in result["telegram_post_ids"]:
        notes = posts[pid].generation_notes
        assert posts[pid].status == "needs_review"
        assert notes.get("platform_target") == "telegram"
        assert notes.get("media_policy") == "media_group"
        assert notes.get("media_count") and notes.get("media_asset_ids")
        assert "media_files" in notes
    # VK: text-only без картинок.
    for pid in result["vk_post_ids"]:
        post = posts[pid]
        notes = post.generation_notes
        assert post.status == "needs_review"
        assert post.media_asset_id is None
        assert notes.get("media_policy") == "text_only"
        assert notes.get("media_count") == 0
        assert post.vk_text and not post.telegram_text


def test_today_calendar_wrong_account_blocked(db_session: Session) -> None:
    account = _setup_account(db_session)
    _run_setup(db_session, account, apply=True)
    # Чужой account_id — проект принадлежит другому аккаунту.
    result = cal.run(
        db_session, MediaGroupingService(), _calendar_args(account.id + 999, dry_run=True)
    )
    assert result is None


def test_today_calendar_no_media_warns(db_session: Session) -> None:
    account = _setup_account(db_session)
    _run_setup(db_session, account, apply=True)
    # Медиа не синхронизированы — Telegram-посты не подготовлены, но VK text-only есть.
    result = cal.run(db_session, MediaGroupingService(), _calendar_args(account.id, dry_run=True))
    assert result is not None
    assert result["telegram_previews"] == []
    assert result["warnings"]
    assert len(result["vk_previews"]) == 1
