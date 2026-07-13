# 51. Botfleet: Telegram-канал уведомлений — привязка, шаблоны, sandbox/live-ready (v0.5.4)

Слой **Telegram как канала уведомлений**
([48](48_Botfleet_Notification_Delivery_Digest.md), [49](49_Botfleet_Notification_Safety_Unsubscribe_Webhooks.md),
[50](50_Botfleet_Email_Templates_SMTP_Sandbox.md)): привязка чата (`/start <token>`), короткие
Telegram-шаблоны и **live-ready, но по умолчанию выключенный** Telegram Bot adapter. Это
foundation под реальную Telegram-доставку — код готов, но включается только полным набором флагов,
которых в MVP нет.

> **Безопасность:** это **не** этап публикаций постов в Telegram, **не** реальных платежей и
> **не** реальной внешней Telegram-доставки. Реальная отправка ВЫКЛЮЧЕНА по умолчанию:
> `NOTIFICATION_TELEGRAM_LIVE_SEND_ENABLED=false`, `NOTIFICATION_TELEGRAM_TEST_SEND_ENABLED=false`,
> `NOTIFICATION_TELEGRAM_TEST_SEND_DRY_RUN=true`, `NOTIFICATION_TELEGRAM_LIVE_ENABLED=false`,
> `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`. Telegram-провайдер **отказывает** (`disabled`),
> пока не включены ВСЕ флаги. `chat_id`/`telegram_user_id` хранятся **зашифрованно + masked +
> hash**; сырой chat_id наружу (API/UI/логи) не отдаётся. Verification token хранится как
> **hash + prefix** и показывается **один раз** при создании. `NOTIFICATION_TELEGRAM_BOT_TOKEN`
> хранится **только в env**, никогда не логируется/не возвращается.

## Зачем это нужно

Уведомления уже создаются и складываются в delivery-логи (v0.5.1) с учётом safety-гейтов
(v0.5.2); email-канал разобран в (v0.5.3). Telegram — второй «живой» канал: людям удобнее получать
короткие уведомления в Telegram. Перед реальной доставкой нужно уметь **привязать чат** (безопасно,
с верификацией), **сгенерировать короткое сообщение** и всё это посмотреть (preview/sandbox) без
единого реального сообщения наружу. v0.5.4 добавляет этот слой и «скелет» Telegram Bot adapter,
который безопасно довести до live одним набором флагов, когда придёт время.

## Поток привязки (binding flow)

1. Пользователь запрашивает привязку (`POST /notification-telegram/bindings` или
   `make telegram-binding-create user_id=1`).
2. Система создаёт `pending_verification`-привязку и выдаёт **verification token** (показывается
   ОДИН раз) + команду `/start <token>`.
3. Пользователь открывает Telegram-бота Botfleet и отправляет `/start <token>`.
4. Бот (в будущем — через webhook/polling; в MVP — вручную или тестовым payload) передаёт токен и
   `chat_id`; Botfleet валидирует токен по hash и сохраняет `chat_id` **зашифрованно**, статус →
   `verified`.
5. С этого момента delivery-конвейер может доставлять в этот чат (пока — только mock/sandbox).

Статусы привязки: `draft`, `pending_verification`, `verified`, `disabled`, `suppressed`,
`revoked`, `failed`.

### `/start <token>` и `verify-update`

`verify_binding_from_update` разбирает Telegram-update payload (`message.text` = `/start <token>`,
`message.chat.id`) **без сети** — это скелет под будущий webhook/polling. В MVP доступен эндпоинт
`POST /notification-telegram/bindings/verify-update` для локального/тестового прогона.

## Telegram-шаблоны

`TelegramNotificationTemplateService` хранит короткие системные шаблоны в коде (не во внешних
файлах): `review_assigned`, `review_mentioned`, `review_comment`, `review_changes_requested`,
`review_approved`, `review_rejected`, `task_overdue`, `post_needs_review`,
`experiment_suggestion_created`, `experiment_winner_selected`, `learning_profile_updated`,
`billing_balance_low`, `digest_daily`, `digest_weekly`, `system_notice`. Неизвестный тип → откат к
`system_notice`.

