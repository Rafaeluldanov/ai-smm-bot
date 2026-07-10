"""CLI: наполнить SaaS-аккаунт Станислава проектом TEEON (SEO-ключи, платформы,
категории, план на сегодня).

Поведение:
1. Находит аккаунт Станислава (``users.full_name ilike '%Станислав%'``; при
   отсутствии — самый свежий аккаунт, созданный через UI). При неоднозначности
   (несколько аккаунтов Станислава) — печатает список и останавливается, ничего
   не создавая.
2. Формирует payload из ``backend/examples/saas_onboarding_teeon_stanislav_full.json``.
3. Подставляет секреты из ``settings`` (telegram/vk/yandex) — секреты не печатаются.
4. Проставляет план публикаций на сегодня (``date.today()`` в Europe/Moscow).
5. Делает preview (dry-run). При ``--apply true`` — реальный apply.

Ничего не публикует и не включает live-публикации.

Запуск:
  PYTHONPATH=backend .venv/bin/python -m app.scripts.setup_stanislav_teeon_project --dry-run true
  PYTHONPATH=backend .venv/bin/python -m app.scripts.setup_stanislav_teeon_project --apply true
"""

import argparse
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_saas_onboarding_service
from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.models.account import Account
from app.models.user import User
from app.repositories import account_repository
from app.schemas.saas_onboarding import SaasOnboardingPayload, SaasOnboardingResult
from app.services.crm_bot_smm_form_service import CrmOnboardingValidationError
from app.services.saas_onboarding_service import SaasOnboardingError

DEFAULT_PAYLOAD_PATH = "backend/examples/saas_onboarding_teeon_stanislav_full.json"
MOSCOW = ZoneInfo("Europe/Moscow")

# Плейсхолдеры вида ``{{name}}`` в JSON подставляются ТОЛЬКО из этого белого списка
# (секреты в репозитории не хранятся и не печатаются).
SECRET_PLACEHOLDERS = {
    "telegram_bot_token",
    "telegram_default_channel_id",
    "vk_access_token",
    "vk_default_group_id",
    "yandex_disk_public_smm_url",
}


# --------------------------------------------------------------------------- #
# SEO-ключи: сырьё и авто-классификация продукт/технология/кластер             #
# --------------------------------------------------------------------------- #

# (запрос, частотность) — из задания v0.2.4.
RAW_KEYWORDS: list[tuple[str, int]] = [
    ("производство маек и футболок", 9),
    ("жилетки купить опт", 9),
    ("производство кепок москва", 9),
    ("контрактное производство футболок", 9),
    ("пошив стеганой жилетки", 9),
    ("лонгслив оверсайз оптом", 9),
    ("куртки оптом от производителя россия", 8),
    ("кепки оптом спб", 8),
    ("пошив лонгсливов оптом", 8),
    ("производство кепок спб", 8),
    ("пошив свитшотов на заказ", 7),
    ("худи футболки оптом", 7),
    ("производство корпоративных футболок", 7),
    ("заказать пошив футболок оптом", 6),
    ("пошив бейсболок с логотипом", 6),
    ("заказать пошив худи", 6),
    ("пошив кепок на заказ спб", 6),
    ("производство дождевиков на заказ", 6),
    ("коммерческое предложение на пошив футболок", 6),
    ("производство курток оптом", 5),
    ("заказать кепки оптом", 5),
    ("пошив футболок с логотипом на заказ", 5),
    ("пошив лонгсливов на заказ", 5),
    ("производство дождевиков в россии", 5),
    ("жилетка производство россия", 5),
    ("пошив толстовок оптом", 4),
    ("пошив кепок оптом", 4),
    ("свитшоты под нанесение оптом", 4),
    ("пошив толстовок на заказ оптом", 4),
    ("производство курток на заказ", 4),
    ("пошив мерча на заказ москва", 4),
    ("сколько стоит пошив футболки на производстве", 4),
    ("толстовка пошив оптом", 4),
    ("цех пошива футболок", 4),
    ("пошив футболок по индивидуальному дизайну", 4),
    ("дождевики eva оптом", 3),
    ("футболки на заказ для компаний", 3),
    ("свитшоты оптом на заказ", 3),
    ("пошив мерча на заказ производство", 3),
    ("толстовки на молнии оптом", 2),
    ("пошив бейсболок оптом", 2),
    ("пошив дождевиков оптом", 2),
    ("кепки оптом с логотипом", 2),
    ("кепки с логотипом оптом", 2),
    ("пошив курток спецодежды", 2),
    ("толстовки оптом с нанесением", 2),
    ("бейсболки с логотипом оптом", 1),
    ("дождевики с логотипом оптом", 1),
    ("пошив мерча в москве", 1),
    ("заказ худи оптом", 1),
    ("пошив и брендирование футболок", 1),
    ("производство бейсболок москва с логотипом", 1),
    ("пошив свитшотов оптом", 0),
    ("пошив свитшотов на заказ оптом", 0),
    ("пошив кепок под заказ", 0),
    ("пошив и брендирование футболок москва", 0),
    ("производство промо футболок", 0),
    ("футболка сигнальная пошив", 0),
    ("футболка сигнальная оптом производство", 0),
    ("пошив зип толстовок", 0),
    ("пошив зип худи под заказ", 0),
    ("худи на заказ для компаний", 0),
    ("производство корпоративных курток", 0),
    ("производство дождевиков из ева с логотипом", 0),
]

