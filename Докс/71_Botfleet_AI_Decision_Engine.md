# Botfleet AI Decision Engine (v0.7.4)

Слой принятия решений поверх всей аналитики Botfleet. Где Operations Center показывает
проблемы и риски, Decision Engine превращает проблему в **выбор**: строит варианты
(сценарии), оценивает их эффект/риск/стоимость, сравнивает и рекомендует лучший — чтобы
владелец принял осознанное решение.

```
Problem → Decision Options → Scenario Analysis → AI Recommendation → Owner Approval
```

Это **аналитический и рекомендательный** слой. Он оценивает и советует, но НИКОГДА не
применяет решения за владельца.

## 1. Decision Engine

`AIDecision` — решение с проблемой, целью, типом и статусом. Создаётся из операционного
риска (Operations Center), бизнес-действия (Business OS), задачи владельца (Chief of Staff)
или вручную (источник фиксируется в `context`, сам источник не меняется).

- `DecisionType`: growth · revenue · marketing · sales · content · efficiency · operational.
- `DecisionStatus`: draft → analyzing → recommended → accepted → applied (и rejected/reviewed).
- `DecisionPriority`: critical · high · medium · low.

## 2. Как AI принимает решения

`analyze_decision` выполняет полный цикл:
1. **collect_signals** — взвешенные сигналы из смежных слоёв (Operations health/риски, Growth
   score, Sales выручка/конверсия, Workflow процессы/блокеры, Campaign активные кампании) —
   `DecisionSignal` (source_module, signal_type, value, weight); каждый сбор в try/except;
2. **generate_scenarios** — варианты решения по типу (см. §3);
3. **evaluate_scenarios** — Decision Score каждого варианта (см. §4);
4. **recommend_best_scenario** — лучший по score, `status=recommended`.

## 3. Как строятся сценарии

`generate_scenarios` создаёт `DecisionScenario` из шаблонов по типу решения (дедуп по
заголовку). Пример для проблемы «низкая конверсия» (efficiency):

1. **Улучшить CTA и офферы**;
2. **Создать новую кампанию**;
3. **Изменить контентную стратегию**.

Каждый сценарий несёт допущения, ожидаемый эффект (`impact`), анализ риска (`risk` + уровень),
оценку стоимости (`cost`) и уверенность (`confidence_score`).

## 4. Как считается Decision Score

```
Decision Score = impact × (confidence / 100) − risk_weight × risk   →  clamp [0..100]
```

- `impact` (0..100) — ожидаемый эффект сценария;
- `confidence` (0..100) — уверенность в сценарии;
- `risk` (0..100) — риск сценария; `risk_weight` = 0.3 обычно, **0.5 если владелец риск-аверсен**
  (учёт предпочтений из Chief of Staff Decision Memory).

Пример: impact 80, confidence 75%, risk 20 → 80·0.75 − 0.3·20 = 54.0.

## 5. Как выбирается лучший вариант

`recommend_best_scenario` берёт сценарий с максимальным Decision Score (среди не отклонённых),
проставляет `decision.recommended_scenario_id` и `confidence_score`, статус `recommended`.
Возвращает `{scenario, score, reason}` (например, «Максимальный эффект при приемлемом риске»).
`explain_decision` объясняет владельцу, почему выбран именно этот путь. Владелец может
`select`/`reject` сценарии вручную (только статус).

## 6. Approve flow

Статусы владельца: **recommended → accepted → applied**.
- `accept_decision` — только `status=accepted` (из recommended/reviewed). **НЕ выполняет.**
- `apply_decision` — ТОЛЬКО при `status=accepted` И `confirmation="APPLY_DECISION"` → создаёт
  лишь **ЧЕРНОВИК процесса** (draft `BusinessWorkflow` из рекомендованного сценария, тип
  процесса — по типу решения). Ответ всегда `live_enabled=False`.

## 7. Безопасность (инварианты, покрыты тестами)

- Decision Engine **НЕ** применяет решения автоматически (select/reject/accept — только статус);
  **НЕ** меняет бизнес/CRM/бюджет/продажи, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ**
  включает live, **НЕ** запускает процессы (apply создаёт лишь draft workflow);
- строго per-project (tenant isolation, в т. ч. `/ai-decisions/{id}`, `/scenarios/{id}` через
  `require_ai_decision_access` / `require_decision_scenario_access`); секретов нет; всё
  **бесплатно** (0 units);
- каждое изменение (`decision.created/analyzed/scenario_created/scenario_selected/accepted/
  applied`) пишется в **AuditLog**;
- `decision_engine_enabled` (kill-switch, default true) + `decision_engine_auto_apply_enabled`
  (default false — apply только через Approve).

## 8. API / UI / CLI

**API** (project- или decision/scenario-guard). Роуты под `/ai-decisions` — во избежание
коллизии с `/decisions` слоя Chief of Staff (v0.7.1):
- `POST /projects/{id}/ai-decisions`, `GET /projects/{id}/ai-decisions`;
- `GET /ai-decisions/{id}`, `POST /ai-decisions/{id}/analyze`, `GET /ai-decisions/{id}/scenarios`,
  `GET /ai-decisions/{id}/explanation`, `POST /ai-decisions/{id}/accept|apply`;
- `POST /scenarios/{id}/select|reject`.

**UI**: `/ui/projects/{id}/decisions` — «AI решения» (проблема, карточки вариантов с эффектом/
риском/уверенностью/score, рекомендация AI, «почему», кнопки Выбрать/Отклонить/Принять/Применить).

**CLI**: `make decision-create project_id=1 type=efficiency title="..."`,
`make decision-analyze decision_id=5`, `make decision-report decision_id=5`.

## 9. Модель данных

- `AIDecision` — решение (decision_type/status/priority/problem_statement/objective/context/
  recommended_scenario_id/confidence_score);
- `DecisionScenario` — вариант (assumptions/expected_impact{impact,score}/risk_analysis/
  cost_estimate/confidence_score/status);
- `DecisionSignal` — взвешенный сигнал (source_module/signal_type/value/weight; append-only).

Миграция: **`0056_ai_decision_engine`** (down_revision `0055_ai_operations_center`; id ≤ 32
символов). Конфиг: `decision_engine_enabled` (default true), `decision_engine_auto_apply_enabled`
(default false).
