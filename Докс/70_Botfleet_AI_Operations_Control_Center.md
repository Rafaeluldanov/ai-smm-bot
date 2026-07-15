# Botfleet AI Operations Control Center (v0.7.3)

Единая операционная панель бизнеса. Собирает воедино всё, что уже знают верхние слои
Botfleet — состояние бизнеса, рост, продажи, процессы, исполнение — в один **health-снапшот**
с рисками и рекомендациями для владельца.

```
Collect Signals → Calculate Health → Detect Risks → Generate Recommendations → Owner Review
```

Это **аналитический и управленческий** слой. Он видит всю операционную картину и советует,
но НИКОГДА не выполняет действия за команду.

## 1. Operations Center

`build_operations_snapshot` собирает сигналы из всех слоёв, считает health-score, детектит
риски и генерирует рекомендации, сохраняя `OperationsSnapshot` (health, статус, метрики,
подсостояния бизнеса/роста/продаж/процессов, счётчик рисков). Владелец видит одну панель
вместо семи отдельных экранов.

- `OperationsHealthStatus`: `healthy` (≥70) · `warning` (≥40) · `critical` (<40).
- `OperationsMetricType`: revenue · growth · sales · content · workflow · execution · risk.

## 2. Health Score

`calculate_health_score` — взвешенная сумма компонентов минус штраф за риски, зажатая в
`0..100`:

```
Health = 0.35·Growth + 0.25·Revenue + 0.20·Execution + 0.20·WorkflowProgress − RiskPenalty
```

- **Growth** — growth_score (Executive/Growth Agent);
- **Revenue** — `min(100, total_revenue/1000)`;
- **Execution** — среднее health активных процессов (или нейтральные 70, если процессов нет);
- **WorkflowProgress** — средний прогресс активных процессов (0% остаётся 0%, не подменяется);
- **RiskPenalty** — сумма по тяжести открытых рисков (critical 15 · high 10 · medium 6 · low 3),
  ограничена 40.

Пример: Growth 80, Revenue 75, Execution 70, WorkflowProgress 80, риски −10 → Health ≈ 76.

## 3. Источники данных

`_collect_signals` переиспользует (каждый в try/except — сбой слоя не роняет снапшот):
- **AI Executive Layer (v0.7.0)** — `analyze_business_state`: business_health, growth_score,
  выручка, конверсия, контент, риски, возможности;
- **AI Chief of Staff (v0.7.1)** — открытые задачи + наличие брифинга;
- **AI Workflow Manager (v0.7.2)** — активные процессы: средний прогресс/health, открытые
  блокеры, застрявшие/просроченные этапы;
- **Growth / Sales / Content** — внутри executive-состояния.

## 4. Риски

`detect_risks` находит проблемы и создаёт `OperationsRisk` (дедуп: если открытый риск такого
типа уже есть — не дублируется):

| `OperationsRiskType` | Триггер | Источник |
|---|---|---|
| `workflow_delay` | застрявшие/просроченные этапы | workflow_manager |
| `execution_block` | открытые блокеры процессов | workflow_manager |
| `revenue_drop` | выручка ниже, чем в прошлом снапшоте | sales_intelligence |
| `conversion_drop` | конверсия ниже, чем в прошлом снапшоте | sales_intelligence |
| `content_gap` | слабые темы / низкая эффективность контента | content_strategy |
| `missing_data` | нет выручки и лидов | operations_center |

`resolve_risk` лишь меняет статус на `resolved` — действий не выполняет.

## 5. Рекомендации

`generate_recommendations` превращает открытые риски в `OperationsRecommendation` (что сделать,
почему, ожидаемый эффект) с приоритетом от тяжести риска. Дедуп по заголовку среди всех
статусов — принятые/отклонённые не появляются заново. Цикл владельца: **generated →
accepted / rejected** (только статус, без исполнения). `explain_operations_state` отвечает на
вопрос «почему здоровье 76/100» (вклад компонентов + штраф рисков + главные риски).

## 6. Безопасность (инварианты, покрыты тестами)

- Operations Center **НЕ** выполняет рекомендации/действия автоматически (resolve/accept/reject
  — только статус); **НЕ** меняет CRM/бюджет/продажи, **НЕ** запускает рекламу, **НЕ**
  публикует, **НЕ** включает live, **НЕ** совершает внешних действий;
- строго per-project (tenant isolation, в т. ч. роуты `/risks/{id}`, `/recommendations/{id}`
  через `require_operations_risk_access` / `require_operations_recommendation_access`);
  секретов нет; всё **бесплатно** (0 units);
- каждое изменение (`operations.snapshot_created/risk_created/risk_resolved/
  recommendation_created/recommendation_accepted/recommendation_rejected`) — в **AuditLog**;
- `operations_center_enabled` — kill-switch (default true).

## 7. API / UI / CLI

**API** (project- или risk/recommendation-guard):
- `GET /projects/{id}/operations`, `POST /projects/{id}/operations/analyze`,
  `GET /projects/{id}/operations/history`, `GET /projects/{id}/operations/explanation`;
- `GET /projects/{id}/operations/risks`, `POST /risks/{id}/resolve`;
- `GET /projects/{id}/operations/recommendations`, `POST /recommendations/{id}/accept|reject`.

**UI**: `/ui/projects/{id}/operations` — «AI Operations Center» (большой Health Score, бизнес-
состояние, карточки рисков и рекомендаций, «почему такой health»).

**CLI**: `make operations-analyze project_id=1`, `make operations-report project_id=1`.

## 8. Модель данных

- `OperationsSnapshot` — снимок (health_score/status/metrics/business_state/growth_state/
  sales_state/workflow_state/risk_count/generated_at);
- `OperationsRisk` — риск (risk_type/severity/status/source_module/source_entity_id/impact/
  recommended_action/resolved_at);
- `OperationsRecommendation` — рекомендация (priority/reasoning/source_signals/expected_impact/
  status).

Миграция: **`0055_ai_operations_center`** (down_revision `0054_ai_workflow_manager`; id ≤ 32
символов — ограничение `alembic_version.version_num`). Конфиг: `operations_center_enabled`
(kill-switch, default true).
