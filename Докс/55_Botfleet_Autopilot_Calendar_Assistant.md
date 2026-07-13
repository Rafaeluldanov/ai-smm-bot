# 55. Botfleet: помощник календаря автопилота (v0.5.8)

Продолжение автопилота ([53](53_Botfleet_Autopilot_First_Workspace.md)) и авто-синхронизации
Яндекс Диска ([54](54_Botfleet_Yandex_Disk_Auto_Sync.md)): клиент **выбирает цель и частоту** —
Botfleet сам строит **календарь автопостинга**. Клиент не думает про расписание, дни недели,
времена, распределение по площадкам — он говорит «хочу продажи / 3 раза в неделю», а система
предлагает готовый календарь, распределяет дни/время, учитывает площадки, количество картинок,
баланс и (если есть) лучшие часы обучения, и по одному нажатию применяет план к автопилоту.

> **Безопасность:** это **не** этап live-публикации, реальных платежей, внешнего AI или удаления
> файлов. Построение и применение календаря **не публикуют** и **не включают** глобальные
> live-флаги (`autopilot_calendar_live_start_enabled=false`). Реальная публикация по-прежнему
> проходит существующие условия безопасности автопилота. По умолчанию:
> `AUTOPILOT_CALENDAR_ASSISTANT_ENABLED=true`, `AUTOPILOT_CALENDAR_ASSISTANT_DRY_RUN=true`,
> `AUTOPILOT_CALENDAR_AUTO_APPLY_ENABLED=true`, `AUTOPILOT_CALENDAR_LIVE_START_ENABLED=false`.
> Preview/create-dry-run **ничего не пишут**; `publish_due` не вызывается; секретов/сырых токенов
> наружу нет; внешних API-вызовов в тестах нет; DELETE-эндпоинтов нет.

## Главный сценарий

1. Клиент подключил площадки и Яндекс Диск (этапы 53–54).
2. Открывает **«Календарь автопостинга»**, выбирает **цель** (продажи / заявки / охваты / доверие /
   экспертность / смешанная) и **частоту** (готовые пресеты) — или жмёт «Подобрать за меня».
3. **Предварительный просмотр**: Botfleet показывает дни/время, число постов в месяц, сколько нужно
   картинок, примерную стоимость (units/мес) и риски (мало картинок, низкий баланс, нет площадок и
   т.п.).
4. **Создать календарь** → сохраняется черновик `AutopilotCalendarPlan`.
5. **Применить к автопилоту** → создаётся/обновляется `CrmPublishingPlan`, календарь становится
   активным. Дальше автопилот сам готовит и публикует посты по плану (с учётом условий
   безопасности).

## Как работает

`AutopilotCalendarPlan` — «клиентский» слой календаря (черновик/активный/пауза/архив): выбранный
пресет и цель, площадки/дни/времена/постов-в-день, часовой пояс, стратегия времени,
сгенерированные правила и сигналы-источники, риск-флаги, оценки (постов/мес, units/мес, нужно
картинок), уверенность, ссылки на связанные `CrmPublishingPlan`. Пресеты (`CALENDAR_PRESET_DEFS`):
`daily`, `weekdays`, `three_per_week`, `two_per_week`, `soft_presence`, `launch_campaign`,
`intensive_month`, `custom`.

`AutopilotCalendarAssistantService` — тонкий оркестратор поверх существующих подсистем:
- **медиа** (`media_asset_repository.count_media_assets`) — сколько картинок есть;
- **обучение** (`client_learning_repository.get_profile(...).best_publish_times`) — лучшие часы
  (если накоплены), иначе базовое время из конфига;
- **баланс** (`BillingService.get_balance`) и **юнит-экономика**
  (`UnitEconomicsService.estimate_schedule_generation_units`) — стоимость и «на сколько хватит»;
- **автопилот** (`AutopilotService.configure_calendar`) — применение календаря создаёт
  `CrmPublishingPlan` (с `frequency="custom"` и точными днями недели, чтобы сохранить пресет).

Методы: `build_calendar_presets`, `recommend_calendar`, `preview_calendar`, `estimate_calendar_cost`,
`create_calendar_plan(dry_run=True)`, `apply_calendar_to_project`, `build_calendar_dashboard`,
`pause_calendar`, `resume_calendar`, `archive_calendar_plan`.

**Риски** (severity `setup`/`info`): `no_platforms`, `no_media`, `too_many_posts_for_media`,
`too_low_balance`, `no_learning_data`, `weekend_posts`, `live_disabled`, `timezone_missing`.

## Интеграция с автопилотом

