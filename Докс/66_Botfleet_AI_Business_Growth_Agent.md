# Botfleet AI Business Growth Agent (v0.6.9)

Слой бизнес-аналитики верхнего уровня. Сводит воедино всё, что Botfleet уже знает —
контент, кампании, лиды, выручку, обучение — в **Growth Intelligence** и превращает это
в **Growth Recommendations**.

```
Content + Campaigns + Leads + Revenue + Learning
          ↓
   Growth Intelligence  (состояние, сильные/слабые стороны, возможности, риски, score)
          ↓
   Growth Recommendations  (Analyze → Recommend → Review → Apply)
```

Это **advisory**-слой: он оценивает и советует, но НИКОГДА не действует за клиента.

## 1. Зачем нужен growth-агент

Отдельные слои (обучение, стратегия, кампании, продажи) отвечают на узкие вопросы. Growth
Agent отвечает на бизнес-вопрос целиком: **как проекту расти?** Он видит картину сверху —
где деньги, где узкое место, что масштабировать — и предлагает приоритезированные шаги.

## 2. Какие данные используются (источники сигналов)

`_gather_signals` собирает per-project:
- **AI Sales Intelligence (v0.6.8)** — `total_revenue`, top-контент/кампании, best_platform,
  best_cta, лиды/сделки/won (конверсия);
- **Content Strategy (v0.6.6)** — `best_topics`, `weak_topics`, `best_formats`;
- **AI Learning (v0.6.5)** — `learning_score` (стабильность обучения), `content_efficiency`
  (средняя эффективность контента);
- **Campaign Manager (v0.6.7)** — эффективность кампаний (`campaign_revenue_score` из атрибуции);
- **Analytics** — охват/показы (для сигнала «трафик vs лиды»).

`GrowthSignalType`: revenue · conversion · content · campaign · audience · platform ·
efficiency · opportunity.

## 3. Как AI оценивает рост (growth_score)

`calculate_growth_score` → 0..100 из четырёх компонентов:

| Компонент | Вес | Источник |
|---|---|---|
| Revenue | 40% | `min(1, total_revenue / 100000)` |
| Conversion | 25% | `won / leads` (клампится ≤ 1) |
| Content efficiency | 20% | средняя эффективность контента (AI Learning) |
| Learning stability | 15% | `learning_score / 100` |

## 4. Как формируются рекомендации

`detect_growth_opportunities` ищет паттерны:
1. **Высокий трафик + мало лидов** → проблема конверсии/CTA (`conversion`);
2. **Выручка сконцентрирована на одной теме** → масштабировать её (`content`);
3. **Сильный канал с выручкой** → увеличить активность (`channel`);
4. **Успешная кампания** → повторить/усилить (`campaign`);
5. **Слабые темы** → пересмотреть контент (`content`).

`generate_recommendations` превращает возможности в `BusinessGrowthRecommendation`
(`GrowthRecommendationType`: content · campaign · channel · conversion · audience ·
product · process) с обоснованием, сигналами-источниками, ожидаемым эффектом и
уверенностью. Дедуп по (type, title). `explain_growth` объясняет клиенту, «почему AI
рекомендует это».

## 5. Как работает apply flow

Статусы (`GrowthRecommendationStatus`): **generated → reviewed → accepted → rejected →
applied**. Цикл **Analyze → Recommend → Review → Apply**:
1. **Review** — «Принять» (accept) / «Отклонить» (reject).
2. **Apply** — `apply_recommendation` срабатывает ТОЛЬКО при:
   - `status == accepted` И
   - `confirmation == "APPLY_GROWTH_ACTION"`.
   Применение меняет **только**:
   - **business-профиль роста** (`growth_targets` / `business_goal`), и/или
   - **черновик стратегии** (`ContentStrategyProfile` через ContentStrategist).

## 6. Безопасность (инварианты, покрыты тестами)

- growth-агент **НЕ** меняет CRM/продажи/бюджет, **НЕ** запускает рекламу и кампании;
- **НЕ** включает live и **НЕ** публикует; **НЕ** совершает внешних действий;
- `apply` невозможен без `accepted` + `APPLY_GROWTH_ACTION`; `apply` даёт `live_enabled=False`;
- `business_growth_auto_apply_enabled` по умолчанию `false` (только Review → Apply);
- каждое изменение (`growth.analyzed/recommendation_created/accepted/rejected/applied`)
  пишется в **AuditLog**;
- строго per-project (tenant isolation); секретов не хранит; всё **бесплатно** (0 units).

## 7. API / UI / CLI

API (под project-guard): `GET /projects/{id}/growth`, `POST …/analyze`,
`GET …/recommendations`, `POST …/recommendations/{id}/accept|reject`, `POST …/apply`,
`GET …/explanation`.

UI: `/ui/projects/{id}/growth` — «AI рост бизнеса» (Growth Score, что работает, где рост,
слабые места, риски, карточки рекомендаций с Принять/Отклонить/Применить).

CLI: `make growth-analyze project_id=1`, `make growth-report project_id=1`,
`make growth-apply project_id=1 rec_id=5`.

## 8. Модель данных

`BusinessGrowthProfile` (одна на проект: business_goal/growth_targets/current_state/
strengths/weaknesses/opportunities/risks/growth_score) + `BusinessGrowthRecommendation`
(Review → Apply). Миграция: **`0051_business_growth_agent`** (down_revision
`0050_ai_sales_intelligence`). Конфиг: `business_growth_enabled` (kill-switch, default
true), `business_growth_auto_apply_enabled` (default false).
