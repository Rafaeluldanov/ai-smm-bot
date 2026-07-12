# 37. Botfleet: Ревью, обучение и режимы автоматизации (v0.4.0)

Полу- и полностью автоматический режим ведения соцсетей: очередь ревью с кнопкой
«Опубликовать», безопасный full-auto по календарю и персональный движок обучения бота
на конкретном клиенте. Слой строится поверх движка расписаний (см.
[35](35_Botfleet_Schedule_Automation_Engine.md)) и фонового worker-а
(см. [36](36_Botfleet_Background_Scheduler_Worker.md)).

> **Безопасность (главное):** живые публикации по умолчанию **выключены**. Ни один режим
> не включает `*_LIVE_PUBLISHING_ENABLED`/`PAYMENTS_LIVE_ENABLED`. Реальная отправка
> возможна только когда **все safety gates** истинны; иначе бот создаёт draft/needs_review
> и пишет понятную причину. В тестах живых вызовов нет — используется `FakePublishingClient`.

## Режимы автоматизации

Клиент выбирает режим на уровне плана публикаций (`CrmPublishingPlan`):

- **`semi_auto`** (по умолчанию) — worker создаёт по календарю `draft/needs_review`,
  оценивает контент и добавляет снимок обучения; **живой публикации нет**. Клиент видит
  очередь, редактирует, одобряет/отклоняет/запрашивает правки и жмёт «Опубликовать».
- **`full_auto`** — worker может сам одобрить и опубликовать пост, **но только** если
  пройдены все safety gates (ниже). Иначе создаётся `needs_review` с причиной блокировки.

Переключение на `full_auto` требует явного подтверждения фразой **`ENABLE_FULL_AUTO`**.
`full_auto` **не** подразумевает live: глобальные live-флаги остаются выключены.

### Статусы поста (`PostApprovalStatus`)

`draft` · `needs_review` · `changes_requested` · `approved` · `scheduled` · `published` ·
`rejected` · `failed` (плюс `needs_media`). Переходы валидируются `post_status_service`.

## Safety gates полностью автоматического режима

`full_auto` публикует live **только** если одновременно:

1. `schedule.automation_mode == full_auto` и `auto_publish_enabled == true`;
2. `quality_score >= min_quality_score_for_auto` (порог качества плана);
3. есть хотя бы одно одобрение клиента, если `require_review_before_first_auto` (иначе
   `needs_first_review`);
4. достаточно баланса units под платную авто-публикацию;
5. подключение платформы есть, включён её live-флаг, есть таргет (иначе `live_disabled`);
6. идемпотентность слота (повтор не создаёт дубль и не публикует дважды).

Причины блокировки (пишутся в `ScheduleRun.auto_publish_blocked_reason` и событие
`auto_blocked`): `quality_score_below_threshold`, `needs_first_review`,
`insufficient_balance`, `live_disabled`, `publish_failed`.

## Очередь ревью и кнопка «Опубликовать»

REST API (`/review`, tenant-изоляция `require_project_access`/`require_post_access`):

| Метод | Маршрут | Действие |
|-------|---------|----------|
| GET  | `/review/projects/{id}/queue` | Очередь постов + скоринг + причины обучения |
| GET  | `/review/posts/{id}` | Детали: тексты, публикации, скоринг, история фидбэка, publish-gate |
| POST | `/review/posts/{id}/edit` | Правка текста/медиа (событие `edited`, пересчёт скоринга) |
| POST | `/review/posts/{id}/approve` | → `approved` (+ событие `approved`) |
| POST | `/review/posts/{id}/reject` | → `rejected` (reason_tags) |
| POST | `/review/posts/{id}/request-changes` | → `changes_requested` |
| POST | `/review/posts/{id}/rate` | Ручная оценка 1..5 |
| POST | `/review/posts/{id}/approve-and-schedule` | Одобрить + запланировать (без live) |
| POST | `/review/posts/{id}/publish-now` | Кнопка «Опубликовать» (semi-auto), под safety gates |

