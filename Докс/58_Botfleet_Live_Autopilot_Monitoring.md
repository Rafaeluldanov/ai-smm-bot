# 58. Botfleet: Мониторинг live-автопилота и стоп-кран (v0.6.1)

Продолжение live-слоя ([56](56_Botfleet_Live_Autopost_Readiness.md), [57](57_Botfleet_Telegram_Live_Rollout.md)):
клиентский слой **«как себя чувствует автопилот»** и **стоп-кран**. Клиент видит здоровье
публикаций за период, инциденты (повторные сбои, низкий баланс) и может мгновенно поставить
автопилот на паузу. Наблюдение фиксируется в снимках ``LiveAutopilotMonitorSnapshot``; проблемы —
в ``LiveAutopilotIncident``.

> **Это НЕ включатель live и НЕ обход safety-gates.** Мониторинг только наблюдает и умеет ставить
> автопилот на **паузу**. Стоп-кран НЕ трогает глобальные ``*_LIVE_PUBLISHING_ENABLED``
> (админ-флаги): пауза переключает состояние, которое движок уже учитывает (per-project/per-platform
> live + пауза профиля автопилота). Возобновление **НЕ** перевзводит реальную публикацию — её нужно
> включить отдельно через готовность. По умолчанию: ``LIVE_AUTOPILOT_MONITORING_DRY_RUN=true``,
> ``LIVE_AUTOPILOT_MONITORING_WORKER_ENABLED=false``, ``LIVE_AUTOPILOT_AUTO_PAUSE_ENABLED=false``,
> подтверждение стоп-крана обязательно. В тестах реальной сети/публикаций нет; секретов/токенов/сырых
> payload не хранит и не печатает.

## Зачем это нужно

Когда автопилот публикует вживую, клиенту нужен понятный ответ на вопрос «всё ли в порядке» и
быстрый способ остановиться, если что-то идёт не так. Технические журналы попыток
(``LivePublishAttempt``, [57](57_Botfleet_Telegram_Live_Rollout.md)) для этого слишком подробны —
мониторинг сводит их в здоровье (`healthy/warning/degraded/paused`), заводит инциденты по порогам и
даёт одну кнопку «пауза».

## Здоровье за окно наблюдения

Сервис ``LiveAutopilotMonitoringService.run_health_check`` берёт live-попытки проекта за окно
``LIVE_AUTOPILOT_MONITORING_WINDOW_HOURS`` (по умолчанию 24 ч) и считает:

- ``total/published/blocked/failed/skipped`` — счётчики попыток;
- ``success_rate/failure_rate`` — доли по «реальным» попыткам (``published + failed``);
- ``health_status``:
  - ``paused`` — автопилот на паузе;
  - ``degraded`` — есть критические инциденты **или** доля сбоев ≥
    ``LIVE_AUTOPILOT_MONITORING_FAILURE_CRITICAL_RATE`` (0.50);
  - ``warning`` — доля сбоев ≥ ``LIVE_AUTOPILOT_MONITORING_FAILURE_WARNING_RATE`` (0.25);
  - ``unknown`` — реальных попыток за период не было;
  - ``healthy`` — иначе.

При ``dry_run`` (по умолчанию) метод **ничего не пишет**: только считает. При ``dry_run=false`` (и
включённом мониторинге) сохраняет ``LiveAutopilotMonitorSnapshot``, при необходимости заводит
инциденты и — если явно разрешено — авто-паузу.

## Инциденты

``LiveAutopilotIncident`` — журнал проблем, требующих внимания. Дедупликация по типу/площадке в окне
``LIVE_AUTOPILOT_INCIDENT_DEDUP_HOURS`` (повторная проблема инкрементирует ``occurrences``, не плодит
дубли; серьёзность только повышается). Типы: ``repeated_publish_failures`` (сбоев ≥
``LIVE_AUTOPILOT_AUTO_PAUSE_FAILURES_THRESHOLD``), ``balance_low`` (баланса на ≤ 2 поста) и др.
Жизненный цикл: ``open → acknowledged → resolved`` / ``ignored`` / ``auto_paused``.

## Стоп-кран (kill switch)

**Ключевой инвариант (проверен тестами):** пауза реально останавливает публикацию, потому что
переключает состояние, которое движок ``ScheduleAutomationService`` уже учитывает, а не только
отображаемый статус.

- ``pause_project_autopilot`` — пауза профиля автопилота (``is_enabled=False``, ``status=paused``)
  **и** выключение per-project/full-auto live через ``LiveReadinessService`` (движок сразу перестаёт
  публиковать вживую → черновики уходят в ``needs_review``). Требует подтверждения
  ``PAUSE_AUTOPILOT``.
- ``resume_project_autopilot`` — снимает паузу профиля (черновики снова создаются). Реальную
  публикацию **не** включает: ``project_live`` остаётся выключенным, пока клиент осознанно не включит
  его через готовность ([56](56_Botfleet_Live_Autopost_Readiness.md)) с подтверждением и порогом.
  Асимметрия намеренная: остановиться легко, а перевзвод live всегда идёт через готовность. Требует
  подтверждения ``RESUME_AUTOPILOT``.