- Блокер `no_calendar` снимается, если есть активный `CrmPublishingPlan` **или** активный
  `AutopilotCalendarPlan`.
- Дашборд автопилота (`build_autopilot_dashboard`) содержит блок `calendar_assistant` (есть ли
  активный календарь, пресет/цель/дни/времена, ссылка на страницу).
- Действие `configure_calendar`/`open_calendar` ведёт на новую страницу помощника.

## API (`/autopilot-calendar`, под project-гардом)

`GET /projects/{id}` — дашборд · `GET /projects/{id}/presets` — пресеты ·
`POST /projects/{id}/recommend` — рекомендация · `POST /projects/{id}/preview` — предпросмотр ·
`POST /projects/{id}/create-dry-run` — проверка без записи · `POST /projects/{id}/create` —
создать · `POST /projects/{id}/plans/{plan_id}/apply` — применить ·
`POST /projects/{id}/plans/{plan_id}/archive` — архивировать ·
`POST /projects/{id}/pause` · `POST /projects/{id}/resume`.

## UI

`/ui/projects/{id}/autopilot/calendar-assistant` — «Календарь автопостинга»: цель, частота
(пресеты), площадки, время, «Предварительный просмотр» / «Создать календарь» / «Применить к
автопилоту» / «Вернуться к автопилоту». Клиентский язык, без техжаргона. Страница автопилота ведёт
сюда из карточки «Когда публикуем», страница «Сегодня» — из пустого состояния ближайших публикаций.

## CLI

```bash
make autopilot-calendar-preview   project_id=1 preset=three_per_week goal=mixed time=10:00
make autopilot-calendar-create    project_id=1 preset=three_per_week dry_run=true   # dry-run по умолчанию
make autopilot-calendar-apply     project_id=1 calendar_plan_id=3
make autopilot-calendar-dashboard project_id=1
```

Все CLI — offline и безопасны: preview/create(dry-run) ничего не пишут, apply создаёт только план
публикаций (без реальной публикации), live-флаги не трогаются.

## Конфигурация (`.env`)

| Переменная | Дефолт | Значение |
|---|---|---|
| `AUTOPILOT_CALENDAR_ASSISTANT_ENABLED` | `true` | помощник включён |
| `AUTOPILOT_CALENDAR_ASSISTANT_DRY_RUN` | `true` | безопасный dry-run |
| `AUTOPILOT_CALENDAR_AUTO_APPLY_ENABLED` | `true` | разрешить применение к автопилоту |
| `AUTOPILOT_CALENDAR_LIVE_START_ENABLED` | `false` | **не** включает live-публикацию |
| `AUTOPILOT_CALENDAR_DEFAULT_PRESET` | `three_per_week` | пресет по умолчанию |
| `AUTOPILOT_CALENDAR_DEFAULT_GOAL` | `mixed` | цель по умолчанию |
| `AUTOPILOT_CALENDAR_DEFAULT_TIMEZONE` | `Europe/Moscow` | часовой пояс |
| `AUTOPILOT_CALENDAR_DEFAULT_TIME` | `10:00` | базовое время публикации |
| `AUTOPILOT_CALENDAR_MAX_POSTS_PER_DAY` | `3` | максимум постов в день |
| `AUTOPILOT_CALENDAR_MAX_PLATFORMS` | `5` | максимум площадок |
| `AUTOPILOT_CALENDAR_MIN_MEDIA_PER_MONTH` | `10` | порог «мало картинок» |
| `AUTOPILOT_CALENDAR_USE_LEARNING_BEST_TIMES` | `true` | использовать лучшие часы обучения |
| `AUTOPILOT_CALENDAR_USE_BALANCE_ESTIMATE` | `true` | учитывать баланс в оценках |

## Модель данных / миграция

`autopilot_calendar_plans` (миграция `0040_autopilot_calendar_plans`, down_revision
`0039_yandex_auto_sync`) + индексы по `account_id`/`project_id`/`autopilot_profile_id`/`status`/
`preset`/`goal`/`created_at`.

## Всё бесплатно в MVP

Preview/create/apply тарифицируются 0 units (`autopilot_calendar_preview/create/apply`);
стоимость появляется только при реальной генерации/публикации постов автопилотом.

> **Дальше — Live autopost readiness (v0.5.9):** когда календарь применён, перед реальной
> автопубликацией проверяется готовность проекта/площадок, а клиент включает live явно (с
> подтверждением), не обходя глобальные live-флаги. См.
> [56_Botfleet_Live_Autopost_Readiness.md](56_Botfleet_Live_Autopost_Readiness.md).