# Продукт → кластер. Порядок важен: первое совпадение по основе слова выигрывает.
_PRODUCT_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("футбол",), "футболка", "футболки"),
    (("майк", "маек"), "майка", "футболки"),
    (("поло",), "поло", "футболки"),
    (("худи",), "худи", "худи и толстовки"),
    (("свитшот",), "свитшот", "худи и толстовки"),
    (("лонгслив",), "лонгслив", "худи и толстовки"),
    (("толстов",), "худи", "худи и толстовки"),
    (("бейсбол",), "бейсболка", "кепки и бейсболки"),
    (("кеп",), "кепка", "кепки и бейсболки"),
    (("жилет",), "жилетка", "жилетки и куртки"),
    (("куртк", "курток"), "куртка", "жилетки и куртки"),
    (("дождевик",), "дождевик", "дождевики"),
    (("мерч",), "мерч", "мерч"),
]

# Технология по вхождению в запрос.
_TECHNOLOGY_RULES: list[tuple[tuple[str, ...], str]] = [
    (("dtf", "дтф"), "DTF-печать"),
    (("вышив",), "вышивка"),
    (("гравиров",), "гравировка"),
    (("шелкограф",), "шелкография"),
    (("уф-печат", "уф печат"), "УФ-печать"),
]


def classify_keyword(query: str) -> tuple[str | None, str | None, str]:
    """Определить (product, technology, cluster) для SEO-запроса по эвристикам.

    product/technology — ``None``, если не распознаны. cluster всегда заполнен:
    от продукта; иначе «технологии нанесения» (если есть технология),
    «производство / пошив» (если есть соответствующие слова) или «мерч».
    """
    text = query.lower()

    product: str | None = None
    cluster = ""
    for stems, prod, clus in _PRODUCT_RULES:
        if any(stem in text for stem in stems):
            product, cluster = prod, clus
            break

    technology: str | None = None
    for stems, tech in _TECHNOLOGY_RULES:
        if any(stem in text for stem in stems):
            technology = tech
            break

    if not cluster:
        if technology is not None:
            cluster = "технологии нанесения"
        elif any(word in text for word in ("производ", "пошив", "цех")):
            cluster = "производство / пошив"
        else:
            cluster = "мерч"

    return product, technology, cluster


def build_keyword_entries() -> list[dict[str, Any]]:
    """Собрать список ключей с авто-заполнением product/technology/cluster/priority."""
    entries: list[dict[str, Any]] = []
    for query, frequency in RAW_KEYWORDS:
        product, technology, cluster = classify_keyword(query)
        entries.append(
            {
                "query": query,
                "frequency": frequency,
                "priority": frequency,
                "intent": "commercial",
                "product": product,
                "technology": technology,
                "cluster": cluster,
            }
        )
    return entries


# --------------------------------------------------------------------------- #
# Полный payload (шаблон с плейсхолдерами секретов)                            #
# --------------------------------------------------------------------------- #


