# 49. Botfleet: безопасность уведомлений — отписка, лимиты, подавление, подписанные webhook (v0.5.2)

Safety-слой **перед** реальной внешней доставкой ([48](48_Botfleet_Notification_Delivery_Digest.md)):
отписки (unsubscribe/opt-out), лимиты доставки (rate limits), подавление при ошибках
(suppression) и **подписанные webhook-подписки**. Всё это гарантирует, что при включении
реальной доставки Botfleet не спамит, уважает отписки и не хранит сырые секреты.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не** реальной
> email/Telegram/webhook доставки. Реальный вызов webhook и внешняя доставка ВЫКЛЮЧЕНЫ по
> умолчанию (`NOTIFICATION_WEBHOOK_SUBSCRIPTIONS_LIVE_ENABLED=false`,
> `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`). Webhook URL и signing secret считаются
> чувствительными: хранятся **зашифрованно** + masked/hash; наружу — только маска. Адреса
> подавления — только SHA-256 hash. Токены отписки подписаны HMAC-SHA256 и не логируются.

## Зачем нужен safety-слой

Реальная доставка без защиты опасна: можно заспамить получателя, слать на отписавшийся адрес,
долбить упавший webhook, хранить секрет в открытом виде. v0.5.2 закрывает это ДО включения
доставки — конвейер доставки уже уважает все гейты (проверено интеграционными тестами на mock).

## Термины

- **NotificationOptOutScope**: `global · account · project · notification_type · channel`.
- **NotificationSuppressionReason**: `user_unsubscribed · preference_disabled · destination_unverified · too_many_failures · rate_limited · external_delivery_disabled · channel_live_disabled · missing_destination · invalid_destination · admin_disabled`.
- **NotificationRateLimitScope**: `user · project · account · channel · notification_type · provider`.
- **WebhookSubscriptionStatus**: `draft · active · disabled · suppressed · failed · revoked`.
- **WebhookSignatureAlgorithm**: `hmac_sha256`.

## Unsubscribe (отписка / opt-out)

Пользователь отписывается: глобально, по аккаунту, проекту, типу уведомления или каналу
(email/telegram/webhook/digest). Два пути:
- **токен** (`NotificationUnsubscribeService.issue_unsubscribe_token` → HMAC-SHA256 +
  base64url JSON payload с `iat`/`exp`) → публичная страница `/unsubscribe?token=…` → opt-out;
- **напрямую** (авторизованный пользователь) через API `/notification-safety/opt-outs`.

Активный opt-out блокирует внешнюю доставку соответствующего scope; можно отменить (revoke).
`in_app` по умолчанию не выключается.

## Rate limits

DB-backed лимитер (окно + счётчик) per (user, channel): email 20/ч, telegram 30/ч, webhook
60/ч, digest 2/сутки (настраивается). Проверка `check_delivery_allowed` (read-only) не тратит
бюджет; учёт `record_delivery_attempt` — только на фактической (mock) доставке. Превышение →
задача доставки `skipped` с причиной `rate_limited`.

## Suppression (подавление)

Если внешняя доставка по каналу/адресу падает `NOTIFICATION_SUPPRESSION_FAILURE_THRESHOLD` (5)
раз — канал/адрес **подавляется** на `NOTIFICATION_SUPPRESSION_TTL_HOURS` (24 ч). Сырой адрес НЕ
хранится — только SHA-256 hash. Успешная доставка сбрасывает счётчик и снимает подавление;
можно снять вручную. Подавление → задача доставки `disabled` с причиной `too_many_failures`.

## Signed webhook subscriptions

Клиент задаёт webhook URL и (опционально) signing secret (если не задан — генерируется).
Хранение: `url_encrypted` + `url_masked` + `url_hash`; `signing_secret_encrypted` +
`signing_secret_masked`. Наружу отдаётся ТОЛЬКО masked/hash/present. Payload подписывается
HMAC-SHA256 по схеме `sha256=HMAC(secret, "{timestamp}.{payload}")` с заголовками
`X-Botfleet-Signature` / `X-Botfleet-Timestamp`. **Реальный вызов выключен** — доступен
подписанный **preview** (какой payload был бы отправлен) без отправки.

## Интеграция с доставкой

`NotificationDeliveryService._initial_status` при создании задачи проверяет по порядку:
delivery включён → есть адрес → предпочтение канала → **opt-out** → **suppression** →
**rate-limit**. Если что-то блокирует — задача создаётся со статусом `disabled`/`skipped`,
причина в `error_message`, пишется аудит `notification.delivery.blocked`, внешней отправки нет.
На успехе (mock) — учёт лимита + снятие подавления; на ошибке — запись в suppression.

