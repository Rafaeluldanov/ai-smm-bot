# 40. Botfleet: worker-предложения экспериментов (v0.4.3)

Слой поверх A/B-тестирования и оптимизации тем
([39](39_Botfleet_AB_Testing_Topic_Optimization.md)): фоновый worker периодически
анализирует проект и **предлагает** эксперименты/темы, а клиент видит «Рекомендации
worker-а» и решает — принять / отклонить / скрыть / создать A/B. Worker может (по явному
флагу) авто-создавать A/B из лучших предложений, но **никогда** не публикует live.

> **Безопасность:** это **не** этап live-публикаций и **не** реальных платежей. Варианты
> идут в очередь ревью (draft/needs_review), live-публикаций нет, внешних API-вызовов нет.
> Worker-генерация предложений и авто-создание экспериментов **выключены** по умолчанию
> (`EXPERIMENT_SUGGESTIONS_WORKER_ENABLED=false`, `EXPERIMENT_SUGGESTIONS_AUTO_CREATE=false`,
> `SCHEDULE_EXPERIMENTS_ENABLED=false`). Live-флаги публикации/платежей эти настройки **не**
> включают.

## Термины

- **ExperimentSuggestionStatus**: `proposed · accepted · rejected · dismissed · experiment_created · expired · failed`
- **ExperimentSuggestionType**: `publish_more · avoid · retest · explore · fill_gap · cta_test · media_test · timing_test · format_test · weak_topic_fix`
- **ExperimentSuggestionSource**: `manual · api · cli · worker`
- **ExperimentSuggestionAction**: `preview · generate · accept · reject · dismiss · create_experiment`

## Сервис (`experiment_suggestion_service`)

Опирается на `TopicOptimizationService.recommend_next_topics` (рекомендации с
`confidence_score 0..1`) и `ABTestingService.create_experiment_from_topic`.

- `preview_suggestions` — кандидаты (с флагом `meets_confidence`), **без записи и без
  списаний**;
- `generate_suggestions` — создаёт предложения `proposed` (запись, **бесплатно**); дедуп по
  **cooldown** (та же тема/площадка в окне) и по **idempotency_key**; фильтр по
  `min_confidence`; лимиты `max_per_tick` и `max_active_per_project`;
- `accept_suggestion` / `reject_suggestion` / `dismiss_suggestion` — решения клиента
  (**бесплатно**); accept/reject дают **лёгкий сигнал обучения** по теме
  (preferred/rejected topics, недеструктивно);
- `create_experiment_from_suggestion` — создаёт A/B из предложения (**платно**,
  идемпотентно), связывает `suggestion ↔ experiment` (в `experiment_metadata.suggestion_id`),
  помечает `experiment_created`; варианты — в очередь ревью, **live нет**;
- `run_worker_suggestions_for_project` — точка входа worker-а (gated флагом); dry-run →
  preview, иначе generate; при `auto_create` — создаёт A/B из лучших
  (`publish_more/explore/fill_gap/retest/weak_topic_fix`);
- `build_suggestion_dashboard` — сводка для UI.

## Интеграция в фоновый worker (`scheduler_worker_service`)

После обработки целей расписания worker вызывает `_process_experiment_suggestions` для
уникальных проектов из целей тика. Флаги: выключено по умолчанию; `suggestions_dry =
worker_dry_run OR EXPERIMENT_SUGGESTIONS_DRY_RUN`. Ошибка одного проекта **не роняет** тик.
`SchedulerWorkerTickResult` расширен полями `experiment_suggestions_enabled/dry_run/scanned/
created/skipped`, `experiments_created`, `experiment_suggestion_errors`. Worker **не
импортирует** `publish_due` и **не** делает live-публикаций (проверяется тестом).

## Дедупликация

- **Cooldown**: та же нормализованная тема/площадка в окне `cooldown_hours` — не дублируется
  (сравнение времени в Python, tz-safe: naive `created_at` → UTC).
- **Idempotency**: ключ окна worker-а `worker-<owner>-<project>-<hash(topic,platform)>`;
  повтор тика не создаёт дублей.
- Истёкшие предложения (`expires_at`) чистятся при следующей генерации.

## Биллинг