- ``pause_platform_live`` / ``resume_platform_live`` — то же для одной площадки. Возобновление
  делегирует ``LiveReadinessService.enable_platform_live`` (подтверждение + проверка готовности) —
  обхода safety-gates нет.

Почему пауза выключает именно live-переключатели готовности: движок проверяет их в
``_filter_by_live_readiness`` (v0.5.9). ``ProjectAutopilotProfile.status="paused"`` сам по себе на
публикацию не влияет, поэтому пауза дополнительно выключает per-project live.

## Авто-пауза

По умолчанию **выключена** (``LIVE_AUTOPILOT_AUTO_PAUSE_ENABLED=false``): система только показывает,
что авто-пауза **сработала бы** (``preview_auto_pause``), но действий не предпринимает. Если включить,
при сбоях ≥ порога (и, при ``LIVE_AUTOPILOT_AUTO_PAUSE_CRITICAL_ONLY=true``, при критической доле
сбоев) автопилот останавливается автоматически (системная пауза без подтверждения), а связанный
инцидент помечается ``auto_paused``.

## Worker

Подшаг ``SchedulerWorkerService._process_live_monitoring`` (v0.6.1) гейтится
``LIVE_AUTOPILOT_MONITORING_WORKER_ENABLED`` (выключен по умолчанию → no-op). Для каждого проекта
запускает ``run_health_check`` (снимок + инциденты, с учётом dry-run), обновляет ``TickResult`` и
пишет аудит ``scheduler.worker.live_monitoring.previewed/snapshot_created/incident_created/failed``.
Один проект не роняет тик.

## API

Префикс ``/live-autopilot-monitoring`` (всё под project-гардом; инциденты — под incident-гардом
``require_live_incident_access`` через их проект):

- ``GET /projects/{id}`` — дашборд (здоровье, инциденты, стоп-кран);
- ``GET /projects/{id}/snapshots`` — история снимков;
- ``POST /projects/{id}/health-check`` — проверка здоровья (``dry_run`` в теле);
- ``GET /projects/{id}/incidents`` — инциденты (фильтр ``?status_filter=open``);
- ``GET /incidents/{id}``, ``POST /incidents/{id}/{acknowledge,resolve,ignore}``;
- ``POST /projects/{id}/{pause,resume}`` — стоп-кран проекта (подтверждение в теле);
- ``POST /projects/{id}/platforms/{platform}/{pause,resume}`` — стоп-кран площадки;
- ``GET /projects/{id}/auto-pause/preview`` — превью авто-паузы.

UI: ``/ui/projects/{id}/live-autopilot-monitoring`` («Мониторинг автопилота»).

## Настройки (безопасные дефолты)

```
LIVE_AUTOPILOT_MONITORING_ENABLED=true
LIVE_AUTOPILOT_MONITORING_DRY_RUN=true
LIVE_AUTOPILOT_MONITORING_WORKER_ENABLED=false
LIVE_AUTOPILOT_MONITORING_WINDOW_HOURS=24
LIVE_AUTOPILOT_MONITORING_FAILURE_WARNING_RATE=0.25
LIVE_AUTOPILOT_MONITORING_FAILURE_CRITICAL_RATE=0.50
LIVE_AUTOPILOT_INCIDENTS_ENABLED=true
LIVE_AUTOPILOT_INCIDENT_DEDUP_HOURS=24
LIVE_AUTOPILOT_AUTO_PAUSE_ENABLED=false
LIVE_AUTOPILOT_AUTO_PAUSE_FAILURES_THRESHOLD=3
LIVE_AUTOPILOT_AUTO_PAUSE_CRITICAL_ONLY=true
LIVE_AUTOPILOT_KILL_SWITCH_ENABLED=true
LIVE_AUTOPILOT_KILL_SWITCH_REQUIRE_CONFIRMATION=true
LIVE_AUTOPILOT_PAUSE_CONFIRMATION_TEXT=PAUSE_AUTOPILOT
LIVE_AUTOPILOT_RESUME_CONFIRMATION_TEXT=RESUME_AUTOPILOT
```

Действия мониторинга бесплатны (``USAGE_LIVE_MONITORING_* = 0`` units).

## CLI

```
make live-autopilot-monitoring-dashboard project_id=1
make live-autopilot-monitoring-health-check project_id=1 dry_run=true
make live-autopilot-monitoring-incidents project_id=1 status=open
make live-autopilot-monitoring-pause project_id=1 action=pause confirmation=PAUSE_AUTOPILOT
```

## Данные

Модели ``LiveAutopilotMonitorSnapshot`` + ``LiveAutopilotIncident``, миграция
``0043_live_autopilot_monitoring`` (down_revision ``0042_live_publish_attempts``). Секретов/сырых
токенов/payload не хранит; совместимо со SQLite и PostgreSQL.
