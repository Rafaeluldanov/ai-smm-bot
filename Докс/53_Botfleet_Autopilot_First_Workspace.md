# 53. Botfleet: Autopilot-first клиентский workspace (v0.5.6)

Главный продуктовый слой поверх всех предыдущих подсистем (schedule automation
[35](35_Botfleet_Schedule_Automation_Engine.md), auto topic
[41](41_Botfleet_Auto_Topic_Selection.md), auto media
[42](42_Botfleet_Auto_Media_Selection.md), платформы/биллинг
[25](25_SaaS_регистрация_проекты_биллинг.md)): **Botfleet — автопилот SMM**. Клиент не должен
разбираться в worker, media decisions, fingerprints, OAuth, webhooks, review pipeline. Он делает
пять шагов и забывает.

> **Безопасность:** это **не** этап включения реальной live-публикации, реальных платежей или
> обхода safety-gates. `AUTOPILOT_AUTO_START_LIVE=false`, `AUTOPILOT_HEALTH_CHECK_WORKER_ENABLED=false`,
> `AUTOPILOT_SHOW_ADVANCED_SETTINGS=false`. Включение автопилота **не меняет** глобальные live-флаги
> (`TELEGRAM/VK/INSTAGRAM_LIVE_PUBLISHING_ENABLED`, `PAYMENTS_LIVE_ENABLED`). При выключенных
> live-условиях посты создаются как `needs_review`, а не публикуются. Секретов/сырых токенов в
> API/UI/логах нет; `publish_due` не вызывается.

## Главный сценарий

1. **Подключить площадки** (Telegram / VK / Instagram / …).
2. **Дать ссылку на Яндекс Диск** с картинками (публичная ссылка + папка).
3. **Выбрать календарь** публикаций (каждый день / по будням / 3 раза в неделю / свои дни; время;
   площадки).
4. **Задать цель и стиль** (продажи/заявки/охват/доверие/экспертность; тон; глубина; CTA).
5. **Нажать «Запустить автопилот»** — и забыть.

Дальше Botfleet сам: выбирает тему → CTA → формат → картинки → пишет глубокий текст → адаптирует
под площадку → публикует по календарю (если live-условия разрешены; иначе безопасно создаёт
`draft/needs_review` и показывает причину) → собирает метрики → учится → улучшает следующие посты.

## Как работает (архитектура)

`ProjectAutopilotProfile` — «панель автопилота» проекта (одна на проект, `project_id` unique). Она
**не заменяет** `CrmPublishingPlan`, а управляет им и хранит упрощённые клиентские настройки
(`calendar_rules`, `content_rules`, `primary_platforms`, `active_blockers`, `setup_progress`).
Секретов не хранит.

`AutopilotService` — тонкий оркестратор поверх существующих подсистем:
- **platform connections** (`PlatformConnectionService`) — подключение площадок и Яндекс Диска;
- **media** (`media_asset_repository`, `MediaQualityService`) — сколько картинок и какого качества;
- **schedule automation** (`ScheduleAutomationService`) — план публикаций, превью, создание
  `needs_review`-постов;
- **billing** (`BillingService`) — баланс и оценка «на сколько постов хватит».

## Health check и блокеры

`run_health_check` считает понятные клиенту блокеры (`AutopilotBlockerType`):

| Блокер | Уровень | Что значит клиенту |
|---|---|---|
| `no_platform_connected` | setup | Подключите хотя бы одну площадку |
| `platform_credentials_missing` | setup | Завершите подключение площадки |
| `no_yandex_disk` | setup | Дайте ссылку на Яндекс Диск |
| `no_media` | setup | Нет картинок — синхронизируйте Диск |
| `weak_media_library` | info | Мало картинок (рекомендуем больше) |
| `no_calendar` | setup | Выберите календарь |
| `no_balance` | blocking | Недостаточно баланса |
| `instagram_public_url_missing` | info | Для Instagram нужен публичный адрес картинок |
| `live_flags_disabled` | info | Условия публикации выключены → посты на проверку |

Приоритет: **сначала настройка** (setup), затем блокирующие (blocking), затем информационные
(info). Поэтому новый проект видит «Нужно настроить» и шаг «Подключить площадку», а не «Нет
баланса». «Следующий лучший шаг» — одна большая кнопка, ведущая на нужный экран.

## Почему live-флаги не включаются автоматически

full_auto — **основной** режим продукта, но он не должен внезапно начать реально публиковать: это
риск для клиента и для площадок. Поэтому автопилот никогда не трогает глобальные
`*_LIVE_PUBLISHING_ENABLED`. Пока они выключены, автопилот в состоянии `running` создаёт посты как
`needs_review` (Botfleet всё пишет и готовит, но не отправляет наружу). Реальная публикация
по-прежнему проходит только через существующие safety-gates и явные live-флаги — включаются
администратором осознанно.

## Полуавтоматический режим

`semi_auto` остаётся вторичным safety/review-режимом: то же самое, но пост всегда идёт на ревью
человеку. Основной сценарий продукта — full_auto.

## UI