| Действие | units |
|----------|-------|
| preview / генерация предложений | 0 |
| accept / reject / dismiss | 0 |
| worker-tick (анализ/предложения) | 0 |
| создать A/B из предложения | 10 (как обычное создание A/B, +5 за вариант сверх 2) |

Недостаток баланса → `InsufficientBalanceError` (API 402); предложение **не** помечается
`experiment_created`. Повтор `create_experiment_from_suggestion` — `skipped_duplicate`, без
двойного списания.

## Приватность

Предложения и обучение строго **per-project/account**; данные одного клиента не смешиваются
с другими; глобального обучения нет. Секретов/токенов в ответах, UI и логах нет.

## Config / env

`EXPERIMENT_SUGGESTIONS_ENABLED=true` · `EXPERIMENT_SUGGESTIONS_WORKER_ENABLED=false` ·
`EXPERIMENT_SUGGESTIONS_AUTO_CREATE=false` · `EXPERIMENT_SUGGESTIONS_DRY_RUN=true` ·
`EXPERIMENT_SUGGESTIONS_MAX_PER_TICK=5` · `EXPERIMENT_SUGGESTIONS_MAX_ACTIVE_PER_PROJECT=20` ·
`EXPERIMENT_SUGGESTIONS_MIN_CONFIDENCE=0.55` · `EXPERIMENT_SUGGESTIONS_COOLDOWN_HOURS=24` ·
`EXPERIMENT_SUGGESTIONS_EXPIRE_DAYS=14` · `EXPERIMENT_SUGGESTIONS_REQUIRE_REVIEW=true`.

Эффективные флаги: `worker_enabled_effective = enabled AND worker_enabled`;
`auto_create_effective = worker_enabled_effective AND auto_create`. То есть авто-создание
недоступно, пока не включены и предложения, и worker.

## Аудит

`experiment_suggestion.previewed/generated/created/accepted/rejected/dismissed/
experiment_created/failed`; `scheduler.worker.experiment_suggestions.previewed/created/
skipped/failed`; `scheduler.worker.experiment_created`. Без секретов.

## Миграция и модель

`0025_experiment_suggestions` (down_revision `0024_content_experiments`,
SQLite/PostgreSQL): таблица `experiment_suggestions` (тема, тип, источник, статус,
`confidence_score`, safe payload/сигналы/риски, подсказки CTA/медиа/время, `estimated_units`,
`idempotency_key` unique, связи с проектом/аккаунтом/экспериментом/`schedule_run`, TS-поля).

## API (`/experiment-suggestions`, tenant-изоляция)

- `GET /projects/{id}` · `GET /projects/{id}/dashboard`;
- `POST /projects/{id}/preview` · `POST /projects/{id}/generate` ·
  `POST /projects/{id}/worker-preview` (только чтение);
- `GET /{id}` · `POST /{id}/accept` · `/reject` · `/dismiss` · `/create-experiment`.

Недостаток баланса → 402; ошибки предложений → 400; чужой проект/предложение → 404.

## CLI

```bash
make experiment-suggestions-preview project_id=1 platform=telegram
make experiment-suggestions-generate project_id=1 dry_run=false
make experiment-suggestion-accept suggestion_id=1
make experiment-suggestion-create suggestion_id=1 dry_run=false
```

Dry-run по умолчанию для generate/create; секреты не печатаются; live-публикаций нет.

## UI

- `/ui/projects/{id}/experiment-suggestions` — «Рекомендации worker-а»: карточки активных
  предложений с приёмом/отклонением/скрытием и «Создать A/B тест»; preview/генерация;
  предупреждение «Live-публикаций нет»;
- вход из `/ui/projects/{id}/optimization` и `/ui/projects/{id}/recommendations`;
- `/ui/scheduler` показывает сводку предложений тика и флаги;
- карточка проекта на дашборде ведёт на «A/B предложения».

## Продолжение: автовыбор темы (v0.4.4)

Следующий слой использует те же сигналы (обучение + метрики + A/B winners + **принятые
предложения**) не для отдельных рекомендаций, а для выбора темы/CTA/формата ближайшего слота
расписания — с записью «почему бот выбрал эту тему» и без live-публикации. См.
[41_Botfleet_Auto_Topic_Selection.md](41_Botfleet_Auto_Topic_Selection.md).
