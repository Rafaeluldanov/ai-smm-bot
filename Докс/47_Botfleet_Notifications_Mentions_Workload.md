# 47. Botfleet: уведомления, упоминания и нагрузка ревьюеров (v0.5.0)

Слой поверх collaborative review ([46](46_Botfleet_Media_Curation_Review.md)): централизованные
**внутренние (in-app) уведомления**, **упоминания (@mentions)**, **inbox** пользователя и
**нагрузка ревьюеров** с SLA. Команда видит, кому что назначено, где просрочка и что требует
внимания — без внешних писем/пушей.

> **Безопасность:** это **не** этап live-публикаций, **не** реальных платежей и **не** внешней
> доставки (email/SMS/Telegram push/webhook). Вся внешняя доставка **выключена по умолчанию**
> (`NOTIFICATIONS_EMAIL_ENABLED=false`, `NOTIFICATIONS_DIGEST_ENABLED=false`,
> `NOTIFICATIONS_WEBHOOK_ENABLED=false`, `NOTIFICATIONS_EXTERNAL_DELIVERY_ENABLED=false`) и в MVP
> **ничего не отправляет наружу**; worker выключен (`NOTIFICATIONS_WORKER_ENABLED=false`),
> dry-run по умолчанию. Уведомления **не роняют** основное действие; тексты/метаданные
> санитизируются (без токенов и внутренних путей). Уведомления **бесплатны** в MVP.

## Зачем нужны уведомления

Collaborative review дал задачи, ответственных и комментарии, но участник не узнавал, что его
назначили, упомянули или что задача просрочена. Уведомления закрывают этот разрыв: назначение,
упоминание, запрос правок, смена статуса, просрочка, «пост ждёт ревью», winner A/B, обновление
профиля обучения, worker-рекомендация, низкий баланс — всё в одном inbox.

## Термины

- **NotificationChannel**: `in_app · email · digest · webhook` (внешние выключены).
- **NotificationStatus**: `unread · read · archived · dismissed · failed`.
- **NotificationType**: `review_assigned · review_mentioned · review_comment ·
  review_changes_requested · review_approved · review_rejected · review_applied · task_overdue ·
  post_needs_review · post_approved · post_rejected · experiment_suggestion_created ·
  experiment_winner_selected · learning_profile_updated · billing_balance_low ·
  worker_attention_needed · system_notice`.
- **NotificationPriority**: `low · normal · high · urgent`.
- **MentionStatus**: `resolved · unresolved · notified · ignored`.
- **SlaStatus**: `ok · due_soon · overdue · critical`.

## In-app уведомления

`NotificationService.create_notification` создаёт внутреннее уведомление получателю с
**дедупликацией**: одинаковые непрочитанные (получатель + тип + сущность) в окне
`NOTIFICATIONS_DEDUP_WINDOW_MINUTES` (30 мин) не плодятся. Хранится лимит на пользователя
(`NOTIFICATIONS_MAX_PER_USER`, старые сверх лимита архивируются). Каждое создание/прочтение
пишется в аудит. Внешней доставки нет — только `in_app`.

Хуки (безопасные, не роняют действие):
- `notify_assignee` — назначили задачу → `review_assigned`;
- `notify_comment` — комментарий → `review_comment` ответственному/ревьюеру (кроме автора);
- `notify_mentions` — упоминания → `review_mentioned` резолвленным;
- `notify_status_change` — approved/rejected/applied/changes_requested;
- `notify_project_owner` — предложения/winner/обучение → владельцу проекта;
- `notify_overdue_tasks` — просрочка → `task_overdue`.

## Упоминания (@mentions)

`mention_parser_service` извлекает три формата: `@email@example.com`, `@username` (по local-part
email или slug имени), `@user_id:123`. Резолв — **строго в пределах аккаунта** (владелец +
активные участники); внешнего поиска нет. Найденный пользователь → `AppMention.status=notified`
+ уведомление `review_mentioned`; **не найденный → `unresolved`** и основное действие (комментарий)
**не падает**. Кириллический текст вокруг упоминания парсится корректно.

## Нагрузка ревьюеров и SLA

`build_review_workload(project_id)` группирует активные задачи ревью медиатеки по ответственному:
`assigned_count`, `overdue_count`, `high_priority_count`, `avg_age_hours` и `sla_status`. SLA
считается из `MEDIA_CURATION_REVIEW_SLA_HOURS` (72 ч): `ok` → `due_soon` (возраст ≥ 75% SLA) →
`overdue` (есть просрочка) → `critical` (≥ 3 просрочек). Просрочка учитывает грейс-период
`NOTIFICATIONS_OVERDUE_GRACE_HOURS` (24 ч).

## Overdue-скан

