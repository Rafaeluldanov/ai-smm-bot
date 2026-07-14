"""CLI демо клиентского онбординга (полный проход 5 шагов) — v0.6.4.

Запуск:
  make onboarding-demo user_id=1
  python -m app.scripts.onboarding_demo --user-id 1

Проходит все 5 шагов с демо-данными и завершает онбординг. Ничего не публикует; live НЕ включает
(после демо система READY, но LIVE=OFF). Требует существующего пользователя (--user-id).
"""

import argparse

from app.db.session import get_sessionmaker
from app.services.client_onboarding_service import (
    ClientOnboardingError,
    get_client_onboarding_service,
)


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов демо онбординга."""
    parser = argparse.ArgumentParser(description="Демо клиентского онбординга (5 шагов)")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--company", type=str, default="Демо-бизнес")
    return parser


def main() -> None:
    """Точка входа CLI демо онбординга."""
    args = build_parser().parse_args()
    service = get_client_onboarding_service()
    factory = get_sessionmaker()
    with factory() as db:
        try:
            start = service.start_onboarding(db, args.user_id, company_name=args.company)
            sid = start["session_id"]
            print(f"start:      session {sid}, project {start['project_id']}")
            b = service.complete_business_step(
                db,
                sid,
                {
                    "company_name": args.company,
                    "industry": "demo",
                    "description": "демо",
                    "target_audience": "все",
                },
                args.user_id,
            )
            print(f"business:   {b['completion_percent']}%")
            m = service.complete_media_step(
                db,
                sid,
                {"yandex_disk_url": "https://disk.yandex.ru/d/demo", "folder": "SMM"},
                args.user_id,
            )
            print(f"media:      {m['completion_percent']}%")
            p = service.complete_platform_step(db, sid, {"telegram": True}, args.user_id)
            print(f"platforms:  {p['completion_percent']}%")
            g = service.complete_goal_step(
                db, sid, {"goal": "sales", "frequency": "3_week"}, args.user_id
            )
            print(f"goal:       {g['completion_percent']}%")
            f = service.finish_onboarding(db, sid, args.user_id)
        except ClientOnboardingError as exc:
            print(f"Ошибка: {exc}")
            return
    print(f"finish:     status={f['status']}, live_enabled={f['live_enabled']}")
    print(f"readiness:  {f['readiness'].get('status')}")
    print(f"next:       {f['next_action']}")
    print("Демо завершено. READY, но LIVE=OFF (реальная публикация не включалась).")


if __name__ == "__main__":
    main()
