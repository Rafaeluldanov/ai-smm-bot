# Botfleet AI Workflow Manager — Business Execution Layer (v0.7.2)

Превращает бизнес-цели и AI-рекомендации в **управляемые процессы**. Там, где Executive
Layer говорит «что делать», а Chief of Staff — «вот задачи», Workflow Manager отвечает на
вопрос «как это довести до конца»: цель → этапы → ответственные → сроки → зависимости →
прогресс → блокеры → рекомендации.

```
Create Workflow → Generate Steps → Assign → Track → Analyze → Recommend
```

Это слой **управления процессами** (workflow management). Он структурирует и отслеживает
работу, но НИКОГДА не выполняет её за команду.

## 1. Workflow engine

`BusinessWorkflow` — процесс с целью, типом, статусом, сроком и прогрессом. Создаётся из
бизнес-цели (Business OS `BusinessObjective`) или AI-задачи (Chief of Staff `AIBusinessTask`)
через `create_workflow_from_goal` — источник записывается в `workflow_metadata`, сам источник
не меняется.

- `WorkflowType`: `growth` · `marketing` · `sales` · `content` · `operational` · `custom`.
- `WorkflowStatus`: `draft` · `active` · `paused` · `completed` · `cancelled`.

## 2. Этапы (steps)

`generate_workflow_steps` собирает этапы из трёх источников (с дедупом по названию, в порядке
приоритета):
1. приоритетные действия исполнительного плана (Executive Layer / Business OS);
2. открытые задачи AI Chief of Staff (интеграция «задача → этап»);
3. дефолтные этапы по типу процесса (когда AI-данных ещё нет).

Пример для `sales`: «Подготовить кейсы клиентов» → «Запустить кампанию» → «Оптимизировать
конверсию».

- `WorkflowStepStatus`: `pending` → `assigned` → `in_progress` → `blocked` → `completed` /
  `cancelled`.
- `assign_step` — только назначает ответственного (pending → assigned). **НЕ выполняет.**
- `complete_step` / `update_step_status` — только меняют статус. **Внешних действий нет.**

## 3. Прогресс (Part «Как считаются статусы»)

`calculate_workflow_progress` = **completed / (все этапы, кроме `cancelled`) × 100** → 0..100.
Пересчитывается при каждом изменении статуса этапа и сохраняется в `workflow.progress_percent`
(отменённые этапы исключаются из знаменателя).

## 4. Блокеры

`WorkflowBlocker` фиксирует, что мешает движению:
- `BlockerType`: `dependency` · `resource` · `approval` · `missing_data` · `external`;
- `severity`: low/medium/high/critical; `status`: open → resolved.

`create_blocker` помечает связанный этап как `blocked`. `resolve_blocker` снимает блокер и
возвращает blocked-этап в работу (`assigned`, если есть ответственный, иначе `pending`).

## 5. Health Score + рекомендации AI

`analyze_workflow_health` → `{health_score (0..100), risks, recommendations, ...}`:
- `health_score` = 100 − (12·открытые_блокеры + 10·просроченные_этапы + 6·застрявшие_этапы),
  зажат в [0..100];
- **просрочка** — дедлайн в прошлом при незакрытом этапе; **застревание** — этап
  in_progress/blocked без изменений ≥ 7 дней;
- `recommendations` подсказывают, как снять блокеры (по типу) и ускорить: например, блокер
  старше 7 дней → «назначьте ответственного»; in_progress без владельца → «назначьте его».

## 6. Связь с Chief of Staff и Business OS

- **Chief of Staff (v0.7.1)**: открытые `AIBusinessTask` становятся этапами процесса при
  генерации; `task_id` можно передать при создании процесса.
- **Business OS (v0.7.0)**: приоритетные `BusinessAction` исполнительного плана становятся
  этапами; `objective_id` бизнес-цели можно передать при создании процесса — после approve в
  Business OS удобно завести workflow-draft под цель.

## 7. Безопасность (инварианты, покрыты тестами)

- Workflow Manager **НЕ** выполняет задачи автоматически (assign/complete/status — только
  статус); **НЕ** меняет CRM/бюджет/продажи, **НЕ** запускает рекламу, **НЕ** публикует,
  **НЕ** включает live, **НЕ** совершает внешних действий;
- строго per-project (tenant isolation, в т. ч. роуты `/workflows/{id}`, `/steps/{id}`,
  `/blockers/{id}` через `require_workflow_access` / `require_workflow_step_access` /
  `require_workflow_blocker_access`); секретов нет; всё **бесплатно** (0 units);
- каждое изменение (`workflow.created/step_created/step_assigned/step_completed/
  blocker_created/blocker_resolved`) пишется в **AuditLog**;
- `workflow_manager_enabled` — kill-switch (default true).

## 8. API / UI / CLI

**API** (project- или workflow/step/blocker-guard):
- `POST /projects/{id}/workflows`, `GET /projects/{id}/workflows`;
- `GET /workflows/{id}`, `POST /workflows/{id}/generate-steps`, `GET /workflows/{id}/steps`,
  `GET /workflows/{id}/health`, `POST /workflows/{id}/blockers`;
- `POST /steps/{id}/assign`, `POST /steps/{id}/status`, `POST /blockers/{id}/resolve`.

**UI**: `/ui/projects/{id}/workflows` — «AI процессы» (активные процессы, timeline этапов,
блокеры, Health Score, рекомендации).

**CLI**: `make workflow-create project_id=1 name="Рост" type=sales`,
`make workflow-status project_id=1 | workflow_id=5`,
`make workflow-analyze workflow_id=5`.

## 9. Модель данных

- `BusinessWorkflow` — процесс (workflow_type/status/goal/target/current/progress_percent/
  start_date/deadline/workflow_metadata);
- `WorkflowStep` — этап (order_number/status/priority/owner_user_id/deadline/completed_at/
  progress_percent/step_metadata);
- `WorkflowBlocker` — блокер (blocker_type/severity/status/step_id/resolved_at).

Миграция: **`0054_ai_workflow_manager`** (down_revision `0053_ai_chief_of_staff`).
Конфиг: `workflow_manager_enabled` (kill-switch, default true).
