# 52. Botfleet: Telegram bot webhook/polling sandbox (v0.5.5)

Приём **входящих Telegram-обновлений** и автоматическая верификация привязки через `/start <token>`
поверх Telegram-канала уведомлений ([51](51_Botfleet_Telegram_Notification_Delivery.md)): incoming
webhook endpoint, чистый update-парсер, история апдейтов, secret-защита webhook, polling/webhook
management dry-run. Всё — **sandbox**: реальных Telegram API-вызовов нет, ответных сообщений наружу
нет. Это foundation под реальный webhook/polling, включаемый флагами, когда домен и бот готовы.

> **Безопасность:** это **не** этап публикаций постов в Telegram, **не** реальных платежей и
> **не** реальных внешних Telegram API-вызовов. По умолчанию:
> `NOTIFICATION_TELEGRAM_WEBHOOK_LIVE_ENABLED=false`, `NOTIFICATION_TELEGRAM_POLLING_LIVE_ENABLED=false`,
> `NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_LIVE_ENABLED=false`, `..._POLLING_DRY_RUN=true`,
> `..._WEBHOOK_MANAGEMENT_DRY_RUN=true`, `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`.
> `getUpdates`/`setWebhook`/`deleteWebhook` реально **не вызываются**, пока не включены все флаги.
> Сырой `chat_id`/`telegram_user_id`/verification token/bot token/webhook secret **не хранятся и
> не логируются** (только hash + маска). Токен в `/start` маскируется в preview/логах.

## Зачем это нужно

В v0.5.4 привязку Telegram-чата подтверждали вручную (ввод chat_id). Реальный бот получает
подтверждение иначе — через **входящий update** (webhook или polling), когда пользователь пишет
`/start <token>`. v0.5.5 добавляет приём таких апдейтов в безопасном sandbox: их можно принимать
через endpoint, симулировать в UI/CLI, логировать и автоматически верифицировать привязку — всё
без единого реального Telegram API-вызова.

## Incoming webhook

`POST /notification-telegram/webhook` — **без auth** (Telegram не присылает наши auth-заголовки),
принимает произвольный Telegram Update (JSON). Поток (`TelegramIncomingService.handle_webhook_update`):

1. проверка `notification_telegram_webhook_enabled_effective` (иначе disabled);
2. **secret-заголовок** `X-Telegram-Bot-Api-Secret-Token` (если требуется) — неверный → лог
   `invalid_secret` + HTTP 403;
3. парсинг апдейта (чистый парсер);
4. **дедупликация** по `update_id` → повтор помечается `duplicate`;
5. запись `received` + аудит;
6. если `/start <token>` → авто-верификация привязки (`verify_binding_from_update`), статус
   `verified_binding` или `failed`;
7. `/help`/`/status` → `processed`; прочее/неизвестное → `ignored`;
8. **ответных сообщений наружу нет**; всегда 200 (кроме invalid_secret → 403), чтобы Telegram не
   ретраил бесконечно.

## Update parser

`TelegramUpdateParserService` (чистый, без БД/сети) — `parse_update` → `ParsedTelegramUpdate`
(update_id, update_type, chat_id, telegram_user_id, username, text, command, command_args,
is_start_command, start_token, unknown_reason, raw_sanitized):

- типы: `message` / `edited_message` / `callback_query` (placeholder) / `unknown`;
- команды: `/start <token>`, `/start@BotName <token>`, `/help`, `/status`, unknown;
- `sanitize_update` → безопасная копия: `chat.id`/`from.id` только маской, токен `/start`
  замаскирован (`/start abc123***`);
- безопасен к отсутствующим полям (`validate_update_shape` возвращает warnings/errors, не бросает).

## История апдейтов

`notification_telegram_update_logs` (миграция `0037_telegram_update_logs`): update_id, update_type,
status, command, `chat_id_hash`/`telegram_user_id_hash` (без сырых значений), username,
`text_preview` (маска токена), `raw_update_sanitized` (очищенная копия), result_metadata,
error_message, received_at/processed_at. Публичное представление (`public_update_view`) — без
сырого chat_id/токена. Статусы: `received`/`processed`/`ignored`/`failed`/`verified_binding`/
`duplicate`/`invalid_secret`.

## Webhook security

- Заголовок `X-Telegram-Bot-Api-Secret-Token` сверяется в постоянном времени (`hmac.compare_digest`).
- `NOTIFICATION_TELEGRAM_WEBHOOK_SECRET_REQUIRED=true` → неверный/пустой заголовок = 403.
- В local можно разрешить отсутствие секрета флагом
  `NOTIFICATION_TELEGRAM_WEBHOOK_ALLOW_LOCAL_WITHOUT_SECRET=true`.
- Secret token хранится **только в env**; наружу отдаётся лишь факт «сконфигурирован да/нет».

## Polling / webhook management (dry-run)

`TelegramBotManagementService` — скелет `setWebhook`/`deleteWebhook`/`getWebhookInfo`/`getUpdates`:

- `*_dry` методы **не ходят в сеть**, возвращают санитизированное «что было бы отправлено»;
- `set_webhook_live` / `poll_updates_live` **отказывают** (`disabled`), пока не включены все флаги
  (external delivery + соответствующий live + не dry-run + bot token настроен);