`notify_overdue_tasks(project_id, dry_run)` сканирует просроченные активные задачи ревью. В
dry-run — только счётчики (аудит `overdue_scan.previewed`); в write-режиме — создаёт
`task_overdue` ответственному (аудит `overdue_scan.created`). Worker выключен по умолчанию —
скан запускается вручную (CLI/API dry).

## Preferences

Настройки уведомлений пользователя: `in_app` включён; `email`/`digest`/`webhook` **выключены**,
пока нет реальной доставки — сервис принудительно оставляет их выключенными
(`external_delivery` off). Возможны per-type настройки и `quiet_hours` (задел на будущее).

## Интеграция

- **media curation review**: assign/comment/mention/request_changes/approve/reject/apply/restore
  создают уведомления;
- **post review**: submit→needs_review, approve/reject/request_changes — владельцу проекта;
- **experiments/learning**: генерация предложений, выбор winner, пересчёт профиля — владельцу;
- **audit log**: пишет создание/прочтение уведомления и создание/резолв упоминания.

Во всех интеграциях: **нет получателя → тихо пропускаем**; ошибка уведомления **логируется, но
не ломает** основное действие.

## UI

- **колокольчик** в шапке с бейджем непрочитанных (загрузка `/notifications/unread-count`);
- `/ui/notifications` — inbox: фильтры (непрочитанные/все, тип, приоритет), карточки (заголовок,
  сообщение, приоритет, статус, сущность, `Открыть`/`Прочитано`/`Скрыть`), «Прочитать все»;
- `/ui/projects/{id}/notifications` — дашборд проекта (непрочитанные/overdue/high-urgent/по типу);
- `/ui/projects/{id}/review-workload` — таблица ревьюеров (задачи/overdue/high-urgent/возраст/SLA);
- `/ui/settings` — секция «Уведомления» (in-app вкл; email/дайджест/webhook выкл; внешней
  доставки нет).

## CLI

```bash
make notifications-inbox user_id=1 status=unread
make notifications-overdue-scan project_id=1 dry_run=true   # dry-run по умолчанию
make notifications-workload project_id=1
```

## Флаги конфигурации

| Флаг | По умолчанию | Смысл |
| --- | --- | --- |
| `NOTIFICATIONS_ENABLED` | `true` | Уведомления включены |
| `NOTIFICATIONS_IN_APP_ENABLED` | `true` | Внутренний канал включён |
| `NOTIFICATIONS_EMAIL_ENABLED` | `false` | Email (выключен) |
| `NOTIFICATIONS_DIGEST_ENABLED` | `false` | Дайджест (выключен) |
| `NOTIFICATIONS_WEBHOOK_ENABLED` | `false` | Webhook (выключен) |
| `NOTIFICATIONS_WORKER_ENABLED` | `false` | Worker-скан (выключен) |
| `NOTIFICATIONS_DRY_RUN` | `true` | Dry-run по умолчанию |
| `NOTIFICATIONS_MAX_PER_USER` | `500` | Лимит уведомлений на пользователя |
| `NOTIFICATIONS_DEDUP_WINDOW_MINUTES` | `30` | Окно дедупликации |
| `NOTIFICATIONS_MENTION_ENABLED` | `true` | Упоминания включены |
| `NOTIFICATIONS_OVERDUE_SCAN_ENABLED` | `true` | Скан просрочек включён |
| `NOTIFICATIONS_OVERDUE_GRACE_HOURS` | `24` | Грейс-период просрочки |
| `NOTIFICATIONS_EXTERNAL_DELIVERY_ENABLED` | `false` | Внешняя доставка (запрещена) |
| `MEDIA_CURATION_REVIEW_SLA_HOURS` | `72` | SLA ревью медиатеки |
| `POST_REVIEW_SLA_HOURS` | `48` | SLA ревью постов |
| `EXPERIMENT_REVIEW_SLA_HOURS` | `72` | SLA ревью экспериментов |

## Биллинг

Внутренние уведомления — **бесплатно в MVP**: `notification_create`,
`notification_overdue_scan`, `notification_digest` стоят 0 units. Email/дайджест/webhook пока
выключены и не тарифицируются.

## Аудит

`notification.created · notification.read · notification.dismissed ·
notification.preference.updated · mention.created · mention.resolved ·
notification.overdue_scan.previewed · notification.overdue_scan.created · workload.viewed`.
Метаданные: `notification_id · recipient_user_id · project_id · entity_type/entity_id ·
notification_type` — без секретов и внутренних путей.

## Приватность

Пользователь видит **только свои** уведомления; проектные дашборды/workload/mentions — под
project-гардом. Межклиентских уведомлений нет; в API/UI/CLI/аудите — только id/типы/статусы.

## Что дальше

- email-провайдер (реальная доставка);
- уведомления Telegram-ботом;
- webhook-уведомления;
- планировщик дайджестов;
- autocomplete упоминаний;
- балансировка нагрузки ревьюеров (workload balancing).
