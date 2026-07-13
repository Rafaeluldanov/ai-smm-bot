# 57. Botfleet: Telegram-first live rollout (v0.6.0)

Продолжение слоя готовности ([56](56_Botfleet_Live_Autopost_Readiness.md)): первый безопасный
**реальный live-канал** автопилота — **Telegram**. Клиент проверяет готовность, делает предпросмотр
и тестовый прогон, а когда администратор осознанно включает production-флаги — пробует реальную
публикацию. Каждая попытка (dry-run/blocked/published/failed) фиксируется в журнале
``LivePublishAttempt``.

> **Это НЕ включатель live и НЕ обход safety-gates.** Реальная отправка **невозможна** без
> глобального ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` (управляется администратором). По умолчанию:
> ``TELEGRAM_LIVE_ROLLOUT_ALLOW_REAL_SEND=false``, ``TELEGRAM_LIVE_ROLLOUT_DRY_RUN=true``,
> подтверждение ``ENABLE_TELEGRAM_LIVE`` обязательно. Никаких реальных публикаций в тестах (только
> fake-клиент), реальных платежей и внешних вызовов; токены/сырые payload/внутренние пути в журнал
> не попадают; ``publish_due`` не вызывается.

## Почему Telegram — первый live-канал

Telegram-публикация технически проще и надёжнее прочих: групповой бот-токен постит текст и
изображения без OAuth-плясок (в отличие от VK user-token для фото и Instagram Graph API с публичным
image_url). Поэтому Telegram — естественный первый реальный канал, на котором обкатывается весь
production-flow (гейты, подтверждения, журнал, мониторинг) перед расширением на VK/Instagram.

## Условия реальной отправки (все обязательны)

Реальная публикация в Telegram сработает **только если ВСЕ** условия true:

1. глобальный ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` (админ, production env);
2. ``project_live_enabled`` (клиент включил live для проекта, [56](56_Botfleet_Live_Autopost_Readiness.md));
3. ``platform_live_enabled`` (клиент включил Telegram);
4. ``full_auto_live_enabled``;
5. ``readiness_ready`` (проверка готовности прошла);
6. ``TELEGRAM_LIVE_ROLLOUT_ALLOW_REAL_SEND=true`` (rollout kill-switch);
7. подтверждение ``ENABLE_TELEGRAM_LIVE``;
8. существующие safety-gates ``PostPublicationService`` (баланс, креды, ``would_send``).

Эффективный статус: ``can_attempt_live = global AND project AND platform AND full_auto AND ready``
(это ``LiveReadinessService.build_effective_live_gate``); ``can_send_real = can_attempt_live AND
allow_real_send``. Если хоть что-то false — попытка **blocked** (без сети и без списания).

## Global flags vs project/platform flags

Глобальные ``*_LIVE_PUBLISHING_ENABLED`` — рубильник администратора в production. Per-project/
per-platform live (v0.5.9) и rollout ``allow_real_send`` (v0.6.0) — клиентские слои, которые
**дополняют**, но **не обходят** глобальный флаг. Rollout проверяет глобальный флаг через тот же
эффективный гейт; сам сервис глобальные флаги **никогда не меняет**.

## LivePublishAttempt (журнал)

``LivePublishAttempt`` фиксирует каждую попытку: триггер (manual_preview/manual_test/
manual_run_once/schedule_due), режим (dry_run/live_blocked/live), статус (preview/blocked/skipped/
attempted/published/failed), снимок гейтов (global/project/platform/full_auto/readiness/balance),
был ли реальный вызов (``live_attempted``), внешние ссылки при успехе и **безопасный** summary
пейлоада (длина текста, число медиа — без текста/пути/токена). Это доказательство, что
заблокированная попытка **не ходила в сеть и не списала деньги**.

## dry-run / live_if_allowed / live

- **preview** — предпросмотр без записи и без сети;
- **run-once dry** — создаёт attempt (``dry_run``), проверяет гейты, но **никогда** не отправляет;
- **publish-once-if-allowed** — реальная попытка, **только** при всех условиях выше; иначе blocked.

`ScheduleAutomationService` дополнительно **журналирует** live-попытку автопилота по Telegram-слотам
(schedule_due) поверх существующей защиты v0.5.9: заблокированная попытка → attempt ``blocked`` без
списания; успешная → ``published``. Fail-safe: любой сбой журнала не ломает прогон.

## Blocked → без списания

Preview/dry-run/blocked — тарифицируются 0 units (``telegram_live_rollout_preview/run_dry`` и
заблокированная ``publish_attempt``). Реальная публикация списывает существующие publication-units
(``USAGE_AUTO_PUBLISH_ACTION``), один раз, идемпотентно. Дубликат (тот же пост) — blocked.

## API (`/telegram-live-rollout`, под project-гардом)

`GET /projects/{id}` — дашборд · `GET /projects/{id}/attempts` — история ·
`GET /attempts/{id}` — деталь (доступ через её проект) · `POST /projects/{id}/preview` ·
`POST /projects/{id}/run-dry` · `POST /projects/{id}/publish-once-if-allowed` (по умолчанию blocked)
· `GET /projects/{id}/effective-status`. Ни один эндпоинт не меняет глобальные флаги и не публикует
без всех гейтов.

## UI

`/ui/projects/{id}/telegram-live-rollout` — «Telegram: первый live-канал автопилота»: статус,
карточки (подключение, готовность, последняя попытка), условия публикации (global/project/platform/
full-auto/allow_real_send), блокеры, кнопки «Проверить Telegram live / Предварительный просмотр /
Тестовый запуск без отправки / Попробовать live один раз», поле подтверждения ``ENABLE_TELEGRAM_LIVE``
и явное предупреждение про production env-флаги, история попыток. Клиентский язык, без кнопки прямой
публикации в обход гейтов. Страницы live-readiness и автопилота ведут сюда.

## CLI

```bash
make telegram-live-rollout-dashboard project_id=1
make telegram-live-rollout-preview project_id=1 post_id=1
make telegram-live-rollout-run-dry project_id=1 post_id=1
make telegram-live-rollout-publish-once project_id=1 post_id=1 \
    confirmation=ENABLE_TELEGRAM_LIVE dry_run=true
```

Все CLI — offline, dry-run по умолчанию, ничего не публикуют без всех флагов, глобальные флаги не
меняют, секретов не печатают.

## Модель / миграция

Таблица ``live_publish_attempts`` — миграция ``0042_live_publish_attempts`` (down_revision
``0041_live_readiness``), индексы по account/project/platform/post/publication/schedule_run/trigger/
mode/status/idempotency/started/created. Секретов не хранит.

## Что дальше

- production media proxy домен (публичные HTTPS image_url);
- VK user-token photo strategy (загрузка фото во VK);
- завершение Instagram API;
- live-мониторинг и алерты по попыткам;
- упрощённый публичный лендинг и тарифы.
