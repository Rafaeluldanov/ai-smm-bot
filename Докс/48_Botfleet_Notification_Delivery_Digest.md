# 48. Botfleet: доставка уведомлений и дайджесты (sandbox) (v0.5.1)

Слой поверх внутренних уведомлений ([47](47_Botfleet_Notifications_Mentions_Workload.md)):
**фундамент внешней доставки** уведомлений (email / Telegram / webhook) и **дайджесты** —
как **sandbox/mock**. Есть delivery-задачи, журнал доставки, retry/backoff, планировщик
дайджестов и настройки — но **реальная внешняя доставка выключена по умолчанию** и в MVP
ничего не отправляет наружу.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не** реальной
> email/SMS/Telegram/webhook доставки. Все внешние каналы выключены
> (`NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`, `NOTIFICATION_EMAIL_LIVE_ENABLED=false`,
> `NOTIFICATION_TELEGRAM_LIVE_ENABLED=false`, `NOTIFICATION_WEBHOOK_LIVE_ENABLED=false`),
> провайдеры по умолчанию `mock`, dry-run по умолчанию, дайджесты и worker выключены. Провайдеры
> НЕ импортируют сетевые библиотеки; live-провайдеры — skeleton (отказ по флагам). В логах/UI/API
> нет токенов/секретов: адрес доставки только маской (`s***@domain.ru`).

## Зачем нужна доставка

In-app уведомления живут внутри кабинета. Чтобы участник узнавал о событиях вне приложения,
нужна внешняя доставка (email/Telegram/webhook) и периодические дайджесты. v0.5.1 закладывает
безопасный фундамент: весь конвейер (задачи → провайдер → лог → retry) готов и протестирован на
mock-провайдерах, а включение реальной доставки — отдельный осознанный шаг в будущем.

## Термины

- **NotificationDeliveryProvider**: `mock · smtp · telegram_bot · webhook`.
- **NotificationDeliveryStatus**: `pending · sent · failed · skipped · disabled · retry_scheduled · canceled`.
- **NotificationDeliveryChannel**: `email · telegram · webhook · digest`.
- **NotificationDigestStatus**: `draft · generated · sent · skipped · failed`.
- **NotificationDigestFrequency**: `daily · weekly`.

## In-app vs external

- **in-app** (v0.5.0) — уведомления в кабинете (колокольчик, inbox); работают всегда.
- **external** (v0.5.1) — email/Telegram/webhook + дайджест; в MVP это **sandbox**: задачи и логи
  создаются, но наружу ничего не уходит.

## Mock / sandbox провайдеры

`MockEmailProvider` / `MockTelegramProvider` / `MockWebhookProvider` реализуют интерфейс
`NotificationDeliveryProvider.send(request) -> NotificationDeliveryResult`, возвращают `sent` с
mock-`provider_message_id` и **никогда не ходят в сеть**. Реестр
`NotificationDeliveryProviderRegistry.resolve(channel)` выбирает live-провайдера ТОЛЬКО когда
канал реально включён (external + канал + live) — по умолчанию всегда mock.

## Email / Telegram / webhook adapters (skeleton)

`SmtpEmailProvider` / `TelegramNotificationProvider` / `WebhookNotificationProvider` —
skeleton'ы live-доставки: если внешняя доставка/live канала выключены → возвращают `disabled`
(отказ); реальная отправка в MVP **не реализована** и сетевые библиотеки не импортируются. Это
защита от случайной реальной доставки.

## Delivery jobs и журнал

- `create_delivery_job(notification_id, channel)` — создаёт `NotificationDeliveryLog`
  (`pending`/`skipped`/`disabled`, с учётом предпочтений и настроек), без отправки;
- `send_delivery(delivery_log_id, dry_run)` — dry-run → `skipped`; mock → `sent`; live-skeleton →
  `disabled`/`failed`;
- `send_notification(notification_id, channels, dry_run)` — создаёт задачи по каналам и «шлёт»;
- журнал хранит `provider · channel · status · destination_masked · attempts · error · sent_at`
  (без секретов).

## Retry / backoff

`retry_due_deliveries(dry_run)` берёт `pending`/`retry_scheduled` и повторяет. При ошибке
провайдера: `schedule_retry` с backoff (`NOTIFICATION_DELIVERY_RETRY_BACKOFF_SECONDS`, по
умолчанию 300 c) пока `attempts < NOTIFICATION_DELIVERY_MAX_ATTEMPTS` (3), затем `failed`.

## Digest / планировщик

- `preview_digest(user_id, frequency)` — собрать недавние уведомления (daily=24ч / weekly=7д),
  вернуть subject/body (без записи);
