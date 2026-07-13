"""CLI сводки безопасности уведомлений (read-only, без записи).

Запуск:
  make notification-safety-dashboard user_id=1
  python -m app.scripts.notification_safety_dashboard --user-id 1 [--project-id 1]

Секреты/сырые URL/адреса не печатаются; внешней доставки нет.
"""

import argparse

from app.api.deps import (
    get_notification_rate_limit_service,
    get_notification_suppression_service,
    get_notification_unsubscribe_service,
    get_webhook_subscription_service,
)
from app.db.session import get_sessionmaker


def build_parser() -> argparse.ArgumentParser:
    """Собрать парсер аргументов сводки безопасности."""
    parser = argparse.ArgumentParser(description="Сводка безопасности уведомлений")
    parser.add_argument("--user-id", type=int, required=True)
    parser.add_argument("--project-id", type=int, default=None)
    return parser


def main() -> None:
    """Точка входа CLI сводки безопасности."""
    args = build_parser().parse_args()
    unsub = get_notification_unsubscribe_service()
    supp = get_notification_suppression_service()
    rate = get_notification_rate_limit_service()
    webhook = get_webhook_subscription_service()
    factory = get_sessionmaker()
    with factory() as db:
        opt_outs = unsub.list_opt_outs(db, args.user_id)
        sup_dash = supp.build_suppression_dashboard(
            db, project_id=args.project_id, user_id=args.user_id
        )
        rl_dash = rate.build_rate_limit_dashboard(
            db, project_id=args.project_id, user_id=args.user_id
        )
        webhooks = (
            webhook.list_subscriptions(db, project_id=args.project_id)
            if args.project_id is not None
            else []
        )
    print(f"Безопасность уведомлений: пользователь #{args.user_id}")
    print(f"  отписок (active): {len(opt_outs)}")
    print(f"  подавлений: всего {sup_dash['total']} · активных {sup_dash['active']}")
    print(f"  лимит-бакетов: {len(rl_dash['buckets'])} · rate-limit включён: {rl_dash['enabled']}")
    print(f"  webhook-подписок проекта: {len(webhooks)} (URL/secret скрыты)")
    print("  Внешней доставки нет; сырые адреса/секреты не печатаются.")


if __name__ == "__main__":
    main()
