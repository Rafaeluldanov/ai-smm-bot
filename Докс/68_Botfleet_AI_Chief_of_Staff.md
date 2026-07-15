# Botfleet AI Chief of Staff — Executive Assistant Layer (v0.7.1)

Персональный AI-ассистент владельца бизнеса поверх всего, что уже умеет Botfleet. Он не
принимает решения за владельца — он **готовит их**: анализирует бизнес, приносит понятный
брифинг, предлагает приоритетные задачи и запоминает решения владельца, чтобы будущие
AI-рекомендации учитывали его стиль.

```
Analyze  →  Briefing  →  Recommendation  →  Owner Approval  →  Task
```

Это **advisory + assistant** слой. Он советует и помнит, но НИКОГДА не действует за владельца.

## 1. Роль AI помощника

Executive Layer (v0.7.0) отвечает на вопрос «что делать бизнесу». Chief of Staff — это
персональный ассистент, который каждый день превращает это в короткий разговор с
владельцем: «вот что изменилось, вот риски, вот возможности, вот 3 задачи на сегодня». Он
также запоминает предпочтения владельца («не использовать агрессивные продажи», «фокус на
кейсах», «Telegram — главный канал») и подмешивает их контекстом во все будущие
рекомендации.

## 2. Термины

- `BriefingType`: `daily` · `weekly` · `monthly`.
- `BriefingStatus`: `generated` · `viewed` · `archived`.
- `TaskPriority`: `critical` · `high` · `medium` · `low`.
- `TaskStatus`: `suggested` → `accepted` / `rejected` → `completed`.
- `DecisionType`: `preference` · `strategy` · `restriction` · `approval`.

## 3. Daily briefing

`generate_daily_briefing` собирает свежий исполнительный план (reuse
`AIExecutiveService.create_executive_plan`, который сам агрегирует Growth Agent, Sales
Intelligence, Content Strategy, Analytics) и формирует `ExecutiveBriefing`:
- **summary** — главная точка роста (из executive-плана, + пометка об ограничениях владельца);
- **key_changes** — что изменилось со вчерашнего брифинга (смена главного канала, рост/падение
  Growth Score и выручки); при первом запуске — базовые наблюдения;
- **risks** — риски роста + «падает конверсия» при сравнении с прошлым брифингом;
- **opportunities** — точки роста из плана;
- **recommended_actions** — приоритетные действия;
- **business_state** — снапшот (health/growth/выручка/конверсия/канал/лиды) **+ owner_context**
  (активные решения владельца) — снапшот служит базой для сравнения на следующий день.

## 4. Weekly review

`generate_weekly_review` дополнительно сравнивает **последние 7 дней против предыдущих 7
дней** по лидам/выручке (`AILeadEvent`) и охвату (`PostAnalyticsSnapshot`): `key_changes`
показывают динамику (±%), `risks` — если выручка или поток лидов за неделю снизились.

## 5. Задачи владельца

`create_tasks_from_briefing` превращает приоритетные действия плана в задачи владельца.
Приоритет задачи — из формулы **impact × confidence** (score 0..100 из executive-слоя),
маппится в бакет: `≥70 critical · ≥45 high · ≥25 medium · else low`. Дедуп по
`(task_type, title)` среди всех статусов — завершённые/отклонённые задачи не появляются заново.

Жизненный цикл: **suggested → accepted / rejected → completed**.
- `accept_task` — только меняет статус (`accepted`), фиксирует `accepted_by_user_id`. **НЕ
  выполняет действие.**
- `complete_task` — только фиксирует `completed` + `completed_at`. **Внешних действий нет.**
- `reject_task` — `rejected`.

## 6. Decision memory

`save_decision_memory` запоминает решение владельца (одна активная запись на `key` —
повторное сохранение обновляет её). `build_decision_context` собирает активные решения в
структуру `{preferences, strategies, restrictions, approvals, by_key}`, а
`apply_decision_memory` готовит этот контекст для AI Learning / Content Strategy / Campaign
Manager. Память лишь **ДОБАВЛЯЕТ контекст** (и попадает в `business_state.owner_context`
каждого брифинга) — она **НЕ меняет** другие слои напрямую. `disable_decision` деактивирует
запись (`active=False`), не удаляя историю.

## 7. Безопасность (инварианты, покрыты тестами)

- ассистент **НЕ** выполняет задачи автоматически (accept/complete — только статус);
- **НЕ** меняет бизнес/CRM/бюджет/продажи, **НЕ** запускает рекламу, **НЕ** публикует,
  **НЕ** включает live, **НЕ** совершает внешних действий;
- decision memory лишь добавляет контекст рекомендациям, ничего не меняя напрямую;
- строго per-project (tenant isolation, в т. ч. роуты `/tasks/{id}` и `/decisions/{id}` через
  `require_task_access` / `require_decision_access`); секретов нет; всё **бесплатно** (0 units);
- каждое изменение (`chief.briefing_generated/task_created/task_accepted/task_rejected/
  task_completed/memory_created/memory_deleted`) пишется в **AuditLog**;
- `chief_of_staff_enabled` — kill-switch (default true).

## 8. API / UI / CLI

**API** (project-guard или task/decision-guard):
- `GET /projects/{id}/briefing`, `POST /projects/{id}/briefing/generate`,
  `POST /projects/{id}/briefing/weekly`;
- `GET /projects/{id}/tasks`, `POST /tasks/{id}/accept|reject|complete`;
- `POST /projects/{id}/decisions`, `GET /projects/{id}/decisions`, `DELETE /decisions/{id}`.

**UI**: `/ui/projects/{id}/chief-of-staff` — «AI помощник руководителя» (сегодня/риски/
возможности, карточки задач с Принять/Отклонить/Завершить, память решений).

**CLI**: `make chief-briefing project_id=1 [weekly=1]`,
`make chief-tasks project_id=1 [task_id=5 action=accept]`,
`make chief-memory project_id=1 [key=sales_style value=soft decision_type=restriction]`.

## 9. Модель данных

- `ExecutiveBriefing` — брифинг (type/status/summary/business_state/key_changes/risks/
  opportunities/recommended_actions/confidence_score/generated_at/viewed_at);
- `AIBusinessTask` — задача владельца (task_type/priority/priority_score/status/reasoning/
  expected_impact/source_modules/accepted_by_user_id/completed_at; briefing_id nullable);
- `BusinessDecisionMemory` — решение владельца (decision_type/key/value/reason/active).

Миграция: **`0053_ai_chief_of_staff`** (down_revision `0052_autonomous_business_os`).
Конфиг: `chief_of_staff_enabled` (kill-switch, default true).
