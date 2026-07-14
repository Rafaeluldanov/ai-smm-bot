# Botfleet Autonomous Content Strategist (v0.6.6)

Автономный AI-стратег контента: Botfleet сам решает **что / когда / для кого / какой
формат / какая цель**, но НИКОГДА не применяет это автоматически. Все стратегические
изменения проходят строгий цикл **Recommendation → Review → Apply** с подтверждением.

## 1. Отличие от AI-копирайтера

- **AI-копирайтер / генератор** (Этап 5, v0.6.5 LearningContext) — пишет *конкретный
  пост*: текст, CTA, хэштеги под выбранную тему.
- **AI Content Strategist (v0.6.6)** — решает *стратегию*: какие темы усилить, какие
  снизить, какие форматы делать чаще, с какой частотой публиковать, какие контентные
  столпы держать. Это уровень выше генерации: план, а не отдельный текст.

Стратег — это слой **рекомендаций**, а не исполнения. Он ничего не публикует и не
меняет активный календарь сам.

## 2. Как AI выбирает стратегию

`build_strategy_snapshot(project_id)` собирает единый снапшот из всех источников и
сохраняет агрегаты в `ContentStrategyProfile` (это память, НЕ применение):
- **бизнес-цель** — из `ContentStrategyProfile` или `ProjectAutopilotProfile.content_rules`;
- **AI Learning Profile (v0.6.5)** — сильные/слабые темы, форматы, лучшее время;
- **аналитика** — топ-темы/кластеры, winners/failures (`PostPerformanceLearningService`);
- **SEO** — ключевые слова, поисковый спрос, сезонность (`SeoStrategyAdapter`);
- **тренды** — трендовые направления (`TrendStrategyAdapter`, пока mock, без сети).

Снапшот → `{content_pillars, recommended_frequency, best_formats, best_topics,
weak_topics, target_audience, seo, trends, warnings}`.

## 3. Какие сигналы используются

`StrategySignalType`: business_goal · learning · analytics · seo · trend · seasonality ·
competitor · audience.

**Оценка темы** `score_topic(topic) → 0..100`:

```
score = learning(25) + analytics(25) + business(20) + seo(20) + trend(10)
```

- **learning** — тема в preferred_topics AI Learning → 1.0; в avoided → 0; иначе 0.4;
- **analytics** — performance_score темы из аналитики (0..1);
- **business** — совпадение темы с ключевыми словами бизнес-цели;
- **seo** — поисковый спрос кластера темы (+ бонус за совпадение с реальными запросами);
- **trend** — совпадение с трендовыми направлениями.

## 4. Как работает recommendation flow

`generate_recommendations` создаёт `ContentStrategyRecommendation` (тип из
`StrategyRecommendationType`: topic · format · schedule · platform · media · cta ·
campaign) со `status`, `priority`, `confidence_score`, `reasoning[]`, `source_signals[]`,
`expected_impact` и `apply_payload`. Примеры:

- «Больше контента по теме "Кейсы производства"» (confidence 87, причины: кейсы дали
  сильные сигналы + AI Learning рекомендует);
- «Меньше рекламных постов»; «Делать больше форматов: case, expert»;
- «Частота публикаций: 3_week»; «Мини-кампания: видео-обзор производства».

Статусы (`RecommendationStatus`): **generated → reviewed → accepted → rejected → applied**.
Повторный `generate` дедуплицирует по (type, title) среди открытых рекомендаций.

## 5. Как клиент подтверждает изменения

Цикл **Recommendation → Review → Apply**:

1. **Review** — клиент видит карточки рекомендаций (что/почему/уверенность) и жмёт
   «Принять» (`accept` → status=accepted) или «Отклонить» (`reject` → status=rejected).
2. **Apply** — `apply_recommendation` срабатывает ТОЛЬКО когда:
   - `status == accepted` И
   - `confirmation == "APPLY_STRATEGY"`.
   Применение меняет **только**:
   - `content_rules` (через `AutopilotService.configure_content_rules`), и/или
   - **ЧЕРНОВИК** календаря (`AutopilotCalendarAssistantService.create_calendar_plan`,
     status=draft) — не активный календарь.

`calendar_strategy_preview` показывает «если применить стратегию» — предпросмотр
календаря **без записи**.

## 6. Безопасность (инварианты, покрыты тестами)

- стратегия **НЕ включает** live и **НЕ меняет** глобальные `*_LIVE_PUBLISHING_ENABLED`;
- стратегия **НЕ публикует** и **НЕ вызывает** внешние API (trend-адаптер — mock);
- **НЕ меняет активный календарь** и **НЕ удаляет темы** автоматически;
- `apply` невозможен без `accepted` + `APPLY_STRATEGY`; `apply` даёт `live_enabled=False`;
- `content_strategy_auto_apply_enabled` по умолчанию `false` (только рекомендации);
- каждое изменение (generated/accepted/rejected/applied) пишется в **AuditLog**
  (`strategy.*`);
- строго per-project (tenant isolation); секретов не хранит; всё **бесплатно** (0 units).

## 7. API / UI / CLI

API (под project-guard): `GET /projects/{id}/strategy`, `POST …/analyze`,
`GET …/recommendations`, `POST …/recommendations/{id}/accept`, `…/reject`,
`POST …/apply`, `GET …/explanation`.

UI: `/ui/projects/{id}/strategy` — «AI стратегия контента» (что AI понял, контентные
столпы, план месяца, карточки рекомендаций с кнопками Принять/Отклонить/Применить).

CLI: `make strategy-analyze|strategy-recommend|strategy-apply project_id=1`.

## 8. Архитектура

```
Бизнес-цель ─┐
AI Learning  ─┤
Аналитика    ─┼→ build_strategy_snapshot → ContentStrategyProfile (память)
SEO-адаптер  ─┤            │
Trend-адаптер─┘            ▼
                   generate_recommendations → ContentStrategyRecommendation[]
                            │  (Review: accept / reject)
                            ▼
                   apply_recommendation (accepted + APPLY_STRATEGY)
                            │
             ┌──────────────┴───────────────┐
             ▼                              ▼
     content_rules (configure)      calendar DRAFT (create, status=draft)
             └──────────── НЕ live, НЕ публикация ─────────┘
```

Модели: `ContentStrategyProfile` (одна на проект) + `ContentStrategyRecommendation`.
Миграция: **`0048_content_strategy`** (down_revision `0047_ai_learning_loop`).
Конфиг: `content_strategy_enabled` (kill-switch, default true),
`content_strategy_auto_apply_enabled` (default false).
