# 39. Botfleet: A/B-тестирование и оптимизация тем (v0.4.2)

Следующий слой обучения поверх метрик ([38](38_Botfleet_Metrics_Import_Learning_Feedback.md)):
A/B-тестирование вариантов постов, оптимизация тем/CTA/форматов/времени и
рекомендательная система «что публиковать дальше». Botfleet создаёт несколько вариантов
поста перед ревью, сравнивает их по feedback + метрикам, выбирает winner и обновляет
профиль обучения.

> **Безопасность:** это **не** этап live-публикаций и **не** реальных платежей. Варианты
> идут в очередь ревью (draft/needs_review), live-публикаций нет, внешних API-вызовов нет.
> Авто-применение winner к будущим расписаниям и авто-создание экспериментов worker-ом
> **выключены** по умолчанию (флаги `AB_TESTING_AUTO_WINNER_ENABLED`,
> `SCHEDULE_EXPERIMENTS_ENABLED`).

## Термины

- **ExperimentStatus**: `draft · active · waiting_metrics · completed · canceled · failed`
- **ExperimentType**: `ab_test · topic_test · cta_test · media_test · timing_test · format_test`
- **VariantStatus**: `draft · needs_review · approved · rejected · published · measured · winner · loser`
- **OptimizationSignalSource**: `client_feedback · manual_metrics · api_metrics · estimated_metrics · demo_metrics · internal_history`
- **WinnerReason**: `higher_er · higher_ctr · client_approved · fewer_edits · better_quality_score · better_conversion_signal · manual_selection`

## Оптимизация тем (`topic_optimization_service`)

`build_project_signal_summary` собирает сигналы проекта (feedback, аналитика, метрики,
learning profile, недавние посты): top/weak topics, high/low tags, best/weak CTA, media,
время, паттерны и **content gaps** (категории CRM без недавних постов).

`recommend_next_topics` даёт рекомендации по категориям:
- **publish_more** — одобряемые темы (с пометкой `fatigue`, если тема часто повторялась);
- **explore** — сильные, но недоиспользуемые теги;
- **fill_gap** — направления плана без недавних постов;
- **retest** — слабые теги/темы, которые стоит переупаковать (A/B);
- **avoid** — отклонённые темы.

Каждая рекомендация: `topic, reason, confidence_score (0..1), source_signals, suggested_cta,
suggested_media_type, suggested_time, estimated_units, risk_flags`.

`score_topic_candidate` считает `topic_fit / client_fit / performance / novelty / risk /
total` (0..100). MVP-веса: сильные теги +25, одобряемые темы +30, отклонённые −40,
usage/recency → novelty; частые повторы → risk (fatigue).

`choose_topic_for_next_schedule` возвращает лучшую рекомендацию (**ничего не публикует**).

## Генерация вариантов (`content_variant_service`, rule-based)

Без внешнего AI. Варианты отличаются заголовком/первым абзацем, CTA, длиной, углом
(выгода/кейс/продукт/технология/срочность) и структурой (короткий/экспертный/подборка/кейс):
- **A** — базовый стиль клиента (предпочитаемый CTA);
- **B** — усиленный CTA (оффер);
- **C** — другой угол / короче / кейс.

Учитывает `preferred/rejected_cta` и `forbidden_patterns` профиля.

## A/B-тестирование (`ab_testing_service`)

- `preview_topic` — предлагаемые варианты + оценка units (**бесплатно, без записи**);
- `create_experiment_from_topic` / `create_experiment_from_post` — создаёт эксперимент и
  **draft/needs_review посты** для вариантов (в очереди ревью), считает quality/predicted
  score, **платно** (идемпотентно);
- `record_variant_feedback` / `import_variant_metrics` — feedback и метрики варианта
  (**бесплатно**);
- `choose_winner(method="manual"|"auto")` — manual (клиент, бесплатно) или auto (анализ по
  метрикам, платно); отмечает winner/losers, завершает эксперимент;
- `build_experiment_summary` — сводка для UI.

## Анализ и выбор winner (`experiment_analysis_service`)

