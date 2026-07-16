# Botfleet AI Optimization Governance Engine (v0.8.2)

Слой управления портфелем поверх Autonomous Optimization. Где Autonomous Optimization **оценивает и
проверяет** улучшения, Governance **управляет портфелем**: заводит governance-записи, ведёт review и
approval flow, назначает владельцев, считает метрики портфеля и отслеживает impact.

```
Optimization Item → Governance Review → Approval → Ownership → Impact Tracking
```

Это **governance / управляющий** слой. Он управляет статусами, владельцами и impact, но НИКОГДА не
применяет улучшения, не запускает эксперименты и не меняет бизнес, KPI, CRM или бюджет.

## 1. Governance, назначения, impact, ревью

- `OptimizationGovernance` — запись портфеля (status/approval_status/priority/owner/review_notes;
  ссылка на `optimization_id`).
- `OptimizationOwnerAssignment` — история ответственности (owner/role/assigned_at/released_at).
- `OptimizationImpact` — отслеживание влияния (status/expected/actual/impact_score; ссылка на
  `experiment_id`).
- `GovernanceReview` — решение ревью (reviewer/decision/comment; append-only).

Термины: `GovernanceStatus` (identified · review · approved · rejected · active · completed ·
archived); `ApprovalStatus` (pending · approved · rejected); `ImpactStatus` (unknown · measuring ·
positive · neutral · negative); `Priority` (critical · high · medium · low).

## 2. Как работает governance

`run_governance_cycle` (advisory) заводит `OptimizationGovernance` по каждой оптимизации проекта
(идемпотентно, приоритет наследуется от оптимизации) и, для governance с завершённым экспериментом
без записи impact, авто-создаёт запись impact. Статус новой записи — `identified`, approval —
`pending`. Цикл **ничего не утверждает и не запускает**.

## 3. Как работает approval

`submit_review` создаёт `GovernanceReview` и переводит статус `identified → review` (комментарий
сохраняется в `review_notes`). `approve_optimization` меняет `approval_status: pending → approved`
(и `status → approved`); `reject_optimization` — в `rejected`. Оба меняют **только статусы** и лишь из
состояния `pending` (повторная обработка запрещена). **НЕ запускают** улучшение. Жизненный цикл
статусов идёт дальше без применения улучшения: назначение владельца одобренной записи → `active`,
измеренный impact активной записи → `completed`.

## 4. Как назначаются владельцы

`assign_owner` фиксирует владельца: закрывает активные назначения (`released_at`), создаёт новое
`OptimizationOwnerAssignment` и проставляет `governance.owner_user_id`. Владельцем можно назначить
**только участника аккаунта проекта** — проверка **FAIL CLOSED**: любой сбой самой проверки доступа →
отказ (назначение не проходит), а не пропуск.

## 5. Как считается portfolio impact

`calculate_portfolio_metrics` (DB-агрегаты `func.count`/`func.avg`, без пагинационного среза):
`total`, `approved`, `pending`, `active`, `completed`, `avg_impact_score`, `positive_impacts`.
`track_impact` выводит impact из результата эксперимента (read-only Optimization): статус по итогу
валидации (success → positive · failure → negative · inconclusive → neutral · завершён без результата
→ measuring · нет эксперимента → unknown); `impact_score` = Optimization Score оптимизации (для
positive), его половина (neutral) или 0 (negative). `explain_governance` объясняет, почему улучшение
прошло approval.

## 6. Безопасность (инварианты, покрыты тестами)

- Engine **НЕ** утверждает автоматически (analyze оставляет всё в `pending`), **НЕ** запускает
  эксперименты, **НЕ** применяет улучшения, **НЕ** меняет бизнес/стратегию/KPI/CRM/бюджет, **НЕ**
  выполняет задачи (весь сбор смежных слоёв — read-only в try/except: падение соседа не роняет цикл);
- назначение владельца — **только участнику аккаунта** (FAIL CLOSED);
- строго per-project (гарды `require_project_access` / `require_governance_access`); секретов нет;
  всё **бесплатно** (0 units: `USAGE_GOVERNANCE_ANALYSIS`, `USAGE_GOVERNANCE_REPORT`);
- каждое изменение (`governance.created`, `governance.review_created`, `governance.approved`,
  `governance.rejected`, `governance.owner_assigned`, `governance.impact_updated`) → **AuditLog**;
- `optimization_governance_enabled` (kill-switch, default true).

## 7. API / UI / CLI

**API** (project- / governance-guard):
- `POST /projects/{id}/optimization-governance`, `GET /projects/{id}/optimization-governance`;
- `GET /governance/{id}`, `POST /governance/{id}/review`, `POST /governance/{id}/approve`,
  `POST /governance/{id}/reject`, `POST /governance/{id}/owner`;
- `GET /projects/{id}/optimization-portfolio`.

**UI**: `/ui/projects/{id}/optimization-governance` — «Optimization Governance» (Portfolio, Review
Queue, Owners, Impact, History).

**CLI**: `make governance-analyze project_id=1`, `make governance-report project_id=1`.

## 8. Интеграции и модель данных

Интеграции (все read-only, try/except): **Autonomous Optimization** (OptimizationItem /
OptimizationExperiment / ExperimentResult — источник governance и impact),
**Continuous Improvement** (ImprovementItem / LearningEvent — контекст улучшения).

- `OptimizationGovernance` — (project/account/optimization_id/status/approval_status/priority/
  owner_user_id/review_notes);
- `OptimizationOwnerAssignment` — (governance_id/owner_user_id/role/assigned_at/released_at);
- `OptimizationImpact` — (governance_id/experiment_id/status/expected_impact/actual_impact/
  impact_score);
- `GovernanceReview` — (governance_id/reviewer_user_id/decision/comment; append-only).

Миграция: **`0064_ai_optimization_governance`** (down_revision `0063_ai_autonomous_optimization`).
Конфиг: `optimization_governance_enabled` (default true).