- Рендер `{{ var }}` — простая подстановка (без Jinja): неизвестные переменные → пусто.
- Текст **санитизируется** (`redact_sensitive_text` + внутренние пути), нормализуется по пробелам
  и обрезается до `NOTIFICATION_TELEGRAM_MAX_MESSAGE_CHARS` (кламп 1..4096).
- `parse_mode` по умолчанию `none` (plain text); поддерживаются `markdown_v2`/`html` (за флагом).

## Провайдеры

### MockTelegramProvider (sandbox)

Не ходит в сеть. Возвращает `ok=True, status=sent`, `provider_message_id=mock_telegram_…`,
`response_metadata={delivered:false, sandbox:true, would_send_text_preview:…}`; destination — маской.

### TelegramNotificationProvider (live-ready foundation)

- `send()` сначала вызывает `_blocked_reason(settings)`: если хоть один флаг не включён — возвращает
  `disabled` (реальной отправки нет). Порядок причин: external delivery → telegram live → telegram
  live send → bot token настроен.
- Live-путь (достижим только при всех флагах) обращается к
  `https://api.telegram.org/bot{token}/sendMessage` с payload `{chat_id, text,
  disable_web_page_preview}` (+ `parse_mode`, если задан). `httpx` импортируется **лениво** внутри
  функции; в тестах HTTP-отправитель внедряется (`http_sender`) — **реальной сети нет**.
- Bot token НИКОГДА не попадает в результат/`provider_message_id`/текст ошибки (`_safe_error`
  дополнительно вычищает токен). destination — только маской.

## Интеграция с доставкой и safety

При `channel=telegram` в `NotificationDeliveryService`:

- **binding required**: адрес доставки = расшифрованный `chat_id` верифицированной привязки (только
  внутри сервис/provider-пути). Нет привязки → задача `disabled` с причиной
  `missing_verified_telegram_binding`.
- **safety-гейты** (v0.5.2): opt-out, suppression, rate-limit (`telegram` 30/ч), preferences —
  всё уважается в `_initial_status`.
- **delivery log**: `subject` = заголовок; `message_preview` = превью Telegram-текста; `destination_masked`
  = masked chat_id; `request_metadata` = `{template_type, parse_mode, binding_id, live_blocked_reason}`.
  Сырой chat_id / verification token в лог **не попадают**.
- **dry-run** → `skipped` (сети нет). **mock** → `sent` (sandbox). **live** → провайдер отказывает,
  пока не включены все флаги.

## API

| Метод | Назначение |
|---|---|
| `GET /notification-telegram/bindings` | список СВОИХ привязок (public view) |
| `POST /notification-telegram/bindings` | создать привязку + verification token (один раз) |
| `POST /notification-telegram/bindings/verify` | верификация token + chat_id (в MVP вручную) |
| `POST /notification-telegram/bindings/verify-update` | верификация из Telegram update (dry/локально) |
| `POST /notification-telegram/bindings/{id}/disable` | отключить свою привязку |
| `POST /notification-telegram/bindings/{id}/revoke` | отозвать (chat_id обнуляется) |
| `POST /notification-telegram/notifications/{id}/preview` | preview Telegram-текста |
| `POST /notification-telegram/notifications/{id}/send-dry` | создать задачу + dry-run |
| `POST /notification-telegram/test-send-dry` | тестовый рендер (dry-run only) |
| `GET /notification-telegram/projects/{id}/dashboard` | сводка проекта (project-гард) |

Token отдаётся ТОЛЬКО при создании; сырой chat_id/bot token в ответах отсутствуют.

## UI

- `/ui/notification-telegram` (и `/ui/projects/{id}/notification-telegram`) — баннер «Реальная
  Telegram-доставка выключена», safety-карточки, блок подключения (`/start <token>` + ручная
  верификация для MVP), список привязок, preview и тест dry-run.
