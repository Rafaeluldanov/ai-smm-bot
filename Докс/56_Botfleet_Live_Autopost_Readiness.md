# 56. Botfleet: готовность к реальной автопубликации (v0.5.9)

Продолжение автопилота ([53](53_Botfleet_Autopilot_First_Workspace.md)), авто-синхронизации
([54](54_Botfleet_Yandex_Disk_Auto_Sync.md)) и календаря ([55](55_Botfleet_Autopilot_Calendar_Assistant.md)):
критический слой **безопасного перехода от автопилота к РЕАЛЬНОЙ автопубликации** по календарю для
конкретного клиента/проекта/площадки. Клиент видит простое: «Автопилот готов к реальной публикации /
не готов / что нужно исправить» — и включает live **явно**, с подтверждением.

> **Это НЕ этап массового включения live и НЕ обход safety-gates.** Реальная публикация по-прежнему
> **невозможна без глобальных** `*_LIVE_PUBLISHING_ENABLED` флагов (управляются администратором).
> Новый per-project/per-platform switch **НЕ обходит** глобальные флаги — он их **дополняет**.
> По умолчанию: `LIVE_READINESS_DRY_RUN=true`, `LIVE_READINESS_WORKER_ENABLED=false`,
> `LIVE_READINESS_AUTO_ENABLE=false`, `LIVE_READINESS_PROBE_EXTERNAL_API=false`,
> `LIVE_READINESS_ALLOW_GLOBAL_FLAG_OVERRIDE=false`, подтверждение обязательно. Никаких реальных
> публикаций в тестах, внешних probe-вызовов и сырых токенов наружу; `publish_due` не вызывается.

## Почему full_auto ≠ live

`full_auto` (режим автопилота) означает «бот сам готовит и, если разрешено, публикует». Но
**реальная** отправка проходит несколько независимых гейтов, и все обязательны:

1. **Глобальный флаг** `*_LIVE_PUBLISHING_ENABLED` (админ) — иначе `would_send=false` и пост уходит
   на проверку.
2. **project_live_enabled** — клиент явно включил реальную публикацию для проекта.
3. **platform_live_enabled** — клиент явно включил площадку.
4. **full_auto_live_enabled** — клиент разрешил автономную публикацию.
5. **readiness_ready** — проверка готовности прошла (автопилот, календарь, медиа, баланс, площадки).

Эффективный гейт: `can_publish_live = global AND project AND platform AND full_auto AND ready`.
Если хоть один false — пост создаётся как `needs_review`/`scheduled` **без реальной отправки**,
причина: `live_readiness_blocked`, **без списания** за автопубликацию.

## Как работает

`ProjectLiveReadinessProfile` (одна панель на проект) хранит статус, `readiness_score`, блокеры,
чек-лист, переключатели `project_live_enabled`/`full_auto_live_enabled`, кто/когда подтвердил.
`PlatformLiveReadiness` — то же по каждой площадке (`platform_live_enabled`, `required_fields`,
`missing_fields`, `credentials_present` — **признак**, не токен). Профили секретов не хранят.

`LiveReadinessService` — тонкий аудит поверх подсистем (autopilot, calendar, yandex sync, platform
connections, media proxy, billing, notifications):
- `run_project_readiness_check` — автопилот запущен? календарь активен? достаточно медиа? хватает
  баланса? площадки готовы? безопасность? → статус + score + блокеры + чек-лист;
- `run_platform_readiness_check` — по площадке (см. ниже);
- `build_project_live_dashboard` — клиентский дашборд;
- `enable_project_live` / `enable_platform_live` / `enable_full_auto_live` — включение с
  подтверждением и порогом (`LIVE_READINESS_MIN_SCORE_TO_ENABLE`, по умолчанию 85); **глобальные
  флаги не трогают**;
- `disable_*` — выключение;
- `build_effective_live_gate(project, platform)` — итоговый гейт (используется schedule automation).

### Готовность площадок

- **Telegram:** подключение + токен (маска) + канал (`channel_id`) + глобальный
  `TELEGRAM_LIVE_PUBLISHING_ENABLED` + `platform_live_enabled` + правила медиа.
