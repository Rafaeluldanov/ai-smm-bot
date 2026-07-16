# Botfleet AI Continuous Improvement Engine (v0.8.0)

Слой обучения поверх всей цепочки. Где Performance Intelligence **измеряет** результат,
Continuous Improvement **учится на нём**: сохраняет опыт из истории решений и результатов,
создаёт события обучения, находит успешные и провальные паттерны, определяет причины провалов,
формирует backlog улучшений и объясняет владельцу выводы для следующего цикла изменений.

```
Performance Result → Experience Memory → Learning Event → Pattern Analysis → Improvement Backlog → Owner Review
```

Это **learning / аналитический** слой. Он учится и советует, но НИКОГДА не меняет бизнес,
стратегию, KPI, CRM или бюджет и не выполняет улучшения — их применяет только владелец.

## 1. Опыт, события, паттерны, улучшения

- `ExperienceMemory` — единица опыта (тип/источник/context/expected_result/actual_result/outcome/
  lessons/confidence).
- `LearningEvent` — событие обучения из опыта (success/failure/insight/…; append-only).
- `AIPattern` — найденный паттерн (success/failure/optimization; signals/confidence).
- `ImprovementItem` — элемент backlog улучшений (pattern_id/status/priority/expected_impact).

Термины: `ExperienceType` (decision · strategy · execution · forecast · performance);
`LearningEventType` (success · failure · deviation · improvement · insight);
`PatternType` (success_pattern · failure_pattern · optimization_pattern);
`ImprovementStatus` (identified · reviewed · accepted · rejected · completed);
`Priority` (critical · high · medium · low); `Outcome` (success · failure · neutral).

## 2. Как собирается опыт

`capture_experience` (только чтение смежных слоёв) собирает опыт из трёх источников:

- **Performance** — последний снимок эффективности: expected = target_state, actual = actual_state,
  outcome по статусу (healthy → success · critical → failure · иначе neutral), lessons = отклонения;
- **Execution** — последний план исполнения: outcome по прогрессу (≥80 % → success · <40 % →
  failure · иначе neutral), lessons = заблокированные задачи;
- **Decision** — последнее рекомендованное/принятое/применённое решение (context, outcome = neutral).

Каждый источник — в своём try/except: падение одного не роняет сбор. `analyze_outcome(expected,
actual)` — чистая функция: средняя доля достижения `min(2, actual/target)`; ≥0.9 success · <0.6
failure · иначе neutral.

## 3. Как создаются события обучения

`create_learning_event` превращает опыт в `LearningEvent` по карте outcome → тип события
(success → success · failure → failure · neutral → insight), сохраняя lessons в `impact`.

## 4. Как находятся паттерны

`detect_patterns` анализирует историю опыта:

- ≥2 success-опыта → **success_pattern** (уверенность = число успехов × 25, clamp 100);
- ≥1 failure-опыт → **failure_pattern** (signals = причины из `analyze_failure`; уверенность =
  число провалов × 30);
- сигналы оптимизации (блокеры исполнения / отклонения метрик) → **optimization_pattern**.

## 5. Как AI ищет причины провалов

`analyze_failure` (только чтение) собирает вероятные системные причины: исполнение (блокеры задач /
задачи без владельцев — Execution Coordinator), прогноз (низкая уверенность модели <40 —
Forecasting), стратегия (значимые high/critical-отклонения — Performance). Каждый источник в
try/except.

## 6. Как формируется backlog улучшений

`generate_improvements` создаёт `ImprovementItem` по не-success паттернам (успех закрепляем, отдельного
улучшения не нужно): по каждому сигналу (до 3) — совет `_improvement_for_signal` (блокеры → «снять
блокеры», нет владельцев → «назначить владельцев», прогноз → «улучшить данные», стратегия →
«пересмотреть стратегию») с приоритетом и ожидаемым эффектом. Статус нового элемента — `identified`.
`explain_learning` объясняет владельцу, что AI понял. Улучшения — **только предложения**.

## 7. Owner Review (approve / reject — только статус)

`approve_improvement` → status `accepted`, `reject_improvement` → status `rejected` (из
identified/reviewed; повторная обработка запрещена). Меняется **только статус** — улучшение НЕ
применяется, задачи/публикации/workflow не создаются.

## 8. Безопасность (инварианты, покрыты тестами)

- Engine **НЕ** применяет улучшения, **НЕ** меняет бизнес/стратегию/KPI/CRM/бюджет, **НЕ**
  выполняет задачи, **НЕ** запускает рекламу, **НЕ** публикует, **НЕ** ходит во внешние действия
  (весь сбор смежных слоёв — read-only, в try/except — падение любого слоя не роняет цикл;
  approve/reject меняют лишь статус);
- строго per-project (гарды `require_project_access` / `require_improvement_access`); секретов нет;
  всё **бесплатно** (0 units: `USAGE_LEARNING_ANALYSIS`, `USAGE_LEARNING_REPORT`);
- каждое изменение (`learning.experience_created`, `learning.event_created`,
  `learning.pattern_created`, `learning.improvement_created`, `learning.improvement_approved`,
  `learning.improvement_rejected`) → **AuditLog**;
- `continuous_improvement_enabled` (kill-switch, default true).

## 9. API / UI / CLI

**API** (project- / improvement-guard; learning namespaced под `/improvement`, чтобы не пересечься с
`/projects/{id}/learning/*` слоя AI Learning):
- `POST /projects/{id}/improvement/analyze`, `GET /projects/{id}/improvement/history`;
- `GET /projects/{id}/patterns`, `GET /projects/{id}/improvements`;
- `POST /improvements/{id}/approve`, `POST /improvements/{id}/reject`.

**UI**: `/ui/projects/{id}/improvement` — «AI улучшения» (AI Insights, успешные паттерны, причины
провалов, backlog улучшений с approve/reject, история обучения).

**CLI**: `make learning-analyze project_id=1`, `make learning-report project_id=1`.

## 10. Интеграции и модель данных

Интеграции (все read-only, try/except): **Performance Intelligence** (snapshot/deviations),
**Execution Coordinator** (plans/tasks/blockers), **Business Forecasting** (confidence),
**Decision Engine** (последнее решение).

- `ExperienceMemory` — опыт (project/account/experience_type/source_id/title/context/expected_result/
  actual_result/outcome/lessons/confidence_score);
- `LearningEvent` — событие (project/account/event_type/experience_id/title/description/impact;
  append-only);
- `AIPattern` — паттерн (project/account/pattern_type/title/description/signals/confidence_score);
- `ImprovementItem` — улучшение (project/account/pattern_id/status/priority/title/description/
  expected_impact).

Миграция: **`0062_ai_continuous_improvement`** (down_revision `0061_ai_performance_intelligence`).
Конфиг: `continuous_improvement_enabled` (default true).