- `/ui/notification-delivery` — карточка Telegram-провайдера (mock/sandbox, live выключен, нужна
  привязка) + ссылка.
- `/ui/settings` — блок «Telegram-уведомления» (всё выключено; bot token не показывается).

## CLI (Makefile)

| Команда | Назначение |
|---|---|
| `make telegram-binding-create user_id=1` | создать привязку (token один раз) |
| `make telegram-binding-verify token=… chat_id=…` | верифицировать (chat_id маской) |
| `make telegram-notification-preview notification_id=1` | preview Telegram-текста |
| `make telegram-test-send user_id=1 dry_run=true` | тестовый рендер (dry-run only) |

`--show-unsafe true` в `telegram-binding-verify` печатает сырой chat_id — только для локальной
отладки; в лог не пишется.

## Флаги конфигурации

| Флаг | Дефолт | Назначение |
|---|---|---|
| `NOTIFICATION_TELEGRAM_TEMPLATES_ENABLED` | `true` | Telegram-шаблоны (только рендер) |
| `NOTIFICATION_TELEGRAM_BINDING_ENABLED` | `true` | привязка чата |
| `NOTIFICATION_TELEGRAM_BINDING_TOKEN_BYTES` | `24` | длина verification-токена |
| `NOTIFICATION_TELEGRAM_BINDING_TOKEN_TTL_DAYS` | `30` | TTL токена (флор 1 час) |
| `NOTIFICATION_TELEGRAM_PARSE_MODE` | `none` | `none`/`markdown_v2`/`html` |
| `NOTIFICATION_TELEGRAM_MAX_MESSAGE_CHARS` | `3900` | лимит сообщения (кламп 1..4096) |
| `NOTIFICATION_TELEGRAM_TEST_SEND_ENABLED` | `false` | тестовая отправка (в MVP только dry-run) |
| `NOTIFICATION_TELEGRAM_TEST_SEND_DRY_RUN` | `true` | dry-run тестовой отправки |
| `NOTIFICATION_TELEGRAM_LIVE_SEND_ENABLED` | `false` | реальная отправка (нужны ВСЕ флаги) |
| `NOTIFICATION_TELEGRAM_REQUIRE_VERIFIED_BINDING` | `true` | доставка только в verified-чат |
| `NOTIFICATION_TELEGRAM_ALLOW_UNVERIFIED_TEST` | `false` | тест без верификации (выключено) |
| `NOTIFICATION_TELEGRAM_BOT_TOKEN` | пусто (env) | bot token — только в env, не в БД/UI |

Эффективный `notification_telegram_live_send_enabled_effective` = external delivery **и** telegram
live **и** telegram live send **и** bot token настроен. В MVP — всегда `false`.

## Что дальше

- реальный Telegram bot webhook/polling (получение `/start` из реальных update);
- production Telegram notification bot (bot token в защищённом окружении);
- верификация чата реальным update (сейчас — ручная/тестовая);
- message templates с кнопками (inline keyboard);
- доставка дайджестов в Telegram;
- мониторинг частоты доставки (delivery rate monitor) и алертинг при всплесках отказов.

> **Реализовано в v0.5.5:** incoming webhook sandbox + update-парсер + авто-верификация `/start`
> через webhook, polling/webhook-management dry-run (реальных Telegram API-вызовов нет). См.
> [52_Botfleet_Telegram_Webhook_Polling_Sandbox.md](52_Botfleet_Telegram_Webhook_Polling_Sandbox.md).

> **Telegram-first live rollout (v0.6.0):** Telegram выбран первым реальным live-каналом
> автопостинга (не уведомлений). Реальная публикация — только под всеми гейтами + подтверждением;
> каждая попытка пишется в `LivePublishAttempt`. См.
> [57_Botfleet_Telegram_Live_Rollout.md](57_Botfleet_Telegram_Live_Rollout.md).
