# Botfleet AI Performance Intelligence Engine (v0.7.9)

Слой измерения эффективности поверх всей цепочки исполнения. Где Execution Coordinator управляет
задачами, Performance Intelligence **измеряет результат**: собирает фактические показатели,
сравнивает с планом, считает Performance Score, находит отклонения, определяет причины и советует
улучшения.

```
Execution Plan → Performance Snapshot → Actual vs Target → Deviation Analysis → Recommendations
```

Это **аналитический** слой. Он измеряет и советует, но НИКОГДА не меняет планы, KPI или бизнес.

## 1. Снимок, метрики, отклонения, рекомендации

- `PerformanceSnapshot` — снимок эффективности (score/status/target_state/actual_state).
- `PerformanceMetric` — план vs факт по метрике (target/actual/difference/%/status; append-only).
- `PerformanceDeviation` — значимое отклонение (тип/влияние/причины; append-only).
- `PerformanceRecommendation` — совет по улучшению (приоритет/ожидаемый эффект).

Термины: `PerformanceStatus` (healthy · warning · critical); `MetricType` (revenue · sales · leads
· conversion · execution · efficiency); `DeviationType` (positive · negative · neutral);
`ImpactLevel` (low · medium · high · critical).

## 2. Как считается Performance Score

```
Performance Score = execution_score + kpi_score + velocity_score − risk_penalty  →  clamp [0..100]
```

- `execution_score` (0..40) — прогресс исполнения (Execution Coordinator) × 0.4;
- `kpi_score` (0..40) — средняя доля достижения KPI (revenue/sales/leads/conversion),
  `min(1, actual/target)` × 40;
- `velocity_score` (0..20) — доля завершённых задач последнего плана исполнения × 20;
- `risk_penalty` (0..20) — открытые операционные риски × 4 + заблокированные задачи × 3.

Статус: ≥70 healthy · ≥40 warning · иначе critical.

## 3. Как сравнивается план и факт

`collect_actual_metrics` собирает факт: revenue/leads/conversion (Executive), sales (= leads ×
conversion), execution (прогресс плана исполнения), efficiency (growth/health). `collect_target_metrics`
собирает план: цели владельца (Business Planner, goal_type → метрика, target_value), execution = 100,
efficiency = 100, revenue-ориентир из Forecasting. `compare_metrics`:

```
difference = actual − target;  difference_percent = difference / target × 100
```

Статус метрики: ≥ −5 % healthy · ≥ −25 % warning · иначе critical (метрики без плана пропускаются).

## 4. Как находятся отклонения

`detect_deviations` создаёт `PerformanceDeviation` для каждой метрики со статусом warning/critical
(недовыполнение). Влияние по величине: <15 % low · <30 % medium · <50 % high · иначе critical;
тип — negative (факт < план) / positive.

## 5. Как AI ищет причины

`analyze_root_causes` (только чтение) собирает вероятные причины: метрические (leads → «нет лидов»,
conversion → «низкая конверсия»), исполнение (блокеры / задержка задач — Execution Coordinator),
операционные (открытые риски — Operations Center). Причины прикрепляются к отклонениям.

## 6. Как формируются рекомендации

`generate_recommendations` создаёт `PerformanceRecommendation` по каждому отклонению (совет по
метрике: leads → «Увеличить поток лидов», conversion → «Улучшить конверсию» и т. д.), приоритет = по
величине отклонения. `explain_performance` объясняет владельцу, почему такой Score. Рекомендации —
**только советы, не выполняются**.

## 7. Безопасность (инварианты, покрыты тестами)

- Engine **НЕ** меняет планы/KPI, **НЕ** меняет бизнес/CRM/бюджет, **НЕ** выполняет задачи и
  рекомендации, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ** ходит во внешние действия
  (весь сбор смежных слоёв — read-only, в try/except — падение любого слоя не роняет анализ);
- строго per-project (гард `require_performance_snapshot_access`); секретов нет; всё **бесплатно**
  (0 units: `USAGE_PERFORMANCE_ANALYSIS`, `USAGE_PERFORMANCE_REPORT`);
- каждое изменение (`performance.snapshot_created`, `performance.metric_created`,
  `performance.deviation_detected`, `performance.recommendation_created`) → **AuditLog**;
- `performance_intelligence_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / snapshot-guard):
- `POST /projects/{id}/performance/analyze`, `GET /projects/{id}/performance`;
- `GET /performance/{id}`, `GET /performance/{id}/metrics`, `GET /performance/{id}/deviations`,
  `GET /performance/{id}/recommendations`.

**UI**: `/ui/projects/{id}/performance` — «AI эффективность» (Performance Score, план vs факт,
проблемы/deviation-cards, причины, AI-рекомендации).

**CLI**: `make performance-analyze project_id=1`, `make performance-report snapshot_id=7`.

## 9. Интеграции и модель данных

Интеграции (все read-only, try/except): **Execution Coordinator** (progress/tasks/blockers),
**Operations Center** (health/risks), **Business Planner** (goals/KPI), **Business Forecasting**
(targets), **Executive** (actual revenue/leads/conversion).

- `PerformanceSnapshot` — снимок (project/execution_plan_id/status/performance_score/metrics/
  target_state/actual_state);
- `PerformanceMetric` — метрика (snapshot_id/metric/target/actual/difference/percent/status;
  append-only);
- `PerformanceDeviation` — отклонение (snapshot_id/deviation_type/metric/impact/root_causes;
  append-only);
- `PerformanceRecommendation` — рекомендация (snapshot_id/priority/expected_effect/status).

Миграция: **`0061_ai_performance_intelligence`** (down_revision `0060_ai_execution_coordinator`;
id = 32 символа, ровно в лимите varchar(32)). Конфиг: `performance_intelligence_enabled` (default
true).