def build_example_payload() -> dict[str, Any]:
    """Собрать полный SaaS-онбординг payload TEEON с плейсхолдерами секретов.

    Секреты (токены/URL) представлены как ``{{name}}`` и подставляются из
    ``settings`` в рантайме — в файле/репозитории токенов нет.
    """
    return {
        "company": {
            "company_name": "TEEON",
            "business_description": (
                "Производство корпоративной одежды, промо-одежды и мерча: футболки, "
                "худи, свитшоты, лонгсливы, поло, кепки, жилетки, куртки, дождевики. "
                "Нанесение логотипов: DTF, вышивка, шелкография, УФ-печать, гравировка."
            ),
            "has_website": True,
            "website_url": "https://teeon.ru",
            "geography": ["Москва", "Санкт-Петербург", "Россия"],
            "brand_tone": "экспертный, деловой, продающий",
        },
        "project": {
            "project_slug": "teeon",
            "project_name": "TEEON — корпоративный мерч и одежда",
            "promoted_resource_url": "https://teeon.ru",
            "default_site_url": "https://teeon.ru",
        },
        "keywords": build_keyword_entries(),
        "media_sources": [
            {
                "source_type": "yandex_disk",
                "title": "Яндекс Диск TEEON — медиа",
                "url": "{{yandex_disk_public_smm_url}}",
                "root_folder": "teeon",
                "media_tags": [
                    "футболка",
                    "футболка с логотипом",
                    "корпоративный мерч",
                    "производство",
                    "швейный цех",
                    "DTF-печать",
                    "вышивка",
                    "шелкография",
                ],
            }
        ],
        "platforms": [
            {
                "platform_type": "telegram",
                "title": "Telegram TEEON",
                "external_id": "{{telegram_default_channel_id}}",
                "api_key": "{{telegram_bot_token}}",
                "live_enabled": False,
                "tags": ["telegram", "teeon", "media_group"],
                "keywords": ["футболки", "мерч", "нанесение логотипа"],
                "media_policy": "media_group",
            },
            {
                "platform_type": "vk",
                "title": "VK TEEON",
                "external_id": "{{vk_default_group_id}}",
                "api_key": "{{vk_access_token}}",
                "live_enabled": False,
                "tags": ["vk", "teeon", "text_only_until_photo_token"],
                "keywords": ["футболки", "мерч", "производство"],
                "media_policy": "text_only",
                "reason": "VK photo upload disabled until correct user token is available",
            },
        ],
        "promotion_categories": [
            {
                "title": "Футболки и майки",
                "description": "Продвижение футболок, маек и поло с нанесением логотипа.",
                "media_tags": [
                    "футболка",
                    "футболка с логотипом",
                    "швейный цех",
                    "корпоративный мерч",
                ],
                "product_priorities": {"футболка": 100, "майка": 70, "поло": 70},
                "technology_priorities": {"DTF-печать": 100, "вышивка": 90, "шелкография": 85},
                "default_site_url": "https://teeon.ru/catalog/futbolki",
                "cta": "Оставьте заявку — рассчитаем тираж и подберём технологию нанесения.",
            },
            {
                "title": "Худи, свитшоты, лонгсливы",
                "description": "Продвижение худи, свитшотов и лонгсливов.",
                "media_tags": ["худи", "свитшот", "лонгслив", "корпоративный мерч"],
                "product_priorities": {"худи": 100, "свитшот": 90, "лонгслив": 80},
                "default_site_url": "https://teeon.ru/catalog/hudi",
                "cta": "Рассчитаем тираж худи и свитшотов с нанесением.",
            },
            {
                "title": "Кепки и бейсболки",
                "description": "Продвижение кепок и бейсболок с логотипом.",
                "media_tags": ["кепка", "бейсболка", "логотип"],
                "product_priorities": {"кепка": 100, "бейсболка": 90},
                "default_site_url": "https://teeon.ru",
                "cta": "Закажите кепки и бейсболки с логотипом.",
            },
            {
                "title": "Жилетки, куртки, дождевики",
                "description": "Продвижение жилеток, курток и дождевиков.",
                "media_tags": ["жилетка", "куртка", "дождевик", "спецодежда"],
                "product_priorities": {"жилетка": 100, "куртка": 90, "дождевик": 80},
                "default_site_url": "https://teeon.ru",
                "cta": "Рассчитаем производство жилеток, курток и дождевиков.",
            },
            {
                "title": "Технологии нанесения",
                "description": "Продвижение технологий нанесения логотипов.",
                "media_tags": ["DTF-печать", "вышивка", "гравировка", "УФ-печать", "шелкография"],
                "technology_priorities": {
                    "DTF-печать": 100,
                    "вышивка": 95,
                    "шелкография": 85,
                    "УФ-печать": 75,
                    "гравировка": 70,
                },
                "default_site_url": "https://teeon.ru/branding/dtf-pechat",
                "cta": "Подберём технологию нанесения под ваш тираж.",
            },
        ],
        # Даты/дни недели плана проставляются на сегодня в рантайме (Europe/Moscow).
        "publishing_plans": [
            {
                "title": "Telegram — футболки с фото",
                "category_title": "Футболки и майки",
                "platforms": ["telegram"],
                "weekdays": [],
                "posts_per_day": 2,
                "publish_times": ["12:00", "16:00"],
                "mode": "semi_auto",
                "timezone": "Europe/Moscow",
                "start_date": None,
                "end_date": None,
                "media_policy": "media_group",
                "tag": "футболка",
            },
            {
                "title": "VK — футболки text-only",
                "category_title": "Футболки и майки",
                "platforms": ["vk"],
                "weekdays": [],
                "posts_per_day": 1,
                "publish_times": ["17:30"],
                "mode": "semi_auto",
                "timezone": "Europe/Moscow",
                "start_date": None,
                "end_date": None,
                "media_policy": "text_only",
                "tag": "футболка",
            },
        ],
        "billing": {
            "tariff_plan_slug": "starter",
            "starting_topup_amount": 200,
            "accept_terms": True,
        },
    }


