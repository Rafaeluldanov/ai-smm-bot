# 50. Botfleet: email-шаблоны и SMTP sandbox / live-ready (v0.5.3)

Слой **генерации и предпросмотра email** для уведомлений и дайджестов
([48](48_Botfleet_Notification_Delivery_Digest.md), [49](49_Botfleet_Notification_Safety_Unsubscribe_Webhooks.md)):
системные шаблоны, рендер subject/text/HTML, футер отписки с маскированным токеном и
**live-ready, но по умолчанию выключенный** SMTP-провайдер. Это foundation под реальную
email-доставку — код готов, но включается только полным набором флагов, которых в MVP нет.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не** реальной
> email-доставки. Реальная отправка ВЫКЛЮЧЕНА по умолчанию:
> `SMTP_LIVE_SEND_ENABLED=false`, `SMTP_DRY_RUN=true`, `EMAIL_TEST_SEND_ENABLED=false`,
> `NOTIFICATION_EMAIL_LIVE_ENABLED=false`, `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED=false`.
> SMTP-провайдер **отказывает** (`disabled`), пока не включены ВСЕ флаги. `SMTP_PASSWORD`
> никогда не логируется/не возвращается (и вычищается из текста ошибки). Токен отписки в
> preview/логах/delivery-метаданных **маскируется**; сырой токен — только по явному
> `--show-unsafe-url` в CLI и никогда не пишется в лог/аудит.

## Зачем это нужно

Уведомления уже создаются и складываются в delivery-логи (v0.5.1) с учётом safety-гейтов
(v0.5.2). Перед реальной отправкой нужно уметь **сгенерировать само письмо** — тему, текст,
HTML-версию, футер отписки — и дать это посмотреть (preview/sandbox) без единого реального
письма наружу. v0.5.3 добавляет этот слой и «скелет» SMTP, который безопасно довести до live
одним переключением флагов, когда придёт время.

## Из чего состоит

### Модель и миграция

- `email_template_overrides` (миграция `0035_email_templates`) — задел под кастомные шаблоны
  на аккаунт/проект (`template_type`, `status`, `subject/text/html_template`, `variables_schema`,
  `override_metadata`). В MVP используются системные шаблоны; таблица — точка расширения.
- Константы: `EMAIL_TEMPLATE_TYPES` (типы писем), `EMAIL_RENDER_FORMATS` (`text`/`html`/`both`),
  `EMAIL_TEMPLATE_STATUSES`, `EMAIL_DELIVERY_MODES` (`preview`/`mock`/`smtp_live_blocked`/`smtp_live`).

### Сервис шаблонов (`email_template_service`)

- `SYSTEM_TEMPLATES` — системные шаблоны (subject/text/html/purpose): `review_assigned`,
  `review_mentioned`, `task_overdue`, `post_needs_review`, `experiment_suggestion_created`,
  `billing_balance_low`, `digest_daily`, `digest_weekly`, `system_notice`. Неизвестный тип →
  мягкий откат к `system_notice`.
- Рендер `{{ var }}` — простая подстановка: неизвестные переменные → пусто; в HTML-версии
  значения переменных экранируются (`html.escape`), пользовательский контент не ломает разметку.
- **Футер отписки** — метка-сентинел `@@UNSUB_FOOTER_TEXT@@` / `@@UNSUB_FOOTER_HTML@@` в шаблоне
  подставляется сырым футером **после** рендера (чтобы HTML-теги футера не экранировались и чтобы
  сентинел пережил движок `{{ }}`). Токен берётся из unsubscribe-сервиса (v0.5.2) и по умолчанию
  **маскируется** (`/unsubscribe?token=abc123***`).
- `preview_template` (демо-данные), `render_notification_email` (по уведомлению, только владелец),
  `render_digest_email` (по дайджесту), `sanitize_rendered_email` (маскирование секретов/путей).

### SMTP-провайдер (`smtp_email_provider`) — live-ready foundation

- `send()` сначала вызывает `_blocked_reason(settings)`: если хоть один флаг не включён —
  возвращает результат `disabled` (реальной отправки нет). Порядок причин: email live →
  SMTP настроен → не dry-run → SMTP live.
- Live-путь (достижим только при всех флагах) использует stdlib `smtplib`/`email.message`,
  но SMTP-клиент **внедряется фабрикой** (`smtp_factory`) — в тестах реальной сети нет.
