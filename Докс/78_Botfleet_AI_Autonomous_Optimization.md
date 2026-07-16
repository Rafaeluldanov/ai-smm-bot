# Botfleet AI Autonomous Optimization Engine (v0.8.1)

Слой оптимизации поверх Continuous Improvement. Где Continuous Improvement **находит** улучшения,
Autonomous Optimization **оценивает, приоритизирует и проверяет** их: считает Optimization Score,
ранжирует backlog, формирует эксперименты-гипотезы, измеряет и валидирует эффект и возвращает
результат обратно в Learning Engine.

```
Improvement Item → Optimization Score → Experiment → Measurement → Validation → Learning Update
```

Это **optimization / аналитический** слой. Он оценивает и проверяет, но НИКОГДА не применяет
улучшения, не меняет бизнес, KPI, CRM или бюджет и не запускает эксперименты автоматически.

## 1. Оптимизации, эксперименты, результаты

- `OptimizationItem` — оценённое улучшение (impact/confidence/cost/risk/optimization_score/
  priority/status; ссылка на `improvement_id`).
- `OptimizationExperiment` — гипотеза проверки (hypothesis/metric/baseline/target/status/
  measurement_period).
- `ExperimentResult` — измеренный итог (actual/expected/difference/validation_result/analysis;
  append-only).

Термины: `OptimizationStatus` (identified · planned · running · completed · cancelled);
`ExperimentStatus` (draft · approved · running · completed · failed);
`ValidationResult` (success · failure · inconclusive); `Priority` (critical · high · medium · low).

## 2. Как считается Optimization Score

```
Optimization Score = impact × confidence − cost − risk  →  clamp [0..100]
```

`confidence` берётся как доля (÷100), чтобы произведение осталось в шкале 0..100. Составляющие
(0..100) выводятся read-only из смежных слоёв:

- `impact` — по приоритету улучшения (critical 90 · high 70 · medium 50 · low 30) + 10 за значимые
  (high/critical) отклонения (Performance Intelligence);
- `confidence` — уверенность паттерна-источника улучшения (AIPattern), иначе 50;
- `cost` — эвристика по смыслу (смена стратегии 40 · данные/прогноз 25 · назначить владельца 10 ·
  иначе 20);
- `risk` — база 10 + заблокированные задачи исполнения (Execution Coordinator, ×5, максимум +20).

## 3. Как выбираются улучшения (приоритизация)

`_priority_from_score`: ≥75 critical · ≥50 high · ≥25 medium · иначе low. `prioritize_improvements`
переоценивает приоритет из score (если рассинхронизирован) и сортирует backlog
critical → low (при равенстве — по score убыв.). `explain_optimization` объясняет владельцу, почему
улучшение выбрано первым (разбор score = impact × confidence − cost − risk).

## 4. Как работают эксперименты

`create_experiment` формирует `OptimizationExperiment` для оптимизации: выводит метрику
(`_infer_metric`: execution_speed / forecast_accuracy / conversion / performance_score), гипотезу,
базу (текущий Performance Score) и цель (+15% к базе). Эксперимент создаётся в статусе **draft** —
он НЕ запускается автоматически и требует явного подтверждения владельца. Оптимизация переходит в
`planned`.

## 5. Как проходит validation

`evaluate_experiment` (чистая функция) сравнивает факт с целью и базой: `difference = actual −
target`. `validate_result` определяет итог с учётом направления метрики:

- «выше = лучше» (target > baseline): `actual ≥ target` → success · `actual ≤ baseline` → failure ·
  иначе inconclusive;
- «ниже = лучше» (target < baseline): зеркально;
- `target == baseline` → inconclusive.

`validate_experiment` (владелец подтверждает замером) фиксирует `ExperimentResult`, переводит
эксперимент в `completed`, оптимизацию в `completed` и вызывает обратную связь в Learning Engine.

## 6. Как создаётся feedback (Learning Update)

`create_learning_feedback` создаёт `LearningEvent` (слой Continuous Improvement) по итогу валидации
(success → success · failure → failure · inconclusive → insight) с метрикой и разницей в `impact`.
Так результат эксперимента **возвращается в Learning Engine**. Обратная связь **не меняет бизнес** —
это только запись обучения.

## 7. Безопасность (инварианты, покрыты тестами)

- Engine **НЕ** применяет улучшения, **НЕ** запускает эксперименты без подтверждения (draft), **НЕ**
  меняет бизнес/стратегию/KPI/CRM/бюджет, **НЕ** выполняет задачи, **НЕ** запускает рекламу, **НЕ**
  публикует (весь сбор смежных слоёв — read-only, в try/except: падение любого слоя не роняет оценку);
- строго per-project (гарды `require_project_access` / `require_optimization_access` /
  `require_optimization_experiment_access`); секретов нет; всё **бесплатно** (0 units:
  `USAGE_OPTIMIZATION_ANALYSIS`, `USAGE_OPTIMIZATION_REPORT`);
- каждое изменение (`optimization.created`, `optimization.prioritized`,
  `optimization.experiment_created`, `optimization.experiment_completed`,
  `optimization.experiment_validated`) → **AuditLog**;
- `autonomous_optimization_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / optimization- / experiment-guard):
- `POST /projects/{id}/optimization/analyze`, `GET /projects/{id}/optimizations`;
- `GET /optimizations/{id}`, `POST /optimizations/{id}/experiment`;
- `GET /optimization-experiments/{id}`, `POST /optimization-experiments/{id}/validate`.

Route-коллизии (namespaced): эксперименты под `/optimization-experiments/*` — `/experiments/*` занято
A/B content-experiments; аудит под `optimization.experiment_*` — `experiment.created/completed` заняты.

**UI**: `/ui/projects/{id}/ai-optimization` — «AI оптимизация» (AI Insights, Priority ranking с
экспериментами и валидацией, Improvement backlog). `/ui/projects/{id}/optimization` занят слоем
оптимизации тем — поэтому `ai-optimization`.

**CLI**: `make optimization-analyze project_id=1`, `make optimization-report project_id=1`.

## 9. Интеграции и модель данных

Интеграции (все read-only, try/except): **Continuous Improvement** (ImprovementItem / AIPattern /
LearningEvent), **Performance Intelligence** (PerformanceSnapshot / deviations),
**Execution Coordinator** (blocked tasks).

- `OptimizationItem` — (project/account/improvement_id/impact/confidence/cost/risk/optimization_score/
  priority/status);
- `OptimizationExperiment` — (optimization_id/hypothesis/metric/baseline/target/status/
  measurement_period);
- `ExperimentResult` — (experiment_id/actual/expected/difference/validation_result/analysis;
  append-only).

Миграция: **`0063_ai_autonomous_optimization`** (down_revision `0062_ai_continuous_improvement`).
Конфиг: `autonomous_optimization_enabled` (default true).
