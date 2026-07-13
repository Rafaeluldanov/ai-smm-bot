# 54. Botfleet: авто-синхронизация Яндекс Диска (v0.5.7)

Продолжение автопилота ([53](53_Botfleet_Autopilot_First_Workspace.md)): клиент **загружает
картинки в Яндекс Диск** — Botfleet сам синхронизирует медиатеку для автопостинга. Клиент не
запускает CLI, не разбирает медиа вручную, не думает про sync/tags/fingerprints/quality. Он даёт
публичную ссылку на папку и загружает фото — остальное делает система.

> **Безопасность:** это **не** этап live-публикации, реальных платежей, внешнего AI или удаления
> файлов. По умолчанию: `YANDEX_AUTO_SYNC_NETWORK_ENABLED=false`, `YANDEX_AUTO_SYNC_WORKER_ENABLED=false`,
> `YANDEX_AUTO_SYNC_DRY_RUN=true`, `YANDEX_AUTO_SYNC_AUTO_DELETE=false`, `YANDEX_AUTO_SYNC_AUTO_HIDE=false`.
> При выключенной сети реальный sync-сервис **вообще не создаётся**; preview/dry-run **не пишут
> медиа и не ходят в сеть**; `run` с `dry_run=false` при выключенной сети безопасно
> **блокируется**. Файлы **никогда не удаляются и не скрываются**; эндпоинта удаления нет.
> Секретов/сырых токенов/внутренних путей наружу нет; `public_url` — только маской; `publish_due`
> не вызывается.

## Главный сценарий

1. Клиент даёт **публичную ссылку** на папку Яндекс Диска (public URL mode) + имя папки (root
   folder, например `SMM`) + опциональные базовые теги.
2. Клиент **загружает картинки** в эту папку.
3. Botfleet периодически **проверяет Диск**, находит новые файлы, синхронизирует `MediaAsset`,
   проставляет базовые теги, прогоняет **quality scoring → fingerprint/dedup → curation preview**.
4. Обновляется статус автопилота; клиент видит простое состояние: «Медиа готово: N картинок».
5. Автопилот использует эти картинки для автопостинга.

## Как работает

`ProjectYandexSyncProfile` — «панель синхронизации» проекта (одна на проект): `public_url`
(наружу — маской), `root_folder`, `default_tags`, `sync_frequency_minutes`, счётчики
(`media_count`/`image_count`/`video_count`/`new_media_count`/…), `active_blockers`,
`last_sync_*`/`next_sync_at`. `YandexAutoSyncRun` — история проверок (что видели/импортировали,
блокеры, warnings).

`YandexAutoSyncService` — тонкий оркестратор поверх существующих подсистем:
- **public media sync** (`PublicYandexDiskMediaSyncService`) — реальная синхронизация (только за
  флагами);
- **media quality** (`MediaQualityService.score_project_media`) — оценка качества;
- **fingerprint** (`MediaFingerprintService.calculate_project_fingerprints`) — дедупликация;
- **curation** (`MediaCurationService.preview_curation_tasks`) — превью порядка в медиатеке;
- **autopilot** — обновление health после синхронизации.

## Dry-run и network флаги — двойная защита

Два независимых флага защищают от случайных вызовов:

- `YANDEX_AUTO_SYNC_DRY_RUN` (по умолчанию `true`) — не писать медиа.
- `YANDEX_AUTO_SYNC_NETWORK_ENABLED` (по умолчанию `false`) — не ходить в сеть.

Реальная синхронизация выполняется **только** при `network_enabled=true` И `dry_run=false`
(в `run_sync`: `do_real = not dry_run and network_enabled_effective`). Пока network выключен, метод
`_public_sync_service()` не вызывается — сетевой клиент не создаётся вообще. `run` с `dry_run=false`
при выключенной сети возвращает статус `blocked` с блокером `network_disabled` и ничего не пишет.

## Health check и блокеры

`health_check` считает понятные клиенту блокеры (`YandexAutoSyncBlockerType`): `no_yandex_disk`
(нет ссылки), `invalid_public_url`, `unsupported_folder`, `no_media_found`, `too_few_media`,
`sync_disabled` (на паузе), `network_disabled` (тестовый режим). «Следующий лучший шаг» — одна
подсказка.

## Интеграция с автопилотом

- Автопилотный блокер `no_yandex_disk` удовлетворяется, если public_url задан **либо** в подключении
  площадки, **либо** в профиле синхронизации.
- `yandex_disk_status` в дашборде автопилота использует профиль синхронизации (`auto_sync: true`).
- После синхронизации `_update_profile_after_run` обновляет health автопилота.
- Никаких live-флагов автопилот/синхронизация не включают.

## Интеграция с scheduler worker

