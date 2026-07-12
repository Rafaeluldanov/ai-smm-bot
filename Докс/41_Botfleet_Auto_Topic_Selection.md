# 41. Botfleet: автовыбор темы в worker-е (v0.4.4)

Слой поверх worker-предложений ([40](40_Botfleet_Worker_Experiment_Suggestions.md)): для
ближайшего слота расписания worker не просто создаёт draft из CRM-категории, а сам
**выбирает лучшую тему / CTA / формат / медиа-стратегию / время** на основе learning profile,
метрик, feedback, A/B winners и experiment suggestions — и сохраняет «почему бот выбрал эту
тему» (:class:`ScheduleTopicDecision`). Пост создаётся только как draft/needs_review.

> **Безопасность:** это **не** этап live-публикаций и **не** реальных платежей. Решение
> влияет только на **draft/needs_review**; live-публикаций нет, внешних API-вызовов нет.
> Автовыбор worker-ом **выключен** по умолчанию (`AUTO_TOPIC_SELECTION_WORKER_ENABLED=false`),
> dry-run по умолчанию. Никакие live-флаги публикации/платежей это не включает.

## Термины

- **TopicDecisionStatus**: `preview · selected · draft_created · skipped · failed · blocked`
- **TopicDecisionSource**: `learning_profile · metrics · ab_winner · experiment_suggestion · crm_category · keyword_priority · media_availability · fallback`
- **TopicDecisionRisk**: `low_confidence · repeated_topic · weak_metrics · no_media · missing_credentials · insufficient_balance · live_disabled · quality_below_threshold · content_gap · stale_learning_profile`
- **TopicDecisionMode**: `semi_auto · full_auto · dry_run`

## Сигналы и кандидаты (`schedule_topic_decision_service`)

`build_candidates` собирает темы-кандидаты из четырёх источников (все per-project):
1. **Оптимизация тем** (`TopicOptimizationService.recommend_next_topics`) — publish_more /
   explore / fill_gap / retest (avoid отбрасывается — такое не публикуем);
2. **Принятые/активные предложения экспериментов** (`experiment_suggestion_repository`);
3. **A/B winners** — тема из эксперимента + победившие CTA/медиа/формат/время из варианта;
4. **CRM-категория** — гарантированный fallback (title/cta/media_tags).

## Скоринг (`score_candidate`, MVP)

| Компонент | Δ |
|-----------|---|
| принятое предложение | +20 |
| A/B winner | +25 |
| сильный тег профиля | +20 |
| одобряемая тема | +15 |
| приоритет ключевого слова | +0..15 |
| доступно медиа | +10 |
| тема давно не использовалась | +10 |
| недавно использованная тема | −15 |
| отклонённая тема | −30 |
| слабый тег | −20 |
| нет медиа (когда план требует) | −10 |

Уверенность метрик дисконтируется по источнику последнего снимка
(`api 1.0 · manual 0.8 · internal 0.6 · estimated 0.4 · demo 0.2`). Итоговая
`confidence_score ∈ [0..1]` = функция от `total_score` и base-уверенности источника.

`explain_decision` формирует человекочитаемые причины («Тема и CTA взяты из победившего
A/B-теста», «Совпадение с сильными тегами профиля», «Тема давно не публиковалась»…).

## Как выбирается тема / CTA / формат / медиа

- **тема** — кандидат с максимальным `total_score`;
- **CTA** — из кандидата, иначе из победившего A/B-варианта;
- **формат / медиа-стратегия / время** — аналогично (кандидат → A/B winner → CRM);
- **fatigue** — недавно использованные темы/теги (по последним постам и решениям) получают
  штраф, что предотвращает повторы.

## Интеграция в движок расписаний (`schedule_automation_service`)

Внутри `_process_entry` (после проверки баланса, перед `build_post_for_schedule`) worker
создаёт `ScheduleTopicDecision`, и `build_post_for_schedule` использует выбранные
тему/CTA/медиа. В `generation_notes` пишутся `schedule_topic_decision_id`, `selected_topic`,
`selected_cta`, `selected_format`, `selected_media_strategy`, `topic_decision_confidence`,
`topic_decision_reasons/source_signals/risk_flags`; в `ScheduleRun.run_metadata` —
краткая сводка решения. **Если уверенность ниже порога — пост всё равно needs_review** с риском
`low_confidence`. Ошибка автовыбора **не роняет прогон** — fallback к обычному CRM-драфту.

Запись решений в `run_due` активна только при
`AUTO_TOPIC_SELECTION_WORKER_ENABLED=true` **и** `AUTO_TOPIC_SELECTION_DRY_RUN=false`; иначе —
обычный CRM-драфт (обратная совместимость, старые тесты не меняются).

## Интеграция в фоновый worker (`scheduler_worker_service`)