def substitute_secrets(obj: Any, settings: Settings) -> Any:
    """Рекурсивно заменить плейсхолдеры ``{{name}}`` значениями из settings.

    Заменяются только строки-плейсхолдеры из белого списка ``SECRET_PLACEHOLDERS``.
    """
    if isinstance(obj, dict):
        return {key: substitute_secrets(value, settings) for key, value in obj.items()}
    if isinstance(obj, list):
        return [substitute_secrets(item, settings) for item in obj]
    if isinstance(obj, str) and obj.startswith("{{") and obj.endswith("}}"):
        name = obj[2:-2].strip()
        if name in SECRET_PLACEHOLDERS:
            return str(getattr(settings, name, "") or "")
    return obj


def apply_today_to_plans(payload_dict: dict[str, Any], today: date) -> None:
    """Проставить план публикаций на сегодня (даты и день недели)."""
    weekday = today.weekday()
    for plan in payload_dict.get("publishing_plans", []):
        plan["start_date"] = today.isoformat()
        plan["end_date"] = today.isoformat()
        plan["weekdays"] = [weekday]


def moscow_today() -> date:
    """Сегодняшняя дата в Europe/Moscow."""
    return datetime.now(MOSCOW).date()


# --------------------------------------------------------------------------- #
# Поиск аккаунта Станислава                                                   #
# --------------------------------------------------------------------------- #


class AccountResolutionError(Exception):
    """Аккаунт не найден или найден неоднозначно."""