**`publish-now`** проверяет те же live-гейты, что и авто-режим. Если live недоступен —
возвращает `{blocked: true, reason: "live_disabled", units_charged: 0}` и **ничего не
списывает**. При успехе (в контролируемом тесте с fake-клиентом) — списывает units один раз,
пишет событие `published` и аудит `review.post.published`.

## Настройки автоматизации

REST API `/automation` (tenant-изоляция):

- `GET/POST /automation/projects/{id}/settings` — режим для всех планов проекта;
- `GET/POST /automation/projects/{id}/platforms/{platform}/settings` — по площадке;
- `POST /automation/projects/{id}/plans/{plan_id}/mode` — для одного плана.

Payload: `{automation_mode, auto_publish_enabled, learning_enabled,
require_review_before_first_auto, min_quality_score_for_auto, max_posts_per_day_auto,
confirm}`. Включение `full_auto`/`auto_publish_enabled` требует `confirm: "ENABLE_FULL_AUTO"`.

## Обучение бота на клиенте

### Сигналы (`PostFeedbackEvent`)

Каждое решение и импорт метрик фиксируются как событие: `approved`, `rejected`,
`changes_requested`, `edited`, `published`, `manual_rating`, `analytics_imported`,
`auto_published`, `auto_blocked`. Полный текст **не хранится** — только `before/after_text_hash`
и агрегированный `diff_summary` (что клиент поменял: сократил, добавил CTA, убрал хэштеги,
добавил цифры, сменил тон). `event_metadata` санитизируется — секретов нет.

### Профиль (`ClientLearningProfile`)

Строго **per-project** (опционально per-platform). Хранит: `brand_voice`,
`preferred_topics`/`rejected_topics`, `preferred_cta`/`rejected_cta`,
`preferred_text_length`, `preferred_media_types`, `high_performing_tags`/`low_performing_tags`,
`best_publish_times`, `approval_patterns`, `editing_patterns`, `performance_patterns`,
`forbidden_patterns`, `recommendations`, `confidence_score`, `profile_version`.

### Алгоритм (MVP, безопасный per-client слой)

- `approved` → теги/CTA/тема поста получают `+1`; `rejected`/`auto_blocked` → `-1`.
- `edited` → анализ diff (сокращение, +CTA, −хэштеги, +цифры, смена тона) → `editing_patterns`.
- аналитика: теги постов с высоким ER → `high_performing_tags`, с низким → `low_performing_tags`.
- `confidence_score` растёт с числом событий; профиль пересчитывается после каждого сигнала.

Это **не** дообучение модели и **не** глобальное обучение на данных клиента без согласия —
только персональный слой эвристик, который влияет на будущие генерации через
`score_content_candidate` и `suggest_next_topics`.

### Как аналитика влияет на будущие посты

Импортированные метрики (`analytics_imported`) усиливают/ослабляют веса тегов в профиле;
`content_scoring_service` при генерации по расписанию считает `quality_score` /
`predicted_engagement_score` / `fit_score` относительно профиля и добавляет причины и
предупреждения в `generation_notes` и `ScheduleRun`. Посты, не проходящие порог качества,
не уходят в авто-публикацию.

## Оценка контента (`content_scoring_service`)

Чистый сервис (без БД/сети/AI): `analyze_text_features` (длина, CTA, ссылка, хэштеги,
цифры, вопрос, тон), `score_post_against_profile` (quality/engagement/fit 0..100 + reasons +
warnings), `recommend_post_improvements`. Используется в движке расписаний, review UI и
движке обучения.

## Биллинг

| Действие | Стоимость |
|----------|-----------|
| Сбор фидбэка (approve/reject/edit/rating) | бесплатно |
| Превью-скоринг контента | бесплатно |
| Публикация «Опубликовать» / авто-публикация | как обычная публикация (units) |
| Глубокий пересчёт профиля (`/learning/.../rebuild`) | 5 units |

