# Botfleet AI Business Forecasting Engine (v0.7.6)

Слой долгосрочного прогноза поверх всей аналитики Botfleet. Где Strategy Simulator моделирует
последствия одного решения, Business Forecasting Engine прогнозирует развитие **всего бизнеса**
на 3/6/12 месяцев: берёт текущее состояние, проецирует KPI, вносит поправку на риск и строит
бизнес-outlook и квартальный roadmap.

```
Business State → Forecast Model → KPI Projection → Risk Adjustment → Business Outlook → Owner Review
```

Это **аналитический прогнозный** слой. Он прогнозирует и советует, но НИКОГДА не гарантирует
прибыль и не выполняет стратегии.

## 1. Прогноз

`BusinessForecast` — прогноз развития бизнеса на горизонт. Хранит базовое состояние
(`baseline_state`), многогоризонтный outlook (`forecast_state`), допущения, уровень риска,
уверенность и время генерации.

- `ForecastHorizon`: 3_months · 6_months · 12_months.
- `ForecastStatus`: generated → reviewed → archived.
- `BusinessMetric`: revenue · leads · customers · conversion · traffic · efficiency.
- `RiskLevel`: low · medium · high · critical.

`create_forecast` собирает baseline и создаёт прогноз (status=generated); сама проекция
запускается отдельно (`generate`).

## 2. Baseline — текущее состояние бизнеса

`collect_business_baseline` собирает состояние из смежных слоёв (каждый источник в try/except —
отсутствие слоя не роняет прогноз):

- **Sales / Growth** (executive state): `revenue`, `leads`, `conversion`, `growth_score`,
  `customers` (≈ сконвертированные лиды — модельная оценка, не CRM);
- **Analytics**: `traffic` (reach);
- **Operations Center** (snapshot): `health_score`, `workflow_progress`, `efficiency` (fallback).

Возвращает метрики + `_meta` (сколько источников дали данные) — это входит в оценку уверенности.

## 3. Модель прогноза (KPI projection)

`project_metric` проецирует метрику на `months` месяцев компаундингом:

```
monthly_growth = MAX_MONTHLY_GROWTH × (growth_score/100) × responsiveness × (1 − risk_penalty/100)
forecast_value = baseline × (1 + monthly_growth)^months
change_percent = ((1 + monthly_growth)^months − 1) × 100
```

- `growth_score` (0..100) — импульс роста бизнеса;
- `responsiveness` — отзывчивость метрики (revenue 1.0 … efficiency 0.45): деньги/лиды растут
  сильнее, чем конверсия/эффективность;
- при нулевой базе прогноз = 0 (нет данных — нет прогноза);
- `MAX_MONTHLY_GROWTH` = 0.06 (6 %/мес при полном импульсе и нулевом риске → ~+100 % за 12 мес).

`generate_business_outlook` строит: (1) `forecast_state` — outlook по ключевым метрикам на 3/6/12
месяцев; (2) `ForecastMetric` — KPI-проекция на выбранном горизонте (по строке на BusinessMetric;
append-only, пересчитывается заново); (3) `BusinessRoadmap`. Прогноз — **модельная оценка, не
финансовая гарантия**.

## 4. Поправка на риск

`apply_risk_adjustment` собирает риск-сигналы и считает штраф (0..50):

```
risk_penalty = operations_risks×8 + workflow_blockers×5 + decision_risks×4 + health_deficit
```

- **Operations Risks** — открытые операционные риски + дефицит health (`(70−health)×0.3`);
- **Workflow Blockers** — открытые блокеры по активным процессам;
- **Decision Risks** — недавние решения с рискованными сценариями (risk ≥ 60).

Уровень: <10 low · <25 medium · <40 high · иначе critical. Штраф гасит месячный рост в проекции.

## 5. Уверенность

```
confidence = 0.30 × data_score + 0.25 × stability + 0.30 × signal_quality + 0.15 × history_score
```

- `data_score` — доля источников baseline с данными;
- `stability` = 100 − risk_penalty;
- `signal_quality` = growth_score (ясность импульса);
- `history_score` — накопленная история прогнозов проекта (`min(100, N×25)`).

Результат — 0..100 (clamp).

## 6. Roadmap

`create_business_roadmap` разворачивает прогноз в квартальный план:

- **quarters** — Q1 Фундамент → Q2 Рост → Q3 Масштабирование → Q4 Закрепление (цели учитывают
  слабые места baseline);
- **milestones** — вехи по горизонтам (ожидаемое изменение выручки на 3/6/12);
- **risks** — из сигналов поправки на риск;
- **recommendations** — по слабым метрикам (только советы).

`explain_forecast` объясняет владельцу, почему AI прогнозирует такой рост.

## 7. Безопасность (инварианты, покрыты тестами)

- Engine **НЕ** гарантирует прибыль/финансовый результат (прогноз — модельная оценка);
- **НЕ** меняет бизнес/CRM/бюджет, **НЕ** выполняет стратегии, **НЕ** публикует, **НЕ** включает
  live, **НЕ** создаёт процессов, **НЕ** ходит во внешние API;
- строго per-project (tenant isolation: `require_forecast_access`); секретов нет; всё
  **бесплатно** (0 units: `USAGE_BUSINESS_FORECAST`, `USAGE_FORECAST_REPORT`);
- каждое изменение (`forecast.created/generated/metric_created/roadmap_created`) пишется в
  **AuditLog**;
- `business_forecasting_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / forecast-guard):
- `POST /projects/{id}/forecasts`, `GET /projects/{id}/forecasts`;
- `GET /forecasts/{id}`, `POST /forecasts/{id}/generate`, `GET /forecasts/{id}/metrics`,
  `GET /forecasts/{id}/roadmap`;
- `GET /projects/{id}/business-outlook`.

**UI**: `/ui/projects/{id}/business-forecast` — «AI прогноз бизнеса» (текущее состояние, прогноз
3/6/12, KPI-таблица baseline→forecast/Δ%, roadmap Q1–Q4, риски).

**CLI**: `make forecast-create project_id=1 [horizon=12_months]`,
`make forecast-generate forecast_id=7`, `make forecast-report forecast_id=7`.

## 9. Модель данных

- `BusinessForecast` — прогноз (horizon/status/baseline_state/forecast_state/assumptions/
  risk_level/confidence_score/generated_at);
- `ForecastMetric` — KPI-проекция метрики (metric/baseline_value/forecast_value/change_percent/
  confidence_score/reasoning; append-only);
- `BusinessRoadmap` — квартальный roadmap (quarters/milestones/risks/recommendations).

Миграция: **`0058_ai_business_forecasting`** (down_revision `0057_ai_strategy_simulator`; id ≤ 32
символов). Конфиг: `business_forecasting_enabled` (default true).
