# Botfleet AI Business OS MVP Launch — Pilot (v0.9.1)

Подготовка AI Business OS к первому реальному бизнес-пилоту. Это **НЕ** новый AI-слой: это
Pilot-окружение (sandbox реальной компании), Business Profile, CEO Dashboard и Pilot Report. Всё —
**advisory only**: AI анализирует и советует, но НЕ меняет бизнес, НЕ выполняет workflow, НЕ шлёт
сообщений, НЕ трогает CRM/платежи, НЕ ходит во внешние API.

```
Pilot Workspace → Business Profile → Pilot Analysis (Decision→…→Governance) → CEO Dashboard → Pilot Report
```

## 1. Pilot Mode

Флаг `pilot_mode` (config, default true). При `pilot_mode=true` разрешено: создавать pilot workspace,
создавать бизнес-профиль, запускать pilot-анализ, формировать dashboard, создавать отчёт. При
`pilot_mode=false` pilot-действия запрещены (`PilotModeDisabledError` → HTTP **403**). Все методы всех
pilot-сервисов начинают с `_require_pilot_mode()`.

## 2. Sandbox (изоляция)

Каждый pilot-прогон идёт на **отдельном изолированном pilot-проекте** с детерминированным slug
`pilot-ws-<workspace_id>` (создаётся при первом `run`, переиспользуется при повторных). Это отделяет
данные пилота от реальных проектов и позволяет прогонять AI-цепочку без риска для боевых данных.

## 3. Business Profile

`PilotBusinessProfile` описывает реальную компанию: продукты, услуги, команда, каналы продаж,
описание, текущая/целевая выручка, KPI. `create_business_profile` создаёт профиль; `get_profile`
возвращает последний. Профиль — контекст для health/dashboard/report и основа для состояния бизнеса.

Пример: TEEON Pilot · apparel · выручка 5 000 000 → цель 10 000 000.

## 4. Pilot Scenario

`run_growth_pilot` **переиспользует E2E-конвейер v0.9.0**: прогоняет всю цепочку
Decision → Forecast → Planner → Execution → Performance → Learning → Optimization → Governance на
pilot-проекте (каждый слой — advisory-метод в try/except, PASS/FAIL по этапу, score). Дополнительно
фиксирует состояние бизнеса из профиля (Performance snapshot по разрыву current/target revenue) для
health. **Запрещено:** execute-методы, workflow-conversion, внешние действия — используются только
advisory create/analyze-методы.

## 5. CEO Dashboard

`AICEODashboardService.generate_dashboard` собирает «AI Business Command Center» — ТОЛЬКО чтение уже
собранных данных (Performance / Operations / Forecasting через pilot health):
`{business_score, current_state, risks, opportunities, today_actions, forecast}`. `get_business_health`
считает score как среднее Performance/Operations health-score, риски — из high/critical отклонений и
открытых операционных рисков, возможности — из рекомендаций и прогноза.

## 6. Pilot Report

`AIBusinessPilotReportService.generate_pilot_report` формирует «AI Business Pilot Report»: компания,
цель (current→target revenue), состояние бизнеса, Performance Score, риски, возможности,
AI-рекомендации, прогноз, следующие шаги. Все шаги — advisory (применяет владелец вручную).

## 7. Security (инварианты, покрыты тестами)

- Работает только при `pilot_mode=true` (иначе 403); всё **advisory/read-only**: прогон НЕ создаёт
  `PostPublication` / `CrmSmmResource` / `BusinessWorkflow` / `PaymentInvoice` / `UsageEvent`
  (проверено тестом); НЕ выполняет workflow, НЕ шлёт сообщений, НЕ ходит во внешние API;
- создание воркспейса — ТОЛЬКО участнику аккаунта (**FAIL CLOSED**: сбой проверки → отказ);
- строго per-account (tenant isolation на всех роутах; workspace создаётся только с `account_id`);
  секретов нет; всё **бесплатно** (0 units: `USAGE_PILOT_ANALYSIS`, `USAGE_PILOT_REPORT`);
- изменения (`pilot.workspace_created` / `profile_created` / `scenario_started` /
  `dashboard_generated` / `report_created`) → **AuditLog**.

## 8. API / UI / CLI

**API** (auth + tenant + pilot_mode):
- `POST /pilot/workspaces`, `GET /pilot/workspaces`, `POST /pilot/workspaces/{id}/profile`,
  `GET /pilot/workspaces/{id}/health`, `POST /pilot/workspaces/{id}/run`,
  `GET /pilot/workspaces/{id}/dashboard`, `GET /pilot/workspaces/{id}/report`.

**UI**: `/ui/ceo/dashboard` — «AI Business Command Center» (Business Health, Current Situation, Risks,
Opportunities, AI Actions Today, Forecast).

**CLI**: `make pilot-create account_id=1`, `make pilot-run workspace_id=1`,
`make pilot-report workspace_id=1`.

## 9. Модель данных

- `PilotWorkspace` — (account/company_name/industry/status[draft/active/paused/completed]/created_by);
- `PilotBusinessProfile` — (workspace/products/services/team/sales_channels/business_description/
  current_revenue/target_revenue/kpi).

Миграция: **`0066_ai_business_os_pilot`** (down_revision `0065_ai_business_os_mvp_testing`).
Конфиг: `pilot_mode` (default true).

## 10. Готовность к v1.0.0

v0.9.1 завершает MVP launch preparation: реальный пилот запускается безопасно (advisory, изоляция,
tenant, pilot_mode kill-switch). Для боевого v1.0.0 останется: включить `pilot_mode=false` вне пилотов
в проде, добавить housekeeping pilot-проектов (`pilot-ws-*`), и — как отдельный слой — переход от
advisory-рекомендаций к контролируемому исполнению под подтверждение владельца.