## UI

- `/ui/notification-safety` — отписки (создать/вернуть), лимиты, подавления (снять), баннер;
- `/ui/notification-preferences` — каналы (masked, внешние выключены);
- `/ui/projects/{id}/notification-safety` — подавления/лимиты проекта;
- `/ui/projects/{id}/webhooks` — webhook-подписки (создать/preview/отозвать; URL/secret masked);
- `/ui/unsubscribe` — инфо; функциональная отписка — по `/unsubscribe?token=…`;
- `/ui/settings` — ссылки на безопасность/настройки.

Реальных кнопок отправки нет — только dry-run/preview.

## CLI

```bash
make notification-safety-dashboard user_id=1
make notification-opt-out user_id=1 scope=channel channel=email dry_run=false
make notification-suppression-clear suppression_id=1 dry_run=false
make webhook-subscription-create account_id=1 url=https://hooks.example.com/x dry_run=false
make webhook-subscription-preview subscription_id=1
```

## Флаги конфигурации

| Флаг | По умолчанию | Смысл |
| --- | --- | --- |
| `NOTIFICATION_SAFETY_ENABLED` | `true` | Safety-слой включён |
| `NOTIFICATION_UNSUBSCRIBE_ENABLED` | `true` | Отписка по токену |
| `NOTIFICATION_UNSUBSCRIBE_TOKEN_SECRET` | пусто | Секрет подписи токена (вне prod — фолбэк) |
| `NOTIFICATION_UNSUBSCRIBE_TOKEN_TTL_DAYS` | `365` | TTL токена отписки |
| `NOTIFICATION_RATE_LIMIT_ENABLED` | `true` | Лимиты доставки |
| `NOTIFICATION_RATE_LIMIT_{EMAIL,TELEGRAM,WEBHOOK}_PER_HOUR` | `20/30/60` | Лимиты каналов |
| `NOTIFICATION_RATE_LIMIT_DIGEST_PER_DAY` | `2` | Лимит дайджеста |
| `NOTIFICATION_SUPPRESSION_ENABLED` | `true` | Подавление при ошибках |
| `NOTIFICATION_SUPPRESSION_FAILURE_THRESHOLD` | `5` | Порог ошибок |
| `NOTIFICATION_SUPPRESSION_TTL_HOURS` | `24` | TTL подавления |
| `NOTIFICATION_WEBHOOK_SUBSCRIPTIONS_ENABLED` | `true` | Подписки webhook (создание/preview) |
| `NOTIFICATION_WEBHOOK_SUBSCRIPTIONS_LIVE_ENABLED` | `false` | Реальный вызов webhook (запрещён) |
| `NOTIFICATION_WEBHOOK_SIGNATURE_HEADER` | `X-Botfleet-Signature` | Заголовок подписи |
| `NOTIFICATION_WEBHOOK_TIMESTAMP_HEADER` | `X-Botfleet-Timestamp` | Заголовок метки времени |
| `NOTIFICATION_WEBHOOK_MAX_PAYLOAD_BYTES` | `262144` | Лимит payload |

## Хранение секрета webhook

`signing_secret` шифруется `crm_secret_service.encrypt_secret` (заглушка-обёртка, заменяемая на
KMS/Fernet без изменения остального кода) и маскируется `mask_secret`. Наружу отдаётся только
`signing_secret_masked` + `signing_secret_present`. Сам секрет не логируется и не возвращается.

## Почему live-доставка выключена

Реальная отправка требует: проверенных провайдеров, доменов/DKIM для email, бота и chat-id для
Telegram, подтверждённых endpoint'ов для webhook, мониторинга bounce/rate. Всё это — следующие
этапы; сейчас конвейер и его защита готовы и протестированы на mock.

## Биллинг

Safety-проверки и webhook (sandbox) — **бесплатно в MVP**: `notification_safety_check`,
`webhook_subscription_create`, `webhook_delivery_preview` = 0 units.

## Аудит

`notification.opt_out.created/revoked · notification.suppression.created/cleared ·
notification.rate_limited · webhook_subscription.created/updated/revoked/previewed ·
notification.delivery.blocked`. Без секретов/сырых адресов в метаданных.

## Что дальше

- реальная SMTP-интеграция;
- реальная доставка Telegram-ботом;
- реальный вызов webhook с retry/rate-monitoring;
- unsubscribe-ссылки в email-шаблонах;
- мониторинг частоты доставки (delivery rate monitor).
