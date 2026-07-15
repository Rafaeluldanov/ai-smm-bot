# Botfleet Autonomous Business OS — AI Executive Layer (v0.7.0)

Верхний слой управления над всем, что уже умеет Botfleet. Это **не новый маркетинговый
модуль**, а «AI директор бизнеса», который сводит рост, продажи и контент в один
исполнительный контур:

```
Business Goal
     ↓
AI Executive Analysis   (состояние бизнеса: health, growth, revenue, content, sales, риски)
     ↓
Growth Priorities       (приоритизированные точки роста)
     ↓
Business Actions → Marketing Actions → Sales Actions
     ↓
Learning Feedback
```

Это **advisory + planning** слой. Поток: **Analyze → Recommend → Approve → Apply**. Он
анализирует и планирует, но НИКОГДА не действует за владельца без явного подтверждения.

## 1. Зачем нужен Executive Layer

Отдельные слои Botfleet отвечают на узкие вопросы: обучение — «что заходит», стратегия —
«о чём писать», кампании — «как продвигать», продажи — «что приносит деньги», growth-агент
— «где рост». Executive Layer отвечает на вопрос владельца целиком: **куда вести бизнес и
что делать в первую очередь?** Он ставит бизнес-цель, оценивает общее состояние и
превращает возможности роста в конкретные, приоритизированные бизнес-действия.

## 2. Термины

- `BusinessObjectiveType`: `revenue_growth` · `lead_growth` · `brand_awareness` ·
  `efficiency` · `retention` · `expansion`.
- `ObjectiveStatus`: `draft` · `active` · `completed` · `paused`.
- `PriorityType`: `growth` · `revenue` · `conversion` · `content` · `sales` · `efficiency`.
- `ActionStatus`: `generated` → `accepted` / `rejected` → `applied`.

## 3. Источники сигналов

`AIExecutiveService.analyze_business_state` переиспользует нижние слои (без дублирования логики):
- **Business Growth Agent (v0.6.9)** — `analyze_business`: growth_score, состояние
  (выручка, лиды, конверсия, best_platform, content_efficiency), сильные/слабые стороны,
  **возможности** и риски;
- **AI Sales Intelligence (v0.6.8)** — выручка/лиды/конверсия (внутри growth-сигналов);
- **Content Strategy (v0.6.6)** — draft-стратегия (используется при apply).

Из этого выводится **business_health** = `0.6 × growth_score + 0.4 × revenue_health`, где
`revenue_health = min(100, total_revenue / 1000)`.

## 4. Приоритизация действий

`prioritize_actions` / `_priority_score` считает приоритет `0..100`:

```
priority = impact × confidence × urgency × 100
impact     = 0.5 × (confidence/100) + 0.5 × type_weight
confidence = opportunity.confidence / 100
urgency    = 0.7   (умеренная; без дедлайна цели)
```

`type_weight`: revenue/conversion 1.0 · sales 0.9 · content/growth 0.8 · channel/campaign
0.7 · efficiency 0.6. Действия в списке и в плане отсортированы по убыванию приоритета.

## 5. Как формируется план и действия

`create_executive_plan`:
1. `analyze_business_state` — собирает состояние (и сохраняет профиль роста нижнего слоя);
2. `AIExecutivePlan` — исполнительное резюме, `current_state`, приоритеты, риски,
   возможности, ожидаемые результаты, уверенность;
3. `generate_actions` — из каждой возможности роста создаётся `BusinessAction`
   (`action_type`, приоритет, обоснование, `source_modules`, `apply_payload`).
   **Дедуп** по `(action_type, title)` среди всех действий проекта (любой статус) — чтобы
   применённые/отклонённые действия не появлялись заново.

`explain_plan` объясняет владельцу, почему AI выбрал именно эти приоритеты.

## 6. Apply flow — что можно и чего нельзя

Статусы действия: **generated → accepted / rejected → applied**. Цикл **Analyze →
Recommend → Approve → Apply**:
1. **Approve** — «Принять» (accept) / «Отклонить» (reject).
2. **Apply** — `apply_action` срабатывает ТОЛЬКО при:
   - `status == accepted` И
   - `confirmation == "APPLY_BUSINESS_ACTION"`.

`apply` меняет **только**:
- **draft-стратегию** (`ContentStrategyProfile` через ContentStrategist), и/или
- **draft-кампанию** (`AICampaign` в статусе `draft` через Campaign Manager).

`apply` **НЕ** делает: запуск рекламы, публикацию, изменение live-флагов, изменение CRM,
изменение денег/бюджета. Ответ всегда содержит `live_enabled=False`.

## 7. Безопасность (инварианты, покрыты тестами)

- Executive Layer **НЕ** меняет бизнес/CRM/бюджет автоматически, **НЕ** запускает рекламу,
  **НЕ** публикует, **НЕ** включает live, **НЕ** пишет продажи/выручку;
- `apply` невозможен без `accepted` + `APPLY_BUSINESS_ACTION`; всегда `live_enabled=False`;
- `business_os_auto_apply_enabled` по умолчанию `false` (только Approve → Apply);
- каждое изменение (`business_os.analyzed/plan_created/action_created/accepted/rejected/
  applied`) пишется в **AuditLog**;
- строго per-project (tenant isolation, в т. ч. роуты `/actions/{id}` через
  `require_action_access`); секретов не хранит; всё **бесплатно** (0 units).

## 8. API / UI / CLI

**API** (project-guard или action-guard):
- `POST /projects/{id}/objectives`, `GET /projects/{id}/objectives`;
- `POST /projects/{id}/executive/analyze` (строит план + действия);
- `GET /projects/{id}/executive/plan`, `GET /projects/{id}/executive/actions`,
  `GET /projects/{id}/executive/explanation`;
- `POST /actions/{id}/accept|reject|apply`.

**UI**: `/ui/projects/{id}/executive` — «AI директор бизнеса» (health/growth/уверенность,
цель бизнеса, приоритеты/возможности/риски/«почему так», карточки действий с
Принять/Отклонить/Применить).

**CLI**: `make business-os-analyze project_id=1`,
`make business-os-plan project_id=1 [objective_id=3]`,
`make business-os-apply action_id=5`.

## 9. Модель данных

- `BusinessObjective` — бизнес-цель (type/title/target/current/unit/deadline/status);
- `AIExecutivePlan` — исполнительный план (executive_summary/current_state/priority_actions/
  risks/opportunities/expected_outcomes/confidence_score);
- `BusinessAction` — бизнес-действие (action_type/priority/status/reasoning/expected_impact/
  source_modules/apply_payload/reviewed_at/applied_at).

Миграция: **`0052_autonomous_business_os`** (down_revision `0051_business_growth_agent`).
Конфиг: `business_os_enabled` (kill-switch, default true), `business_os_auto_apply_enabled`
(default false).