Заблокированная публикация **не списывает** units. Успешная публикация списывает ровно один
раз (идемпотентно). Авто-режим не обходит биллинг.

## UI

- `/ui/review` и `/ui/projects/{id}/review` — очередь: карточки со скорингом, кнопки
  **Открыть / Одобрить / Запросить правки / Отклонить / Опубликовать**; кнопка «Опубликовать»
  показывает причину, если live недоступен.
- `/ui/learning` и `/ui/projects/{id}/learning` — блок **«Чему бот научился»**: темы, CTA,
  сильные/слабые теги, длина текста, время, уверенность, рекомендации, последние решения.
- `/ui/projects/{id}/automation` — карточки режимов `semi_auto`/`full_auto`, чек-лист safety
  gates, подтверждение `ENABLE_FULL_AUTO`.
- В sidebar добавлены **Ревью** и **Обучение** (Автоматизация — существующий пункт).

## Аудит

`review.post.opened/edited/approved/rejected/changes_requested/publish_clicked/publish_blocked/
published`, `learning.feedback.recorded`, `learning.profile.updated/rebuilt`,
`automation.mode.changed`, `automation.full_auto.enabled/disabled`,
`automation.auto_publish.blocked/succeeded`. Секретов в аудите нет.

## Миграция и модель данных

Миграция `0022_automation_modes_learning` (down_revision `0021_scheduler_worker_leases`,
совместима со SQLite и PostgreSQL):

- новые таблицы `client_learning_profiles`, `post_feedback_events`;
- поля автоматизации в `crm_publishing_plans` (`automation_mode`, `auto_publish_enabled`,
  `learning_enabled`, `require_review_before_first_auto`, `min_quality_score_for_auto`,
  `max_posts_per_day_auto`, `safety_notes`);
- поля прогона в `schedule_runs` (`automation_mode`, `auto_publish_attempted`,
  `auto_publish_blocked_reason`, `learning_profile_version`, `quality_score`, `safety_score`).

## Приватность

Профиль строго per-project; данные одного клиента **не смешиваются** с другими и **не**
используются для глобального обучения модели без явного согласия. Хранятся агрегаты и хеши,
не сырой текст.

## Как открыть

```bash
make run
# http://127.0.0.1:8000/ui/review
# http://127.0.0.1:8000/ui/projects/1/review
# http://127.0.0.1:8000/ui/projects/1/learning
# http://127.0.0.1:8000/ui/projects/1/automation
```

## Что дальше

- импорт реальных метрик площадок (пока `analytics_imported` — ручной/fake);
- тонкая настройка промптов генерации под профиль клиента;
- A/B-тестирование заголовков/CTA;
- multi-armed bandit для выбора тем;
- обучение рекомендаций по медиа;
- включение реального live-авто-режима только после production-аудита.

## Продолжение: импорт метрик (v0.4.1)

Следующий слой обучения — импорт метрик опубликованных постов (demo/manual/estimated/api),
нормализация метрик площадок и пересчёт профиля по реальным/ручным данным: какие темы, теги,
CTA, медиа и время работают лучше. См.
[38_Botfleet_Metrics_Import_Learning_Feedback.md](38_Botfleet_Metrics_Import_Learning_Feedback.md).


## Продолжение: A/B-тесты (v0.4.2)

Варианты A/B создаются как draft/needs_review посты и проходят обычную очередь ревью;
winner (ручной или авто по метрикам) обновляет профиль обучения. См.
[39_Botfleet_AB_Testing_Topic_Optimization.md](39_Botfleet_AB_Testing_Topic_Optimization.md).

## Продолжение: worker-предложения (v0.4.3)

Приём/отклонение предложений worker-а даёт лёгкий сигнал обучения по теме (preferred/rejected
topics), не публикуя live. См.
[40_Botfleet_Worker_Experiment_Suggestions.md](40_Botfleet_Worker_Experiment_Suggestions.md).