В `SchedulerWorkerTickResult` добавлены поля `yandex_auto_sync_enabled`/`yandex_auto_sync_dry_run`/
`yandex_sync_profiles_scanned`/`yandex_sync_runs_created`/`yandex_sync_media_imported`/
`yandex_sync_errors`/`yandex_sync_blockers`. Шаг `_process_yandex_sync` выполняется в тике **только**
при `YANDEX_AUTO_SYNC_WORKER_ENABLED=true` (по умолчанию выключен), в dry-run — превью без записи.

## API

Все под project-гардом (`require_project_access`); эндпоинта удаления нет:

| Метод | Назначение |
|---|---|
| `GET /yandex-sync/projects/{id}` | дашборд синхронизации |
| `GET /yandex-sync/projects/{id}/profile` | профиль (url — маской) |
| `POST /yandex-sync/projects/{id}/profile` | настроить профиль |
| `POST /yandex-sync/projects/{id}/health-check` | health-check |
| `POST /yandex-sync/projects/{id}/preview` | предпросмотр (без записи) |
| `POST /yandex-sync/projects/{id}/run-dry` | dry-run синхронизация |
| `POST /yandex-sync/projects/{id}/run` | синхронизация (реальная — только при network+не dry) |
| `POST /yandex-sync/projects/{id}/pause` / `/resume` | пауза/возобновление |
| `GET /yandex-sync/projects/{id}/runs` | история проверок |
| `POST /yandex-sync/worker/tick-dry` | dry-run tick воркера (авторизация) |

## UI

- `/ui/projects/{id}/yandex-sync` — «Картинки из Яндекс Диска»: карточки (подключение, медиатека,
  последняя синхронизация, что дальше), форма (public_url/папка/теги/частота), кнопки (Проверить,
  Синхронизировать сейчас, Предварительная проверка, Пауза/Возобновить), история проверок,
  предупреждения «Файлы не удаляются», «В тестовом режиме внешняя сеть выключена».
- `/ui/projects/{id}/autopilot/media` — упрощена: статус синхронизации + ссылка на страницу Яндекс
  Диска + кнопка синхронизации.

## CLI (Makefile)

| Команда | Назначение |
|---|---|
| `make yandex-sync-profile project_id=1` | сводка профиля (url маской) |
| `make yandex-sync-preview project_id=1` | предпросмотр (без записи) |
| `make yandex-sync-run project_id=1 dry_run=true` | синхронизация (dry-run) |
| `make yandex-sync-worker-tick dry_run=true` | tick воркера (dry-run) |

## Флаги конфигурации

| Флаг | Дефолт | Назначение |
|---|---|---|
| `YANDEX_AUTO_SYNC_ENABLED` | `true` | UI/API синхронизации |
| `YANDEX_AUTO_SYNC_WORKER_ENABLED` | `false` | фоновый sync-worker |
| `YANDEX_AUTO_SYNC_DRY_RUN` | `true` | dry-run (без записи медиа) |
| `YANDEX_AUTO_SYNC_NETWORK_ENABLED` | `false` | реальные сетевые вызовы |
| `YANDEX_AUTO_SYNC_PUBLIC_URL_ENABLED` | `true` | режим публичной ссылки |
| `YANDEX_AUTO_SYNC_OAUTH_ENABLED` | `false` | OAuth-режим (на будущее) |
| `YANDEX_AUTO_SYNC_DEFAULT_FREQUENCY_MINUTES` | `60` | частота (кламп 5..1440) |
| `YANDEX_AUTO_SYNC_MAX_PROJECTS_PER_TICK` | `20` | лимит проектов за tick |
| `YANDEX_AUTO_SYNC_MAX_FILES_PER_RUN` | `500` | лимит файлов за прогон |
| `YANDEX_AUTO_SYNC_MIN/RECOMMENDED_MEDIA_ASSETS` | `5`/`30` | объём медиатеки |
| `YANDEX_AUTO_SYNC_RUN_QUALITY_SCORING/FINGERPRINTING/CURATION_PREVIEW` | `true` | пост-обработка |
| `YANDEX_AUTO_SYNC_AUTO_DELETE` / `_AUTO_HIDE` | `false` | удаление/скрытие — выключено |

## Биллинг

Синхронизация Яндекс Диска — **бесплатно в MVP** (preview/run/worker-tick = 0 units; quality/
fingerprint/curation после синхронизации тоже бесплатны). Неуспешная синхронизация не списывает
units. Крупная реальная синхронизация может стать платной в будущем.

## Что дальше

- реальный сетевой worker в production (с включённой сетью, под мониторингом);
- OAuth Яндекс Диска (приватные диски);
- инкрементальная синхронизация по hash;
- теги по папкам;
- веб-загрузка картинок прямо в Botfleet.

> **Дальше — Calendar assistant (v0.5.8):** когда картинки готовы, клиент выбирает цель и частоту, а Botfleet сам строит календарь автопостинга. См. [55_Botfleet_Autopilot_Calendar_Assistant.md](55_Botfleet_Autopilot_Calendar_Assistant.md).