def resolve_target_account(db: Session) -> Account:
    """Найти аккаунт Станислава; при неоднозначности — остановиться."""
    users = db.scalars(select(User).where(User.full_name.ilike("%Станислав%"))).all()
    accounts: list[Account] = []
    seen: set[int] = set()
    for user in users:
        # Аккаунты по членству И по владению (owner) — на случай отсутствия членства.
        owned = db.scalars(select(Account).where(Account.owner_user_id == user.id)).all()
        for account in [*account_repository.list_accounts_for_user(db, user.id), *owned]:
            if account.status != "deleted" and account.id not in seen:
                seen.add(account.id)
                accounts.append(account)

    if len(accounts) == 1:
        return accounts[0]
    if len(accounts) > 1:
        listing = "; ".join(f"#{a.id} {a.name} ({a.slug})" for a in accounts)
        raise AccountResolutionError(
            f"Найдено несколько аккаунтов Станислава — уточните вручную (--account-id): {listing}"
        )

    # Fallback: самый свежий аккаунт (созданный через UI).
    all_accounts = db.scalars(
        select(Account)
        .where(Account.status != "deleted")
        .order_by(Account.created_at.desc(), Account.id.desc())
    ).all()
    if not all_accounts:
        raise AccountResolutionError(
            "Аккаунтов нет — сначала зарегистрируйтесь через /ui/register."
        )
    return all_accounts[0]


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов настройки проекта TEEON для Станислава."""
    parser = argparse.ArgumentParser(description="Наполнить аккаунт Станислава проектом TEEON")
    parser.add_argument("--payload-path", default=DEFAULT_PAYLOAD_PATH)
    parser.add_argument(
        "--account-id", type=int, default=None, help="явный account_id (в обход поиска)"
    )
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--apply", default="false")
    parser.add_argument("--emit-example", default=None, help="сгенерировать пример JSON и выйти")
    return parser


def load_payload_dict(payload_path: str, settings: Settings, today: date) -> dict[str, Any]:
    """Загрузить payload из файла, подставить секреты и план на сегодня."""
    raw = json.loads(Path(payload_path).read_text(encoding="utf-8"))
    resolved: dict[str, Any] = substitute_secrets(raw, settings)
    apply_today_to_plans(resolved, today)
    return resolved


def _print_result(result: SaasOnboardingResult, account: Account, calendar_cmd: str) -> None:
    mode = "dry-run (без записи)" if result.dry_run else "apply (записано)"
    crm = result.crm
    print(f"\nTEEON онбординг: {mode}")
    print(f"  account_id={account.id} ({account.name} / {account.slug})")
    print(f"  project_id={result.project_id} slug={crm.project.slug}")
    print("  платформы (секрет не печатается):")
    for resource in crm.resources:
        key = "ключ задан" if resource.api_key_present else "без ключа"
        print(f"    - {resource.resource_type}: {resource.title} [{key}]")
    print(f"  ключей: {crm.keywords_count}")
    print(f"  медиа-источников: {crm.content_sources_count}")
    print(f"  категорий: {len(crm.categories)} — " + ", ".join(c.title for c in crm.categories))
    print(f"  планов публикаций в конфиге: {len(crm.plans)}")
    for plan in crm.plans:
        print(
            f"    - {plan.category_title}: {plan.platforms} "
            f"weekdays={plan.weekdays} posts/day={plan.posts_per_day} mode={plan.mode}"
        )
    print(f"  баланс биллинга: {result.billing_balance_units} units")
    for warning in result.warnings:
        print(f"  ! {warning}")
    print("\nСледующие шаги (ничего не публикуется автоматически):")
    if result.dry_run:
        print("  make saas-teeon-stanislav-apply")
    print(f"  {calendar_cmd}")


def run(db: Session, settings: Settings, args: argparse.Namespace) -> SaasOnboardingResult | None:
    """Ядро: разрешить аккаунт, собрать payload, preview/apply. Вернуть результат."""
    if args.account_id is not None:
        account = account_repository.get_account_by_id(db, args.account_id)
        if account is None:
            print(f"Ошибка: аккаунт #{args.account_id} не найден.")
            return None
    else:
        try:
            account = resolve_target_account(db)
        except AccountResolutionError as exc:
            print(f"Ошибка: {exc}")
            return None

    today = moscow_today()
    payload_dict = load_payload_dict(args.payload_path, settings, today)
    payload = SaasOnboardingPayload.model_validate(payload_dict)

    # Apply только при --apply true; иначе preview (dry-run по умолчанию).
    do_apply = _parse_bool(args.apply)

    service = get_saas_onboarding_service()
    try:
        if do_apply:
            result = service.apply(db, account.id, payload, allow_live=False)
        else:
            result = service.preview(db, account.id, payload, allow_live=False)
    except (SaasOnboardingError, CrmOnboardingValidationError) as exc:
        print(f"Ошибка онбординга: {exc}")
        return None

    calendar_cmd = (
        "PYTHONPATH=backend .venv/bin/python -m app.scripts.create_today_calendar_posts "
        f"--account-id {account.id} --project-slug teeon --date today "
        "--telegram-media-posts 2 --vk-text-posts 1 --dry-run true"
    )
    _print_result(result, account, calendar_cmd)
    return result


def main() -> None:
    """Точка входа CLI настройки проекта TEEON для Станислава."""
    args = build_parser().parse_args()

    if args.emit_example:
        Path(args.emit_example).write_text(
            json.dumps(build_example_payload(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Пример payload записан: {args.emit_example}")
        return

    settings = get_settings()
    factory = get_sessionmaker()
    with factory() as db:
        run(db, settings, args)


if __name__ == "__main__":
    main()
