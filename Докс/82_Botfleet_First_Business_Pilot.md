# Botfleet First Business Pilot (v1.0.0)

Первый настоящий бизнес-пилот AI Business OS. Это **НЕ** новый AI-слой: это онбординг реальной
компании (workspace → бизнес-профиль → цели → KPI), AI Business Intelligence Report, CEO Daily Brief
и feedback loop. AI остаётся **advisory only**: только анализирует, прогнозирует, рекомендует, формирует
планы. AI **НЕ** выполняет рекомендаций, **НЕ** меняет бизнес/CRM/финансы, **НЕ** запускает рекламу,
**НЕ** публикует, **НЕ** шлёт сообщений, **НЕ** совершает внешних действий.

```
Onboarding (Workspace → Profile → Goals → KPIs)
        → Business Context (SWOT) → Intelligence Report
        → CEO Daily Brief → Feedback Loop (accept/reject/modify — только фиксация)
```

## 1. Онбординг компании

`AIPilotOnboardingService.create_company_pilot()` заводит пилот компании одним шагом:
`PilotWorkspace → PilotBusinessProfile → PilotGoal(s) → PilotKPI(s)`. Проверки: `pilot_mode` включён;
аккаунт существует; пользователь — участник аккаунта (**FAIL CLOSED**). Переиспользует
`AIBusinessPilotService` для воркспейса (с member-check) и профиля, затем создаёт цели/KPI. Без
явных параметров используется демо-пилот TEEON (выручка 5 000 000 → 10 000 000, цель роста, 2 KPI).

## 2. Бизнес-цели (PilotGoal)

`PilotGoal` — цель компании: `title`, `description`, `current_value`/`target_value`, `unit`,
`deadline`, `priority` (critical/high/medium/low), `status` (draft/active/completed/cancelled).
Хранится per-workspace. `create_goal` доступен и как часть онбординга, и отдельным вызовом/роутом.

## 3. KPI (PilotKPI)

`PilotKPI` — метрика: `name`, `current_value`/`target_value`, `unit`, `frequency`
(daily/weekly/monthly/quarterly), `status` (active/paused/archived). Хранится per-workspace.

## 4. Business Context (SWOT)

`AIBusinessContextService.analyze_company_context()` — ТОЛЬКО аналитика уже собранных данных.
Собирает профиль/цели/KPI + `get_business_health` (Performance/Operations/Forecasting, read-only) и
выдаёт SWOT: `strengths` (≥2 продуктов / ≥2 каналов / есть выручка), `weaknesses` (≤1 канал / разрыв
до цели / KPI ниже цели), `opportunities` (рост выручки к цели + health-возможности), `risks`
(health-риски + недостигнутые цели). Ничего не выполняет и бизнес не меняет.

## 5. AI Business Intelligence Report

`AIPilotIntelligenceReportService.generate_intelligence_report()` компонует контекст (SWOT) +
health + профиль в «AI Business Intelligence Report»: компания (name/industry/current→target
revenue), текущее состояние, сильные/слабые стороны, риски, возможности, AI-рекомендации. Все
рекомендации — advisory: применяет владелец вручную, бизнес не меняется.

## 6. CEO Daily Brief

`AICEODailyBriefService.generate_daily_brief()` — ежедневная сводка владельца (read-only):
`{greeting "Доброе утро.", company_name, health_score, main_event, risks, opportunities,
today_actions[:3], forecast}`. `main_event` — топ-риск или «Бизнес стабилен». `forecast` берётся из
последнего Business Forecast pilot-проекта через **tenant-safe** `resolve_pilot_project` (при чужом
slug — `available:false`, без cross-tenant чтения).

## 7. Feedback Loop

`AIPilotFeedbackService` фиксирует решения владельца по AI-рекомендациям: `accept_recommendation`,
`reject_recommendation`, `submit_feedback(decision ∈ {accepted, rejected, modified})`,
`record_result`. `PilotFeedback` — append-only (`decision`, `recommendation_id` soft-ref, `comment`,
`result`, `created_at`). **Важно:** feedback ТОЛЬКО сохраняется — НЕ выполняет рекомендацию, НЕ меняет
бизнес, НЕ трогает KPI/цели/профиль (проверено тестом `test_feedback_does_not_mutate_business`).

## 8. Security (инварианты, покрыты тестами)

- Работает только при `pilot_mode=true` (иначе `PilotModeDisabledError` → HTTP **403**); всё
  **advisory/read-only**: онбординг+intelligence+brief+feedback НЕ создают `PostPublication` /
  `CrmSmmResource` / `BusinessWorkflow` / `PaymentInvoice` / `UsageEvent` (проверено тестом);
- онбординг — ТОЛЬКО участнику аккаунта (**FAIL CLOSED**); все роуты — auth + tenant (доступ к
  воркспейсу чужого аккаунта → 403/404); онбординг требует `account_id`;
- секретов в ответах нет; всё **бесплатно** (0 units: `USAGE_PILOT_INTELLIGENCE`, `USAGE_DAILY_BRIEF`,
  `USAGE_FEEDBACK`);
- изменения (`pilot.goal_created` / `pilot.kpi_created` / `pilot.intelligence_generated` /
  `pilot.daily_brief_generated` / `pilot.feedback_created`) → **AuditLog**.

## 9. API / UI / CLI

**API** (auth + tenant + `pilot_mode`):
- `POST /pilot/onboarding` — онбординг компании;
- `POST /pilot/{workspace_id}/goals`, `POST /pilot/{workspace_id}/kpis`;
- `GET /pilot/{workspace_id}/intelligence`, `GET /pilot/{workspace_id}/daily-brief`;
- `POST /pilot/{workspace_id}/feedback`.

Не пересекается с `/pilot/workspaces/*` (v0.9.1) — разная глубина/сегменты.

**UI**: `/ui/ceo/dashboard` — добавлен блок «🌅 AI Daily Brief» (greeting, Health, главное событие,
риски, возможности, действия на сегодня, прогноз).

**CLI**: `make pilot-onboarding account_id=1 [company_name=… user_id=…]`,
`make pilot-brief workspace_id=1 [user_id=…]`,
`make pilot-feedback workspace_id=1 decision=accepted [comment=… result=… recommendation_id=… user_id=…]`.

## 10. Модель данных

- `PilotGoal` — (workspace/title/description/current_value/target_value/unit/deadline/priority/status),
  индекс `ix_pilot_goals_workspace_status`;
- `PilotKPI` — (workspace/name/current_value/target_value/unit/frequency/status),
  индекс `ix_pilot_kpis_workspace_status`;
- `PilotFeedback` — append-only (workspace/recommendation_id/decision/comment/result/created_at).

Миграция: **`0067_ai_business_pilot_release`** (down_revision `0066_ai_business_os_pilot`).
Конфиг: `pilot_mode` (default true).

## 11. Итог v1.0.0

v1.0.0 запускает первый реальный бизнес-пилот безопасно: онбординг реальной компании, цели, KPI,
ежедневный CEO Daily Brief и feedback loop — при этом AI строго advisory (анализ/прогноз/рекомендации),
с изоляцией по аккаунту, kill-switch `pilot_mode` и полным аудитом. Переход от advisory к
контролируемому исполнению (под явное подтверждение владельца) — предмет следующих версий.