Primary-страницы (клиентский язык, без технического жаргона):
- `/ui/today` — что происходит сегодня (запланировано/создано/на проверке/автопилотов работает),
  что требует внимания, следующий лучший шаг, ближайшие публикации.
- `/ui/projects/{id}/autopilot` — «Автопостинг работает сам»: статус (Работает / Нужно настроить /
  Есть проблема / На паузе), большая кнопка (Запустить / Пауза / Исправить), карточки (куда
  публикуем / откуда картинки / когда публикуем / что бот делает сам / что требует внимания),
  баланс и стоимость.
- `/ui/projects/{id}/autopilot/setup` — пошаговый мастер (чек-лист).
- `.../platforms` — большие карточки площадок со статусом.
- `.../media` — публичная ссылка Яндекс Диска, папка, теги, проверка/синхронизация.
- `.../calendar` — простой выбор частоты/времени/площадок.
- `.../rules` — цель / тон / глубина / CTA.

Сложные разделы (эксперименты, решения по темам/картинкам, поиск дублей, доставка уведомлений,
webhooks, безопасность) вынесены в `/ui/advanced`. Sidebar упрощён (Сегодня · Автопилот · Проекты ·
Аналитика · Оплата · Настройки · Advanced). Добавлена мобильная нижняя навигация.

## API

Все под project-гардом (`require_project_access`):

| Метод | Назначение |
|---|---|
| `GET /autopilot/projects/{id}` | дашборд автопилота |
| `GET /autopilot/projects/{id}/checklist` | чек-лист настройки |
| `POST /autopilot/projects/{id}/health-check` | health-check |
| `POST /autopilot/projects/{id}/mode` | full_auto / semi_auto |
| `POST /autopilot/projects/{id}/calendar` | настроить календарь |
| `POST /autopilot/projects/{id}/yandex-disk` | подключить Яндекс Диск |
| `POST /autopilot/projects/{id}/content-rules` | цель/тон/стиль |
| `POST /autopilot/projects/{id}/start` | запустить (блокируется при незавершённой настройке) |
| `POST /autopilot/projects/{id}/pause` | пауза |
| `POST /autopilot/projects/{id}/preview-next` | превью ближайших публикаций (без записи) |
| `POST /autopilot/projects/{id}/first-draft` | первый пост как `needs_review` |
| `GET /autopilot/projects/{id}/client-summary` | простая клиентская сводка |

## Биллинг

На странице автопилота — простой блок: баланс (units), «хватит примерно на N постов», стоимость
одного автопоста (≈ units), «аналитика и обучение включены». Превью и настройка бесплатны; новых
платных действий не вводится (используется существующая стоимость генерации черновика).

## Флаги конфигурации

| Флаг | Дефолт | Назначение |
|---|---|---|
| `AUTOPILOT_UI_ENABLED` | `true` | клиентский workspace |
| `AUTOPILOT_DEFAULT_MODE` | `full_auto` | режим по умолчанию |
| `AUTOPILOT_FULL_AUTO_PRIMARY` | `true` | full_auto — основной режим |
| `AUTOPILOT_REQUIRE_YANDEX_DISK/CALENDAR/PLATFORM` | `true` | обязательные шаги |
| `AUTOPILOT_HEALTH_CHECK_WORKER_ENABLED` | `false` | фоновый health-worker выключен |
| `AUTOPILOT_AUTO_START_LIVE` | `false` | live не включается из UI |
| `AUTOPILOT_SHOW_ADVANCED_SETTINGS` | `false` | advanced скрыт |
| `AUTOPILOT_MIN_MEDIA_ASSETS` / `_RECOMMENDED_MEDIA_ASSETS` | `5` / `30` | объём медиатеки |
| `AUTOPILOT_DEFAULT_POSTS_PER_DAY` / `_PUBLISH_TIME` / `_TIMEZONE` | `1` / `10:00` / `Europe/Moscow` | дефолты календаря |

## Чем отличается от обычных автопостинг-сервисов

Обычный сервис — это **только календарь**: вы сами пишете пост, сами выбираете картинку, он лишь
публикует по расписанию. Botfleet — **автопилот**: сам думает (тема/CTA/формат), сам выбирает
картинки из вашей медиатеки, сам пишет глубокий текст, адаптирует под площадку, и **учится** на
метриках, улучшая следующие посты. Клиент даёт Диск и календарь — остальное делает бот.

## Что дальше

- Yandex Disk auto-sync worker (автоматическая синхронизация медиатеки);
- production live-autopost audit (безопасное включение реальной публикации по клиенту);
- calendar assistant (умные подсказки календаря);
- реальная live-публикация по каждому клиенту с per-tenant флагами;
- упрощённый публичный лендинг и тарифы.


> **Yandex Disk auto-sync (v0.5.7):** клиент загружает картинки в Яндекс Диск — Botfleet сам синхронизирует медиатеку (dry-run/без сети по умолчанию, файлы не удаляются). См. [54_Botfleet_Yandex_Disk_Auto_Sync.md](54_Botfleet_Yandex_Disk_Auto_Sync.md).