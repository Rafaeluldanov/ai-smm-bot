# 35. Botfleet: движок автоматизации расписаний (v0.3.8)

Клиент создал расписание → Botfleet умеет **безопасно** обработать due-задачи: создать
draft/needs_review посты и публикации (pending/scheduled), списать units и записать логи.

> **Живой публикации НЕТ.** Внешние API не вызываются. Всё уходит на ревью; `publish-due`
> старого типа не используется.

## 1. Schedule task (задача расписания)

Задача — это план публикаций `CrmPublishingPlan` (создаётся в UI/онбординге): дни недели
(`weekdays`, Пн=0), время (`publish_times`), платформы, режим (`mode`), период
(`start_date`/`end_date`), таймзона. Метод `list_schedule_tasks` отдаёт карточки задач:
`next_run_at`, `estimated_units_per_post`, `connection_status`, `can_run`, `warnings`.

## 2. Schedule run (прогон)

`ScheduleRun` (миграция **0020**) — факт обработки одного **due-слота**
(`plan × platform × date × time`): что бот сделал. Статусы:

- `planned` — создан, обработка началась;
- `draft_created` — создан draft + публикация, списаны units;
- `skipped` — дубликат (уже обработан ранее);
- `missing_credentials` — платформа не подключена (пост не создан);
- `insufficient_balance` — не хватило units (пост не создан, списания нет);
- `failed` — ошибка построения (пост не создан);
- `live_disabled` — резерв (live всегда выключен).

`idempotency_key = sched-{project}-{plan}-{platform}-{date}-{time}` (unique) — защита от
дублей. `run_metadata` секретов не содержит.

## 3. Как обрабатываются due-задачи

`preview_due_runs` / `run_due_dry` — БЕЗ записи (показывают, что было бы). `run_due` —
реальное создание draft. Для каждого due-слота:

1. проверка владения (`project.account_id == account_id`);
2. идемпотентность (уже `draft_created` → skip, без дубля/списания);
3. креды подключения (`resolve_publish_credentials`); `missing` → `missing_credentials`;
4. баланс (`ensure_balance`); не хватает → `insufficient_balance`;
5. `build_post_for_schedule` → draft/needs_review пост (текст из категории/CTA/тега,
   медиа — одобренный ассет проекта по тегам, иначе text-only + warning);
6. `PostPublication` в `scheduled` (target_id = external_id подключения; токен не
   раскрывается); **не published**;
7. списание units один раз (`debit_for_action`, идемпотентно);
8. `ScheduleRun` → `draft_created`, аудит.

## 4. Почему live не выполняется

Живая публикация выключена архитектурно: движок только создаёт черновики на ревью. Режим
`auto_publish` не публикует — создаётся draft с предупреждением. Реальный воркер/публикация
после одобрения — следующий этап.

## 5. Billing

Платное действие `schedule_due_draft_generation` (units из `UnitEconomicsService`,
генерация draft). Правила: dry-run = 0; неуспех = 0; успех = списание один раз; повтор
(idempotency) = без двойного списания; недостаток баланса = нет поста и списания
(`insufficient_balance`); создаётся usage-событие и аудит.

## 6. Логи

Аудит-действия: `schedule.run.preview/started/draft_created/skipped/failed/
insufficient_balance/missing_credentials` (метаданные: project_id, platform_key, plan_id,
run_id, post_id, publication_id, units, status — **без секретов**). История прогонов —
`ScheduleRun` (UI `/ui/projects/{id}/schedule-runs`).

## 7. Platform connections

Креды берутся из подключения проекта (`platform_connection_service`): `project_connection`
→ `env_fallback` (только local) → `missing`. Токен наружу не выходит. Чужой проект не
используется (поиск строго по `project_id`).

- **missing credentials** → откройте платформу и заполните API/ID (вкладка «Настройки»);
- **insufficient balance** → пополните баланс (units).

## 8. API

