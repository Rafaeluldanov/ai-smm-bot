# Botfleet AI Strategy Simulator (v0.7.5)

Слой моделирования будущего поверх Decision Engine. Где Decision Engine строит варианты решения
и рекомендует лучший, Strategy Simulator берёт конкретный **сценарий решения** и прогнозирует его
последствия во времени: строит прогноз метрик на 30/60/90 дней, оценивает уверенность, сравнивает
сценарии и показывает ожидаемый результат — чтобы владелец увидел «что будет, если».

```
Decision Scenario → Simulation → Forecast → Comparison → Recommendation
```

Это **аналитический** слой. Он моделирует и советует, но НИКОГДА не гарантирует прибыль и не
выполняет стратегию.

## 1. Симуляция

`StrategySimulation` — прогон одного `DecisionScenario` (Decision Engine) через модель будущего.
Хранит цель, допущения (копируются из сценария), горизонт, уровень уверенности и итоговую оценку.

- `ForecastPeriod`: 30_days · 60_days · 90_days · custom.
- `ForecastMetric`: revenue · leads · conversion · traffic · engagement · efficiency.
- `SimulationStatus`: generated → running → completed → reviewed.
- `ConfidenceLevel`: low · medium · high.

`create_simulation` строится строго из сценария этого проекта (tenant isolation: сценарий →
решение → проект). Само моделирование НЕ запускается при создании.

## 2. Baseline — текущее состояние

`collect_baseline` собирает базовые метрики из смежных слоёв (каждый источник в try/except —
отсутствие слоя не роняет симуляцию, метрика остаётся 0):

- **Sales / Growth** (executive state): `revenue`, `leads`, `conversion`, `efficiency` (growth score);
- **Analytics** (project summary): `traffic` (reach), `engagement` (avg engagement rate);
- **Operations Center** (snapshot): `efficiency` (health-score как запасной сигнал) + полнота данных.

Возвращает метрики + `_meta` (сколько источников дали данные) — это входит в оценку уверенности.

## 3. Моделирование будущего

`simulate_scenario` (роут `run`): `baseline → прогноз каждой метрики на 30/60/90 дней → уверенность`.
Для каждой метрики и горизонта:

```
monthly_lift = MAX_MONTHLY_LIFT × (impact/100) × responsiveness × (1 − 0.5 × risk/100)
cumulative   = monthly_lift × months^0.9            # мягко убывающая отдача
forecast_value = baseline × (1 + cumulative)
change_percent = cumulative × 100
```

- `impact`, `risk`, `confidence` берутся из `DecisionScenario`;
- `responsiveness` — отзывчивость метрики (revenue 1.0 … efficiency 0.5): деньги/лиды двигаются
  сильнее, чем конверсия/эффективность;
- при нулевой базе прогноз = 0 (нет данных — нет прогноза);
- `MAX_MONTHLY_LIFT` = 0.12 (12 % в месяц при полном эффекте и нулевом риске).

Каждый горизонт — строка `ForecastResult` (append-only; при повторном `run` прогнозы
пересчитываются заново). Прогноз — **модельная оценка, не финансовая гарантия**.

## 4. Уверенность прогноза

```
confidence = 0.4 × signal_quality + 0.35 × data_score + 0.25 × stability   →  clamp [0..100]
```

- `signal_quality` — уверенность сценария (`confidence_score`);
- `data_score` — доля источников baseline, давших данные;
- `stability` = 100 − risk (стабильность обратна риску).

Уверенность **падает с горизонтом** (дальше — менее уверенно). Уровень: <40 low · <70 medium ·
иначе high.

## 5. Сравнение сценариев

`compare_scenarios` сопоставляет все не отклонённые сценарии решения по Strategy Score:

```
Strategy Score = impact × (confidence / 100) − risk_weight × risk   →  clamp [0..100]
```

`risk_weight` = 0.3 обычно, **0.5 если владелец риск-аверсен** (Chief of Staff Decision Memory).
Победитель — максимум; `score_difference` — отрыв от следующего. Результат сохраняется как
`ScenarioComparison` (append-only; берётся последнее сравнение).

## 6. Рекомендация

`recommend_strategy` возвращает `{winner, confidence, reason}` по лучшему сценарию (при отсутствии
сравнения — строит его сам). Пример reason: «Лучший баланс эффекта и риска; уверенный отрыв от
альтернатив». `explain_forecast` объясняет владельцу траекторию метрик на 90 дней. Обе выдачи —
**только совет**; решение принимает владелец.

## 7. Безопасность (инварианты, покрыты тестами)

- Simulator **НЕ** гарантирует прибыль/финансовый результат (прогноз — модельная оценка);
- **НЕ** меняет бизнес/CRM/бюджет/продажи, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ**
  включает live, **НЕ** выполняет стратегии и **НЕ** меняет статус решения (не «применяет» его);
- строго per-project (tenant isolation: `require_simulation_access`, а `create_simulation`
  проверяет, что сценарий принадлежит решению этого проекта); секретов нет; всё **бесплатно**
  (0 units: `USAGE_STRATEGY_SIMULATION`, `USAGE_FORECAST_REPORT`);
- каждое изменение (`simulation.created/started/completed/compared/recommended`) пишется в
  **AuditLog**;
- `strategy_simulator_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / simulation- / decision-guard):
- `POST /projects/{id}/simulations`, `GET /projects/{id}/simulations`;
- `GET /simulations/{id}`, `POST /simulations/{id}/run`, `GET /simulations/{id}/forecast`;
- `POST /decisions/{id}/compare-scenarios`, `GET /decisions/{id}/strategy-recommendation`.

**UI**: `/ui/projects/{id}/strategy-simulator` — «AI прогноз стратегии» (выбор решения → сценария,
запуск симуляции, таблица прогноза baseline→forecast/Δ%/уверенность, сравнение сценариев и
рекомендация).

**CLI**: `make simulation-create project_id=1 scenario_id=5 [period=90_days]`,
`make simulation-run simulation_id=7`, `make simulation-report simulation_id=7`.

## 9. Модель данных

- `StrategySimulation` — симуляция (project/decision/scenario/status/title/objective/assumptions/
  simulation_period/confidence_level/overall_score);
- `ForecastResult` — прогноз метрики (simulation_id/metric/period/baseline_value/forecast_value/
  change_percent/confidence_score/reasoning; append-only);
- `ScenarioComparison` — сравнение сценариев решения (decision_id/winner_scenario_id/
  comparison_data/score_difference/reasoning; append-only, winner — мягкая ссылка без FK).

Миграция: **`0057_ai_strategy_simulator`** (down_revision `0056_ai_decision_engine`; id ≤ 32
символов). Конфиг: `strategy_simulator_enabled` (default true).
