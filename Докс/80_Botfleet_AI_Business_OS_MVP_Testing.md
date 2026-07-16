# Botfleet AI Business OS MVP Testing Framework (v0.9.0)

E2E-фреймворк для тестирования всей AI Business Operating System. Это **НЕ** новый бизнес-слой: это
demo-окружение, scenario runner, E2E-валидация и отчётность, которые прогоняют существующую
AI-цепочку и фиксируют, что каждый слой работает.

```
Business Goal → Decision → Forecast → Plan → Execution → Performance → Learning → Optimization → Governance
```

## 1. Зачем нужен testing layer

AI Business OS собран из 10+ слоёв (Decision → … → Governance). Перед MVP-запуском нужно убедиться,
что весь конвейер проходит от начала до конца на реалистичных данных. Framework даёт: demo-компанию,
запускаемые сценарии, PASS/FAIL по каждому этапу и итоговый score — воспроизводимую product-валидацию
без реальных интеграций.

## 2. Demo Mode

Флаг `demo_mode` (config, default true). При `demo_mode=true` разрешено: создавать demo-данные,
запускать тестовые сценарии, формировать отчёты. **Запрещено в любом режиме** (и проверяется тестами):
реальные интеграции/пользователи/платежи/внешние API-действия; demo-сценарии не запускают workflow,
не меняют бизнес/CRM, не отправляют сообщений. При `demo_mode=false` demo-действия отклоняются
(`AIBusinessOSDemoError`).

## 3. Сценарии

- **growth** — рост: полный цикл под цель «выручка 5 млн → 10 млн за 12 мес».
- **recovery** — восстановление: «продажи упали на 20%» → найти проблему, предложить решение, план.
- **optimization** — оптимизация: «процессы медленны» → паттерн → Improvement → Optimization →
  Governance.

Каждый сценарий сидирует своё проблемное состояние (Performance snapshot + deviation) для
детерминированного прохода обучения и прогоняет **весь** конвейер. Термины: `ScenarioType`
(growth · recovery · optimization); `Status` (draft · running · completed · failed).

## 4. Как работает E2E pipeline

`run_scenario` создаёт **изолированный demo-проект** (slug `demo-<id>`), затем проходит 8 этапов —
каждый вызывает advisory-метод соответствующего слоя в try/except и фиксирует PASS/FAIL:

| Этап | Вызов (advisory) |
|------|------------------|
| decision | `AIDecisionEngineService.create_decision` |
| forecast | `AIBusinessForecastingService.create_forecast` |
| planner | goal → `generate_strategic_plan` → `approve_plan` |
| execution | `create_execution_plan(approved)` → `generate_execution` |
| performance | `AIPerformanceIntelligenceService.create_snapshot` |
| learning | сид проблемы → `run_learning_cycle` |
| optimization | `run_optimization_cycle` |
| governance | `run_governance_cycle` |

Падение любого этапа не роняет прогон (он записывается FAIL). Все вызванные слои — advisory: не
публикуют, не выполняют workflow, не меняют CRM/бюджет, не шлют сообщений.

## 5. Какие слои проверены

Проверяется вся цепочка: **Decision Engine · Business Forecasting · Business Planner · Execution
Coordinator · Performance Intelligence · Continuous Improvement (Learning) · Autonomous Optimization ·
Optimization Governance**. Score = `round((0.7·passed + 0.3·produced) / total · 100)`, где
`passed` — этапы без исключения, `produced` — этапы, реально давшие результат.

## 6. Отчёты

`AIBusinessOSReportService.generate_report` формирует «AI Business OS Test Report»: PASS/FAIL по
каждому из 8 этапов, `overall_score`, `verdict` (MVP-READY при всех PASS и score ≥ 90). Только чтение
сохранённого прогона — ничего не выполняет.

## 7. Ограничения / безопасность (инварианты, покрыты тестами)

- Работает только при `demo_mode=true`; НЕ создаёт реальных пользователей/CRM/платежей, НЕ запускает
  рекламу/workflow, НЕ публикует и не шлёт сообщений (проверено: прогон не создаёт `PostPublication`/
  `CrmSmmResource`/`BusinessWorkflow`/`PaymentInvoice`/`UsageEvent`);
- каждый прогон — на **отдельном** demo-проекте (изоляция); падение этапа не роняет прогон;
- строго per-account (доступ к demo-ресурсам — только участнику аккаунта); секретов нет; всё
  **бесплатно** (0 units: `USAGE_DEMO_SCENARIO`, `USAGE_DEMO_REPORT`);
- изменения (`demo.workspace_created`, `demo.scenario_started`, `demo.scenario_completed`,
  `demo.report_created`) → **AuditLog**.

## 8. API / UI / CLI

**API** (auth + доступ к аккаунту demo-ресурса):
- `POST /demo/workspace/create`, `POST /demo/scenario/{type}/run`, `GET /demo/scenarios`,
  `GET /demo/scenario/{id}/report`, `GET /demo/health`.

**UI**: `/ui/demo/business-os` — «AI Business OS Testing Center» (Demo Workspace, Scenario Launcher,
Pipeline PASS/FAIL, Result score, History).

**CLI**: `make demo-create account_id=1`, `make demo-run workspace_id=1 scenario=growth`,
`make demo-report scenario_id=1`.

## 9. Модель данных

- `DemoWorkspace` — demo-компания (account/name/company_name/industry/description);
- `DemoScenario` — прогон (workspace/scenario_type/status/input_data/result_data/score).

Миграция: **`0065_ai_business_os_mvp_testing`** (down_revision `0064_ai_optimization_governance`).
Конфиг: `demo_mode` (default true).
