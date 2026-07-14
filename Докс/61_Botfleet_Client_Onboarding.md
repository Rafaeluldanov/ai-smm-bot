# 61. Botfleet: Клиентский онбординг — «запуск автопилота за 5 минут» (v0.6.4)

Клиентский мастер первого запуска: 5 простых шагов, а Botfleet сам создаёт проект, autopilot-профиль,
media-профиль, календарь, проверяет готовность и делает первый preview. Клиент **не видит**
worker/миграции/токены/live-флаги/готовность/биллинг/репозитории/API — только 5 шагов.

> **После онбординга система READY, но LIVE=OFF.** Онбординг НЕ включает реальную публикацию и НЕ
> трогает глобальные `*_LIVE_PUBLISHING_ENABLED`: делается только **preview** первого поста
> (needs_review draft). Реальная публикация включается отдельно и осознанно (через готовность +
> Telegram runbook [60](60_Botfleet_Telegram_Live_Runbook.md)). Секретов/токенов онбординг не хранит.

## Путь клиента (5 минут)

| Шаг | Экран | Клиент вводит | Botfleet делает (скрыто) |
|---|---|---|---|
| 1 | Ваш бизнес | название, категория, о компании, аудитория | Account + Project + AutopilotProfile (is_enabled=False), сохраняет контекст |
| 2 | Ваши материалы | ссылка на Яндекс Диск, папка | `ProjectYandexSyncProfile` (configure_profile — **без сетевой синхронизации**) |
| 3 | Где публиковать | Telegram / VK / Instagram | platform connections (`live_enabled` всегда OFF; креды опциональны) |
| 4 | Что должен делать автопилот | цель + частота | content_rules (цель) + `configure_calendar` (CrmPublishingPlan) + `AutopilotCalendarPlan` |
| 5 | Запустите автопилот | — | LiveReadiness dry-run + первый preview (draft), возврат «Создать первый пост» |

Прогресс: 20% → 40% → 60% → 80% → 100%.

## Автоматические действия

`start_onboarding` → создаёт (если нет) Account + owner-membership + Project (slug генерится) +
привязывает account_id + `AutopilotService.get_or_create_profile` (setup_required, **is_enabled=False**)
+ `OnboardingSession`. Повторный старт возвращает активную сессию (идемпотентно).

Шаги делегируют существующим сервисам (без нового кода публикации):
- media → `YandexAutoSyncService.configure_profile` (никакого `run_sync` — сети нет);
- platforms → `PlatformConnectionService.upsert_connection` (`live_enabled` форсится в False);
- goal → `AutopilotService.configure_content_rules` (business_goal) + `configure_calendar`
  (реальное расписание CrmPublishingPlan) + `AutopilotCalendarAssistantService.create_calendar_plan`
  (клиентский план). Маппинг: цель `sales/brand/reach/expertise` → `sales/trust/reach/expertise`;
  частота `daily/3_week/weekly` → preset `daily/three_per_week/two_per_week` + расписание;
- finish → `LiveReadinessService.run_project_readiness_check(dry_run=True)` (ничего не пишет) +
  `AutopilotService.create_first_draft_now` (needs_review draft — **preview, не публикация**).

## Как новый клиент запускает автопилот

1. Открывает `/ui/onboarding` → «Запустите AI-автопилот за 5 минут».
2. Проходит 5 шагов (бизнес → материалы → площадки → цель → запуск).
3. На финале видит: ✓ Материалы ✓ Календарь ✓ Площадки ✓ AI подготовка + кнопку «Создать первый пост».
4. Автопилот **готов и настроен**, но реальная публикация **выключена** — клиент включает её отдельно,
   когда готов (готовность + runbook).

## Безопасность

- `finish` возвращает `live_enabled: false`; `build_effective_live_gate.can_publish_live` остаётся
  False (проверено тестами).
- В `OnboardingSession.platform_data` хранятся только `selected`/`connected` — не токены (секреты
  живут write-only в `CrmSmmResource`, замаскированы).
- tenant isolation: сессия строго привязана к `user_id`; чужую сессию не отдаём (404).
- Сбой оркестрации любого шага (`_soft`) не роняет онбординг.

## Данные

Модели `OnboardingSession` (5-шаговая сессия, business/media/platform/goal_data JSON, completion %) +
`OnboardingStepResult` (журнал шагов), миграция **`0046_client_onboarding`** (down_revision
`0045_telegram_live_runbook`). SQLite+PostgreSQL. Настройки: без новых секретов.

## API

Все под auth (`get_current_user`), tenant isolation в сервисе:
- `POST /onboarding/start` — начать/возобновить;
- `GET /onboarding/{session_id}` — состояние;
- `POST /onboarding/{session_id}/{business,media,platforms,goal,finish}` — шаги.

UI: `/ui/onboarding` (5-шаговый мастер + прогресс-бар).

## CLI

```
make onboarding-start user_id=1 company="TEEON"
make onboarding-status session_id=1
make onboarding-demo user_id=1     # полный проход 5 шагов, LIVE=OFF
```
