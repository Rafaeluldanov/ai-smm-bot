# Botfleet AI Business Planner (v0.7.7)

Слой стратегического планирования поверх всей аналитики Botfleet. Где Forecasting прогнозирует
развитие бизнеса, Business Planner берёт **бизнес-цель владельца** и превращает её в конкретный
план: анализирует текущее состояние, сравнивает с прогнозом, находит gap, строит стратегию,
квартальные цели, KPI и roadmap — а по одобрению может создать черновик процесса.

```
Business Goal → Gap Analysis → Strategic Plan → Quarter Objectives → KPI → Milestones → Workflow Draft
```

Это **planning-слой**. Он планирует и советует, но НИКОГДА не выполняет план за владельца.

## 1. Цель, план, кварталы, вехи

- `BusinessGoal` — цель владельца (тип/цель/target/current/срок/статус).
- `StrategicPlan` — план достижения цели (gap-анализ, стратегия, уверенность).
- `QuarterObjective` — квартальная цель (Q1–Q4) с KPI и приоритетом.
- `PlanMilestone` — веха внутри квартальной цели.

Термины: `GoalType` (revenue · growth · sales · marketing · efficiency · operational);
`PlanStatus` (draft → generated → reviewed → approved → archived); `ObjectiveStatus` (planned →
active → completed → cancelled); `Priority` (critical · high · medium · low). Статус самой цели —
active → achieved/cancelled/archived.

## 2. Gap-анализ

`analyze_gap` сравнивает текущее состояние с целью:

```
gap = target − current;  gap_percent = gap / target × 100
```

Если `current_value` не задан (0), текущее значение подтягивается из **Business Forecasting
baseline** по метрике типа цели (revenue→revenue, sales→leads, growth→growth_score,
marketing→traffic, efficiency→efficiency, operational→health_score) — в try/except.

## 3. Стратегический план

`generate_strategic_plan`: `gap → стратегия → кварталы → KPI → вехи → уверенность`. Стратегия
(`approach`) зависит от gap%: ≤0 — удержание; <50% — поэтапное закрытие; ≥50% — агрессивный рост.
План собирает сигналы прогноза (Forecasting confidence) и решений (Decision Engine
recommended) — оба в try/except. Создаётся `StrategicPlan` (status=generated). План — **рекомендация,
не гарантия**.

## 4. Квартальные цели и KPI

`generate_quarter_objectives` создаёт Q1–Q4 (пересоздаёт при повторной генерации). KPI кажого
квартала — **доля закрытия gap** линейно:

```
quarter_target = current + (target − current) × (quarter / 4)
```

Так Q1 закрывает 25 % gap, …, Q4 достигает target. Каждой квартальной цели `create_milestones`
добавляет вехи (планирование + выполнение/замер).

## 5. Уверенность

```
confidence = 0.4 × forecast_confidence + 0.3 × data_quality + 0.3 × strategy_confidence
```

- `forecast_confidence` — уверенность из Business Forecasting;
- `data_quality` — есть ли current/target/прогноз (0..100);
- `strategy_confidence` — осуществимость (меньше gap% → выше).

## 6. Approve → Convert (связь с Workflow)

- `approve_plan` — только `status=approved` (из generated/reviewed). **НЕ выполняет.**
- `convert_to_workflow` — ТОЛЬКО при `status=approved` И `confirmation="CONVERT_PLAN"` → создаёт
  лишь **ЧЕРНОВИК процесса** (draft `BusinessWorkflow` через Workflow Manager, тип процесса — по
  типу цели). Ответ всегда `live_enabled=False`; процессы/CRM/бюджет/публикации не запускаются.

`explain_plan` объясняет владельцу, почему AI выбрал этот план.

## 7. Безопасность (инварианты, покрыты тестами)

- Planner **НЕ** выполняет план автоматически (approve/convert — только статус / draft workflow);
  **НЕ** меняет бизнес/CRM/бюджет, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ** включает live;
- convert возможен ТОЛЬКО при approved + подтверждении → лишь draft (live off);
- строго per-project (tenant isolation: `require_goal_access` / `require_plan_access` через goal→
  project); секретов нет; всё **бесплатно** (0 units: `USAGE_BUSINESS_PLAN`, `USAGE_PLAN_REPORT`);
- каждое изменение (`goal.created`, `plan.generated`, `objective.created`, `milestone.created`,
  `plan.approved`, `workflow.draft_created`) пишется в **AuditLog**;
- `business_planner_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / goal- / plan-guard):
- `POST /projects/{id}/goals`, `GET /projects/{id}/goals`;
- `GET /goals/{id}` (+ gap), `POST /goals/{id}/plan`;
- `GET /plans/{id}` (+ objectives + explanation), `GET /plans/{id}/objectives`,
  `POST /plans/{id}/approve`, `POST /plans/{id}/convert-workflow`.

**UI**: `/ui/projects/{id}/business-planner` — «AI стратегический план» (цель/gap, стратегия,
кварталы Q1–Q4 с KPI, milestones; кнопки Approve Plan / Create Workflow Draft).

**CLI**: `make goal-create project_id=1 type=revenue title="..." target=5000000 [current=1000000]`,
`make plan-generate goal_id=5`, `make plan-report plan_id=7`.

## 9. Модель данных

- `BusinessGoal` — цель (goal_type/title/target_value/current_value/target_date/status/
  goal_metadata; `metadata` зарезервировано SQLAlchemy → `goal_metadata`, в API как `metadata`);
- `StrategicPlan` — план (goal_id/status/summary/gap_analysis/strategy/confidence_score);
- `QuarterObjective` — квартальная цель (plan_id/quarter/kpi/priority/status);
- `PlanMilestone` — веха (objective_id/target_date/status/milestone_metadata).

Миграция: **`0059_ai_business_planner`** (down_revision `0058_ai_business_forecasting`; id ≤ 32
символов). Конфиг: `business_planner_enabled` (default true).