Взвешенная оценка варианта: **ER 35% · CTR 20% · client_approval 20% · low_edits 10% ·
quality 10% · saves/shares 5%**. При отсутствии реальных метрик — fallback на approval +
quality + predicted (уверенность ниже). Winner = лучший по итоговой оценке; причина — по
доминирующему сигналу; уверенность растёт с отрывом от второго места.

## Как winner обновляет обучение

При выборе winner: пост-winner получает событие `approved` (его CTA/тема/длина/медиа/теги
усиливаются в профиле), посты-losers — `rejected` (слабые сигналы). Профиль
пересчитывается; версия фиксируется в эксперименте.

## Интеграции

- **Очередь ревью**: карточка поста показывает, что он — вариант эксперимента
  (`A/B <ключ> · <название>`).
- **Импорт метрик**: если публикация относится к варианту — метрики привязываются к
  варианту (`measured`).
- **Расписание**: только `suggest_experiment_for_schedule`/`choose_topic_for_next_schedule`
  (рекомендация); worker поведение НЕ меняется без флага `SCHEDULE_EXPERIMENTS_ENABLED`.

## Биллинг

| Действие | units |
|----------|-------|
| рекомендации / preview / dry-run | 0 |
| feedback / привязка метрик | 0 |
| ручной выбор winner | 0 |
| создать A/B-эксперимент | 10 (+5 за каждый вариант сверх 2) |
| скоринг эксперимента / авто-winner анализ | 5 |

Неуспешное/заблокированное создание units **не** списывает; повтор с тем же
`idempotency_key` — без двойного списания и без дубля эксперимента.

## Приватность

Все эксперименты и обучение строго **per-project/account**; данные одного клиента не
смешиваются с другими; глобального обучения без явного согласия нет.

## Config / env

`AB_TESTING_ENABLED=true` · `AB_TESTING_AUTO_WINNER_ENABLED=false` ·
`AB_TESTING_DEFAULT_VARIANT_COUNT=2` · `AB_TESTING_MAX_VARIANTS=3` ·
`AB_TESTING_MIN_CONFIDENCE_TO_AUTO_APPLY=0.7` · `SCHEDULE_EXPERIMENTS_ENABLED=false` ·
`TOPIC_OPTIMIZATION_ENABLED=true` · `TOPIC_OPTIMIZATION_RECENCY_DAYS=60` ·
`TOPIC_OPTIMIZATION_MAX_RECOMMENDATIONS=10`.

## Аудит

`experiment.created/variant.created/scored/feedback.recorded/winner.selected/completed/
canceled`, `optimization.recommendations.generated`, `optimization.topic.selected`,
`ab_test.previewed`, `ab_test.blocked`. Без секретов.

## Миграция и модель

`0024_content_experiments` (down_revision `0023`, SQLite/PostgreSQL): таблицы
`content_experiments` и `content_experiment_variants` (A/B/C, оценки, метрики, winner).

## CLI

```bash
make topic-recommendations project_id=1 platform=telegram limit=10
make ab-experiment-preview project_id=1 platform=telegram topic="Футболки"
make ab-experiment-create project_id=1 platform=telegram topic="Футболки" dry_run=false
make experiment-score experiment_id=1
make experiment-winner experiment_id=1 method=auto dry_run=true
```

## UI

- `/ui/experiments`, `/ui/projects/{id}/experiments` — список + создание A/B по теме;
- `/ui/projects/{id}/experiments/{experiment_id}` — детали: варианты, метрики, выбор winner;
- `/ui/optimization`, `/ui/projects/{id}/optimization` — «что публиковать дальше»
  (стратегия + рекомендации);
- `/ui/projects/{id}/recommendations` — рекомендации контента;
- карточка на дашборде проекта (лучший CTA / тема, A/B тесты);
- в sidebar: **Эксперименты**, **Оптимизация**.

## Что дальше

Реальная A/B live-доставка · авто-подбор темы в worker (за флагом) · multi-armed bandit ·
Bayesian/Thompson sampling · платформенно-специфичная оптимизация · production live-auto
аудит.