- **VK:** подключение + токен + группа (`group_id`) + глобальный `VK_LIVE_PUBLISHING_ENABLED` +
  `platform_live_enabled` + предупреждение: **групповой токен не грузит фото** (нужен
  пользовательский).
- **Instagram:** токен/user id + **публичный HTTPS media proxy** (`media_proxy_https_ready`) +
  глобальный `INSTAGRAM_LIVE_PUBLISHING_ENABLED` + `platform_live_enabled`.
- **MAX/OK:** «скоро» (unsupported), пока не появится поддержка подключения.

## Защита schedule automation

В `ScheduleAutomationService._attempt_auto_publish` перед реальной отправкой добавлен гейт
`_filter_by_live_readiness`: глобальный флаг уже обеспечен `would_send` (реестр), а фильтр
**дополнительно** оставляет только площадки, где включён клиентский слой (project/platform/full_auto)
и `readiness_ready`. Если ничего не осталось → `live_readiness_blocked` (draft `needs_review`, без
списания). Любой сбой гейта → **fail-safe**: не публикуем. Ручной `publish_now` (ревью) —
engage-on-opt-in: блокируется, если клиент создал профиль готовности, но не включил project live.

## API (`/live-readiness`, под project-гардом)

`GET /projects/{id}` — дашборд · `POST /projects/{id}/check` — проверка проекта ·
`POST /projects/{id}/platforms/{platform}/check` — проверка площадки ·
`POST /projects/{id}/enable|disable` — project live (подтверждение `ENABLE_LIVE_AUTOPILOT`) ·
`POST /projects/{id}/platforms/{platform}/enable|disable` — platform live
(`ENABLE_PLATFORM_LIVE`) · `POST /projects/{id}/full-auto-live/enable|disable` ·
`GET /projects/{id}/effective/{platform}` — эффективный гейт. Ни один эндпоинт не меняет глобальные
флаги и не публикует.

## UI

`/ui/projects/{id}/live-readiness` — «Готовность к реальной автопубликации»: главный статус
(Готово / Нужно исправить / Заблокировано / Проверка не запускалась), чек-лист, блокеры, карточки
Автопилот/Календарь/Медиа/Баланс, карточки площадок (Telegram/VK/Instagram), безопасность и
подтверждения. Кнопки: «Проверить готовность», «Включить live для проекта», «Включить full-auto
live», «Выключить live», «Включить площадку». Явное предупреждение: «Это не включает глобальные
env-флаги. Реальная публикация сработает только если условия публикации включены администратором.»
Клиентский язык (без техжаргона), без кнопки прямой публикации. Страница автопилота показывает
карточку «Реальная публикация»; «Сегодня» подсказывает, если автопилот работает, но публикация не
включена.

## CLI

```bash
make live-readiness-check project_id=1 dry_run=true
make live-readiness-platform-check project_id=1 platform=telegram dry_run=true
make live-readiness-enable project_id=1 confirmation=ENABLE_LIVE_AUTOPILOT dry_run=true
make live-readiness-effective-gate project_id=1 platform=telegram
```

Все CLI — offline, dry-run по умолчанию, ничего не публикуют, глобальные флаги не меняют, секретов
не печатают.

## Всё бесплатно в MVP

`live_readiness_check`/`platform_check`/`enable` — 0 units. Заблокированная публикация — 0 units.
Реальная публикация later тарифицируется прежним потоком автопубликации.

## Модель / миграция

Таблицы `project_live_readiness_profiles`, `platform_live_readiness` — миграция
`0041_live_readiness` (down_revision `0040_calendar_plans`), индексы по account/project/platform/
status/live-переключателям. Секретов не хранят.

## Что дальше

- реальный **Telegram-first** live rollout по клиенту (первый прод-запуск);
- production media proxy домен (публичные HTTPS image_url для Instagram);
- VK user-token photo strategy (загрузка фото);
- завершение Instagram API;
- упрощённый публичный лендинг и тарифы.