`process_target` вызывает `run_due` / `run_due_dry`, поэтому решения создаются в общем потоке
создания драфтов; `SchedulerWorkerTickResult` расширен полями
`auto_topic_selection_enabled/dry_run`, `topic_decisions_previewed/created`,
`low_confidence_decisions`, `topic_decision_errors`. Worker **не импортирует** `publish_due`.

## Обучение

Приём/отклонение поста-драфта проходит обычную очередь ревью и обновляет профиль. Если пост
создан из решения, событие обратной связи несёт `schedule_topic_decision_id` (лёгкий хук в
`client_learning_service`), без тяжёлой связки и без cross-client mixing.

## Биллинг

Preview / создание решения / применение к драфту — **бесплатно**
(`topic_decision_preview/create/apply_to_draft = 0`). Реальная стоимость — только за создание
draft по расписанию (`USAGE_SCHEDULE_GENERATION`, как и раньше). Неуспешное решение — без
списаний; дублей нет (idempotency).

## Приватность

Все решения и обучение строго **per-project/account**; данные одного клиента не смешиваются
с другими. Секретов/токенов в `alternatives/source_signals/decision_metadata`, в UI/API и в
логах нет.

## Config / env

`AUTO_TOPIC_SELECTION_ENABLED=true` · `AUTO_TOPIC_SELECTION_WORKER_ENABLED=false` ·
`AUTO_TOPIC_SELECTION_DRY_RUN=true` · `AUTO_TOPIC_SELECTION_MIN_CONFIDENCE=0.55` ·
`AUTO_TOPIC_SELECTION_MAX_ALTERNATIVES=5` · `AUTO_TOPIC_SELECTION_RECENCY_DAYS=60` ·
`AUTO_TOPIC_SELECTION_FATIGUE_WINDOW_DAYS=14` ·
`AUTO_TOPIC_SELECTION_REQUIRE_MEDIA_FOR_MEDIA_PLANS=false` ·
`AUTO_TOPIC_SELECTION_USE_AB_WINNERS=true` ·
`AUTO_TOPIC_SELECTION_USE_EXPERIMENT_SUGGESTIONS=true` ·
`AUTO_TOPIC_SELECTION_USE_METRICS=true` · `AUTO_TOPIC_SELECTION_USE_CLIENT_FEEDBACK=true` ·
`AUTO_TOPIC_SELECTION_FALLBACK_TO_CRM_CATEGORY=true`.

Эффективные флаги: `worker_enabled_effective = enabled AND worker_enabled`. Запись решений в
расписании требует ещё и `NOT dry_run`.

## Аудит

`topic_decision.previewed/created/applied_to_draft/failed/low_confidence/fallback_used`;
`scheduler.worker.topic_decision.previewed/created/skipped/failed`. Без секретов.

## Миграция и модель

`0026_schedule_topic_decisions` (down_revision `0025_experiment_suggestions`,
SQLite/PostgreSQL): таблица `schedule_topic_decisions` (выбранные тема/CTA/формат/медиа/время,
источник/режим/статус, `confidence_score`, ожидаемые метрики, `learning_profile_version`,
`alternatives/source_signals/risk_flags/reasons/decision_metadata`, `idempotency_key` unique,
связи с проектом/аккаунтом/планом/`schedule_run`/`experiment_suggestion`/`content_experiment`).

## API (`/topic-decisions`, tenant-изоляция)

- `GET /projects/{id}` (фильтры платформа/статус/источник) · `GET /projects/{id}/dashboard`;
- `POST /projects/{id}/preview` (без записи) · `POST /projects/{id}/create` (идемпотентно);
- `GET /{id}` · `POST /{id}/apply-dry` (как решение повлияло бы на draft-payload).

Чужой проект/решение → 404; ошибки решения → 400.

## CLI

```bash
make topic-decision-preview project_id=1 platform=telegram plan_id=1
make topic-decision-create project_id=1 platform=telegram dry_run=false
make topic-decision-dashboard project_id=1
```

Dry-run по умолчанию для create; секреты не печатаются; пост не создаётся; live нет.

## UI

- `/ui/projects/{id}/topic-decisions` — «Выбор тем по обучению»: preview/создание + карточки
  решений (тема/CTA/формат/уверенность/источник/риски/причины);
- `/ui/projects/{id}/topic-decisions/{id}` — детали: альтернативы, разбор оценки, причины,
  риски, сигналы, связанный прогон/пост, «влияние на draft»;
- `/ui/projects/{id}/automation` — блок «Автовыбор тем» + флаги;
- `/ui/scheduler` — блок «Автовыбор тем в worker» + счётчики последнего тика;
- карточка проекта — «Следующая тема · почему бот её выберет».

## Что дальше

Авто-выбор медиа-стратегии · multi-armed bandit / Bayesian оптимизация · сезонное
планирование · content-gap crawler · платформенно-специфичное взвешивание метрик ·
production live-auto аудит.
