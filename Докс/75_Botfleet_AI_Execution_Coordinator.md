# Botfleet AI Execution Coordinator (v0.7.8)

Слой управления исполнением поверх Business Planner. Где Planner превращает цель в стратегический
план, Execution Coordinator берёт **утверждённый план** и превращает его в управляемую систему
исполнения: цели → задачи → владельцы → сроки → прогресс → блокеры → AI-координация.

```
Approved Strategic Plan → Execution Plan → Objectives → Tasks → Owners → Progress → AI Coordination
```

Это **coordination-слой**. Он координирует и советует, но НИКОГДА не выполняет задачи за владельца.

## 1. План, цели, задачи, зависимости

- `ExecutionPlan` — план исполнения (из утверждённого `StrategicPlan`; статус/прогресс/сроки).
- `ExecutionObjective` — цель исполнения (из квартальной цели плана; KPI/приоритет/владелец/прогресс).
- `ExecutionTask` — задача цели (владелец/срок/приоритет/статус/прогресс).
- `ExecutionDependency` — зависимость задачи (task/objective/external; append-only).

Термины: `ExecutionStatus` (draft · active · paused · completed · cancelled — план/цель);
`ExecutionTaskStatus` (pending · assigned · in_progress · blocked · completed · cancelled);
`ExecutionPriority` (critical · high · medium · low); `DependencyType` (task · objective · external).

## 2. Как Strategic Plan превращается в Execution Plan

`create_execution_plan` принимает **только УТВЕРЖДЁННЫЙ** (`status=approved`) стратегический план
этого проекта (иначе — ошибка). Создаётся `ExecutionPlan` (status=draft) со ссылкой
`strategic_plan_id`. `generate_execution` затем строит цели и задачи и переводит план в `active`.

## 3. Как создаются задачи

`generate_execution_objectives` создаёт цель исполнения на каждую квартальную цель стратегического
плана (дедуп по title, KPI/приоритет копируются). `generate_execution_tasks` разбивает каждую цель
на задачи по шаблону: **Подготовить → Выполнить → Проанализировать результат** (status=pending, без
владельца). Регенерация не размножает (дедуп по title).

## 4. Как считается прогресс

```
progress = completed tasks / all tasks (кроме cancelled) × 100
```

`calculate_execution_progress` пересчитывает и сохраняет прогресс на плане. `complete_task` ставит
задаче `completed` (100 %) и пересчитывает прогресс плана.

## 5. Как работают blockers

`detect_blockers` **аналитически** (статус задач НЕ меняет) находит:

- **overdue** — срок задачи прошёл;
- **no_owner** — нет владельца ≥ 7 дней;
- **no_progress** — задача assigned/in_progress без прогресса ≥ 3 дней;
- **dependency** — незакрытая зависимость (задача-предшественник не completed);
- **blocked** — задача явно помечена blocked.

`generate_coordination_recommendations` формирует советы («Задача без владельца N дней» →
«Назначить ответственного»), учитывая стиль управления владельца (Chief of Staff Decision Memory).
`get_health` возвращает прогресс + блокеры + рекомендации + счётчики.

## 6. Как связка с Workflow

`create_workflow_link` — ТОЛЬКО по подтверждению `LINK_WORKFLOW` создаёт **ЧЕРНОВИК процесса**
(draft `BusinessWorkflow` через Workflow Manager) и сохраняет ссылку в `task_metadata.workflow_link`.
Процесс НЕ запускается; ответ всегда `live_enabled=False`. Владелец назначается через `assign_owner`
(только `owner_user_id` + статус, и только участнику аккаунта проекта).

## 7. Безопасность (инварианты, покрыты тестами)

- Coordinator **НЕ** выполняет задачи автоматически (assign/status/complete — только статус/владелец);
  **НЕ** меняет бизнес/CRM/бюджет, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ** включает live;
- `create_execution_plan` — только из **approved** плана проекта; `assign_owner` — только участнику
  аккаунта проекта (tenant isolation); `create_workflow_link` — только draft, по подтверждению;
- строго per-project (гарды `require_execution_plan_access` / `require_execution_task_access`);
  секретов нет; всё **бесплатно** (0 units: `USAGE_EXECUTION_PLAN`, `USAGE_EXECUTION_REPORT`);
- каждое изменение (`execution.created`, `execution.objective_created`, `execution.task_created`,
  `execution.task_assigned`, `execution.task_completed`, `execution.blocker_detected`) → **AuditLog**;
- `execution_coordinator_enabled` (kill-switch, default true).

## 8. API / UI / CLI

**API** (project- / plan- / task-guard). **Задачи — под `/execution-tasks/{id}`** (во избежание
коллизии: `/tasks/{id}/assign` занят media-curation, `/tasks/{id}` — Chief of Staff/media-curation):
- `POST /projects/{id}/execution-plans`, `GET /projects/{id}/execution-plans`;
- `GET /execution-plans/{id}`, `POST /execution-plans/{id}/generate`,
  `GET /execution-plans/{id}/tasks`, `GET /execution-plans/{id}/health`;
- `POST /execution-tasks/{id}/assign`, `POST /execution-tasks/{id}/status`.

**UI**: `/ui/projects/{id}/execution` — «AI исполнение» (план/прогресс, objectives + tasks с
владельцами и статусами, blockers, AI-координация).

**CLI**: `make execution-create project_id=1 strategic_plan_id=5`,
`make execution-generate execution_plan_id=7`, `make execution-report execution_plan_id=7`.

## 9. Модель данных

- `ExecutionPlan` — план (project/strategic_plan_id/status/progress_percent/start_date/deadline/
  plan_metadata; `metadata` зарезервировано → `plan_metadata`, в API как `metadata`);
- `ExecutionObjective` — цель (execution_plan_id/kpi/priority/status/progress_percent/owner_user_id);
- `ExecutionTask` — задача (objective_id/priority/status/owner_user_id/deadline/progress_percent/
  task_metadata);
- `ExecutionDependency` — зависимость (task_id/depends_on_task_id[soft ref]/dependency_type/status;
  append-only).

Миграция: **`0060_ai_execution_coordinator`** (down_revision `0059_ai_business_planner`; id ≤ 32
символов). Конфиг: `execution_coordinator_enabled` (default true).