- в live-пути `httpx` импортируется **лениво**; в тестах внедряется HTTP-отправитель (сети нет);
- bot token НИКОГДА не попадает в URL/результат/ошибку/логи; при сбое — sanitized-ошибка.

## Почему нет реальных Telegram API по умолчанию

Реальный webhook требует публичного HTTPS-домена и production bot token; `setWebhook` меняет
глобальное состояние бота у Telegram. До готовности инфраструктуры любые реальные вызовы опасны,
поэтому всё за флагами и dry-run. Sandbox позволяет разработать и протестировать весь поток
(приём, парсинг, верификация, логи) без внешних зависимостей.

## API

| Метод | Назначение |
|---|---|
| `POST /notification-telegram/webhook` | incoming Telegram update (без auth; secret-check) |
| `POST /notification-telegram/simulate-update` | симуляция `/start`-апдейта (auth) |
| `GET /notification-telegram/updates` | свои недавние апдейты (public view) |
| `GET /notification-telegram/projects/{id}/updates` | апдейты проекта (project-гард) |
| `GET /notification-telegram/webhook-dashboard` | сводка webhook-канала |
| `GET /notification-telegram/projects/{id}/webhook-dashboard` | сводка проекта |
| `POST /notification-telegram/webhook/set-dry` | DRY-RUN setWebhook |
| `POST /notification-telegram/webhook/delete-dry` | DRY-RUN deleteWebhook |
| `GET /notification-telegram/webhook/info-dry` | DRY-RUN getWebhookInfo |
| `POST /notification-telegram/polling/dry` | DRY-RUN getUpdates |

## UI

`/ui/notification-telegram` (и проектная страница): баннер «Реальные Telegram API-вызовы выключены»,
разделы «Incoming updates / Webhook» (endpoint, public URL, secret/live статус), «Проверка /start
token» (форма симуляции), «Recent incoming updates» (таблица), «Webhook management (dry-run)»
(кнопки Preview setWebhook / getWebhookInfo / polling). Bot token/secret не показываются.

## CLI (Makefile)

| Команда | Назначение |
|---|---|
| `make telegram-update-simulate token=… chat_id=…` | симуляция `/start` (chat_id маской) |
| `make telegram-webhook-info` | getWebhookInfo (dry-run) |
| `make telegram-webhook-set url=…` | setWebhook (dry-run) |
| `make telegram-polling-dry limit=10` | getUpdates (dry-run) |

`--show-unsafe true` в `telegram-update-simulate` печатает сырой chat_id — только для локальной
отладки; в лог не пишется.

## Флаги конфигурации

| Флаг | Дефолт | Назначение |
|---|---|---|
| `NOTIFICATION_TELEGRAM_WEBHOOK_ENABLED` | `true` | incoming webhook endpoint (sandbox) |
| `NOTIFICATION_TELEGRAM_WEBHOOK_LIVE_ENABLED` | `false` | реальный webhook (нужны все флаги) |
| `NOTIFICATION_TELEGRAM_WEBHOOK_SECRET_REQUIRED` | `false` | требовать secret-заголовок |
| `NOTIFICATION_TELEGRAM_WEBHOOK_SECRET_TOKEN` | пусто (env) | secret token — только в env |
| `NOTIFICATION_TELEGRAM_WEBHOOK_PUBLIC_URL` | пусто | публичный HTTPS-домен |
| `NOTIFICATION_TELEGRAM_WEBHOOK_PATH` | `/notification-telegram/webhook` | путь эндпоинта |
| `NOTIFICATION_TELEGRAM_WEBHOOK_ALLOW_LOCAL_WITHOUT_SECRET` | `true` | local без секрета |
| `NOTIFICATION_TELEGRAM_POLLING_ENABLED` | `true` | polling skeleton (dry-run) |
| `NOTIFICATION_TELEGRAM_POLLING_LIVE_ENABLED` | `false` | реальный getUpdates |
| `NOTIFICATION_TELEGRAM_POLLING_DRY_RUN` | `true` | dry-run polling |
| `NOTIFICATION_TELEGRAM_POLLING_LIMIT` | `20` | лимит getUpdates (1..100) |
| `NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_ENABLED` | `true` | управление webhook (dry-run) |
| `NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_LIVE_ENABLED` | `false` | реальный setWebhook |
| `NOTIFICATION_TELEGRAM_WEBHOOK_MANAGEMENT_DRY_RUN` | `true` | dry-run управления |
| `NOTIFICATION_TELEGRAM_INCOMING_UPDATE_LOG_ENABLED` | `true` | лог входящих апдейтов |
| `NOTIFICATION_TELEGRAM_INCOMING_MAX_TEXT_PREVIEW` | `200` | лимит text_preview (1..512) |

## Что дальше

- production Telegram webhook domain (публичный HTTPS + реальный `setWebhook`);
- реальный `setWebhook` и polling worker (за флагами, с мониторингом);
- меню команд бота (`setMyCommands`) и inline-кнопки;
- реальная доставка дайджестов в Telegram;
- мониторинг частоты доставки и алертинг.