- `GET /schedule/projects/{id}/tasks` — карточки задач;
- `GET /schedule/projects/{id}/runs` — история (фильтр платформа/статус);
- `POST /schedule/projects/{id}/preview-due` — что было бы (без записи);
- `POST /schedule/projects/{id}/run-due-dry` — dry-run;
- `POST /schedule/projects/{id}/run-due` — создать draft (идемпотентно, без live);
- `GET /schedule/runs/{run_id}`, `POST /schedule/runs/{run_id}/retry-dry`.

Все под `require_project_access`; `account_id` в теле должен совпадать с
`project.account_id`. Секретов в ответах нет.

## 9. UI

Вкладка «Расписание» платформы: блок «Автоматизация расписаний» (карточки задач,
кнопки **Preview due** / **Создать drafts сейчас** / **История запусков**, предупреждения
о подключении/балансе, «Живая публикация выключена»). Страница
`/ui/projects/{id}/schedule-runs` — история прогонов с фильтрами.

## 10. CLI

```
make schedule-due-preview account_id=1 project_id=1 platform=telegram date=today
make schedule-due-run     account_id=1 project_id=1 platform=telegram date=today dry_run=true
```
`schedule_due_run` по умолчанию dry-run (без записи). Секреты не печатаются.

## 11. Что осталось дальше

- реальный background worker (cron/Celery/RQ) для планового запуска;
- workflow одобрения (approval) → перевод draft в approved;
- живая публикация после одобрения (per-platform live QA);
- реальные метрики платформенных API.

## Развитие: режимы автоматизации и обучение (v0.4.0)

Движок расширен режимами `semi_auto`/`full_auto`: `_process_entry` теперь оценивает контент
(`content_scoring_service`), пишет `quality_score`/`safety_score`/`learning_profile_version` в
`ScheduleRun` и, для `full_auto` с `auto_publish_enabled`, пытается опубликовать под safety
gates (иначе `auto_publish_blocked_reason`). Живая публикация возможна только при всех гейтах;
в тестах — через `FakePublishingClient`. Workflow одобрения и очередь ревью реализованы в
[37_Botfleet_Review_Learning_Automation.md](37_Botfleet_Review_Learning_Automation.md).

## Продолжение: предложения экспериментов (v0.4.3)

`SCHEDULE_EXPERIMENTS_ENABLED` остаётся выключенным; worker лишь **предлагает** эксперименты/
темы (без live). См.
[40_Botfleet_Worker_Experiment_Suggestions.md](40_Botfleet_Worker_Experiment_Suggestions.md).

## Продолжение: автовыбор темы (v0.4.4)

`_process_entry` перед `build_post_for_schedule` (за флагом `AUTO_TOPIC_SELECTION_WORKER_ENABLED`,
выключено по умолчанию) выбирает тему/CTA/формат/медиа по обучению и пишет
`ScheduleTopicDecision` + метаданные решения в `generation_notes`/`run_metadata`. Пост —
только draft/needs_review. См.
[41_Botfleet_Auto_Topic_Selection.md](41_Botfleet_Auto_Topic_Selection.md).

Следом (v0.4.5, за флагом `AUTO_MEDIA_SELECTION_WORKER_ENABLED`, выключено по умолчанию)
`_process_entry` создаёт `ScheduleMediaDecision`: выбирает media strategy и конкретные медиа,
накладывает `media_asset_ids`/`media_strategy` на черновик и пишет `schedule_media_decision_id`
+ метаданные в `generation_notes`/`run_metadata`. Live-публикаций нет; публичные ссылки не
создаются. См. [42_Botfleet_Auto_Media_Selection.md](42_Botfleet_Auto_Media_Selection.md).

Начиная с v0.4.6 подбор медиа учитывает **оценку качества** (quality/relevance/freshness/
uniqueness/platform_fit): сильные ассеты поднимаются в ранге, слабые/повторы дают risk
`weak_media_quality`/`repeated_media`, а в `generation_notes` пишется `media_quality_summary`.
Правило-ориентированно, без внешнего AI. См.
[43_Botfleet_Media_Quality_Scoring.md](43_Botfleet_Media_Quality_Scoring.md).