- `generate_digest(..., dry_run)` — write-режим создаёт `NotificationDigest`;
- `send_digest(digest_id, dry_run)` — доставка канала `digest` (в MVP sandbox);
- `run_digest_scheduler(frequency, dry_run)` — найти пользователей с включённым дайджестом и
  сгенерировать/отправить; **выключено по умолчанию** (`NOTIFICATION_DIGEST_ENABLED=false`).
- `build_digest_body(notifications)` — текст, сгруппированный по проекту, с типами/приоритетами и
  `action_url` (санитизирован).

## Preferences

`in_app` включён; `email` / `telegram` / `digest` / `webhook` **выключены** по умолчанию — сервис
принудительно оставляет внешние каналы выключенными, пока `external delivery` off.

## UI

- `/ui/notification-delivery` — «Доставка уведомлений»: баннер «Внешняя доставка выключена», карты
  статусов (pending/sent/failed/skipped/disabled), карточки каналов (mock/disabled), тест
  (Preview / Send dry-run), таблица логов (Retry dry-run);
- `/ui/projects/{id}/notification-delivery` — дашборд доставки проекта;
- `/ui/notification-digests` — preview daily/weekly, список, generate dry-run, предупреждение;
- `/ui/settings` — секция «Уведомления» (in-app вкл; email/Telegram/дайджест/webhook выкл).

Кнопки — только sandbox/dry-run; live-кнопок нет.

## CLI

```bash
make notification-delivery-preview notification_id=1 channels=email,telegram
make notification-delivery-send notification_id=1 channels=email dry_run=true
make notification-delivery-retry dry_run=true
make notification-digest-preview user_id=1 frequency=daily
make notification-digest-generate user_id=1 dry_run=true
make notification-digest-scheduler frequency=daily dry_run=true
```

## Флаги конфигурации

| Флаг | По умолчанию | Смысл |
| --- | --- | --- |
| `NOTIFICATION_DELIVERY_ENABLED` | `true` | Подсистема доставки (задачи/логи/dry-run) |
| `NOTIFICATION_DELIVERY_DRY_RUN` | `true` | Dry-run по умолчанию |
| `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED` | `false` | Реальная внешняя доставка (запрещена) |
| `NOTIFICATION_EMAIL_ENABLED` / `_LIVE_ENABLED` | `false` | Email канал / live |
| `NOTIFICATION_EMAIL_PROVIDER` | `mock` | Провайдер email (mock/smtp) |
| `SMTP_*` | пусто | SMTP host/port/user/pass/from/tls (секреты — только в env) |
| `NOTIFICATION_TELEGRAM_ENABLED` / `_LIVE_ENABLED` | `false` | Telegram канал / live |
| `NOTIFICATION_TELEGRAM_BOT_TOKEN` | пусто | Токен бота (секрет) |
| `NOTIFICATION_WEBHOOK_ENABLED` / `_LIVE_ENABLED` | `false` | Webhook канал / live |
| `NOTIFICATION_WEBHOOK_SIGNING_SECRET` | пусто | Секрет подписи webhook |
| `NOTIFICATION_DIGEST_ENABLED` / `_WORKER_ENABLED` | `false` | Дайджесты / worker |
| `NOTIFICATION_DIGEST_DRY_RUN` | `true` | Dry-run дайджестов |
| `NOTIFICATION_DELIVERY_MAX_ATTEMPTS` | `3` | Лимит попыток |
| `NOTIFICATION_DELIVERY_RETRY_BACKOFF_SECONDS` | `300` | Backoff |

## Биллинг

Sandbox-доставка и дайджесты — **бесплатно в MVP**: `notification_delivery_preview`,
`notification_delivery_send`, `notification_digest_generate`, `notification_digest_send` = 0 units.
Внешняя доставка будущего тарифицируется позже; failed/skipped/disabled не списывают средства.

## Аудит

`notification_delivery.previewed · job_created · sent · failed · skipped · disabled ·
retry_scheduled` и `notification_digest.previewed · generated · sent · failed · scheduler.previewed`.
Метаданные: `notification_id · delivery_log_id · digest_id · channel · provider · status` — без
секретов и токенов.

## Приватность

Пользователь видит **только свои** delivery-логи и дайджесты; проектный дашборд — под
project-гардом. Адрес доставки — только маской; токены/секреты в API/UI/логах отсутствуют.

## Что дальше

- реальная SMTP-интеграция;
- доставка уведомлений Telegram-ботом;
- подписанные webhooks;
- digest-worker (периодический планировщик);
- управление отпиской (unsubscribe);
- rate limits доставки.