- `SMTP_PASSWORD` передаётся клиенту при `login`, но **никогда** не попадает в результат,
  `provider_message_id` или текст ошибки (`_safe_error` дополнительно вычищает пароль).
- destination — только маской; при сбое — sanitized-ошибка без секретов.

### Интеграция в доставку

- При создании delivery-задачи для `email`/`digest` тема берётся из шаблона, в
  `request_metadata` кладётся `template_type` / `has_unsubscribe_footer`. В сам лог сырой токен
  **не попадает** — там только превью уведомления и маска адреса.
- При отправке (`send_delivery`, не dry-run) полное письмо (subject/text/HTML + футер с
  маской) рендерится в **запрос** провайдера, не в БД-лог.

### API (`/email-templates`)

- `GET /email-templates` — список типов (тип/статус/назначение).
- `POST /email-templates/preview` — preview на демо-данных или на своём уведомлении.
- `POST /email-templates/notifications/{id}/preview`, `POST /email-templates/digests/{id}/preview`
  — только владелец (иначе 404).
- `GET /email-templates/projects/{id}/settings` — статус email/SMTP-безопасности без секретов.
- `POST /email-templates/test-send-dry` — **dry-run only**: рендер + проверка гейтов/allowlist,
  получатель маской, реальной отправки нет ни при каких флагах в этом эндпоинте.

### UI

- `/ui/email-templates` — баннер «Реальная email-доставка выключена. Сейчас доступен
  preview/sandbox», safety-карточки (SMTP live / email live / external delivery / footer),
  форма и панель preview (subject/text/HTML экранированный), список шаблонов.
- `/ui/notification-delivery`, `/ui/notification-digests` — ссылки на email-preview + статус
  email-провайдера (mock/sandbox).
- `/ui/settings` — блок «Email-уведомления» (всё выключено; SMTP-пароль не показывается).

### CLI (Makefile)

| Команда | Назначение |
|---|---|
| `make email-template-preview template_type=review_assigned` | preview шаблона на демо-данных |
| `make email-template-preview list=true` | список доступных типов |
| `make email-notification-preview notification_id=1` | preview email уведомления (URL маской) |
| `make email-notification-preview digest_id=1` | preview email дайджеста |
| `make email-test-send to=user@example.ru` | тестовый рендер (DRY-RUN only, получатель маской) |

`--show-unsafe-url true` в `email-notification-preview` печатает полный unsubscribe-URL с сырым
токеном — только для локальной отладки; в лог/аудит он не попадает.

## Флаги конфигурации

| Флаг | Дефолт | Назначение |
|---|---|---|
| `EMAIL_TEMPLATES_ENABLED` | `true` | генерация email-шаблонов (только рендер) |
| `EMAIL_TEMPLATE_PREVIEW_ENABLED` | `true` | preview в API/UI |
| `EMAIL_UNSUBSCRIBE_FOOTER_ENABLED` | `true` | футер отписки в письмах |
| `SMTP_LIVE_SEND_ENABLED` | `false` | реальная SMTP-отправка (нужны ВСЕ флаги) |
| `SMTP_DRY_RUN` | `true` | dry-run режим SMTP |
| `SMTP_HOST` / `SMTP_FROM_EMAIL` | пусто | конфигурация SMTP (иначе «не настроен») |
| `SMTP_TIMEOUT_SECONDS` | `20` | таймаут (клампится в 1..120) |
| `EMAIL_TEST_SEND_ENABLED` | `false` | тестовая отправка (в MVP только dry-run) |
| `EMAIL_TEST_ALLOWED_RECIPIENTS` | пусто | allowlist получателей теста |
| `NOTIFICATION_EMAIL_LIVE_ENABLED` | `false` | реальный email-канал |
| `NOTIFICATION_EXTERNAL_DELIVERY_ENABLED` | `false` | любая внешняя доставка |

Эффективный `smtp_live_send_enabled_effective` = external delivery **и** email live **и** SMTP
live **и** SMTP настроен **и** не dry-run. В MVP — всегда `false`.

## Что дальше

- реальная SMTP-интеграция (включение флагов на проверенном окружении, с мониторингом);
- кастомные шаблоны на аккаунт/проект поверх `email_template_overrides`;
- локализация шаблонов и брендирование (логотип/цвета проекта);
- delivery rate monitor и alerting при всплесках отказов SMTP.
