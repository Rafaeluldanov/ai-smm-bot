# Botfleet AI Sales & Lead Intelligence (v0.6.8)

Слой, который связывает **контент и деньги**. Botfleet понимает не только просмотры,
лайки и комментарии, а бизнес-результат: **какие публикации и кампании создают лиды и
выручку**. Главный принцип: **Content → Lead → Revenue Attribution**.

Это **аналитический** слой: собирает сигналы → считает атрибуцию → строит рекомендации.
Он ничего не продаёт, не рассылает и не меняет CRM.

## 1. Content Revenue Attribution

Каждый бизнес-сигнал фиксируется как `AILeadEvent` (тип `RevenueSignalType`):
`lead_created` · `deal_created` · `deal_won` · `revenue_added`, со ссылкой на пост/
кампанию/площадку, статусом лида (`LeadStatus`: new/contacted/qualified/converted/lost)
и источником (`LeadSourceType`: post/campaign/platform/referral/manual/crm).

`calculate_attribution` группирует события в **путь лида** (по `event_metadata.lead_ref`,
иначе каждое событие — свой путь), берёт выручку пути и распределяет её по постам-
касаниям по одной из моделей (`AttributionModel`) в `ContentRevenueAttribution`:

- **first_touch** — вся выручка первому касанию (какой пост привёл лида);
- **last_touch** — последнему касанию (какой пост закрыл сделку) — модель по умолчанию;
- **multi_touch** — поровну между всеми касаниями пути.

Пример пути L1: пост A (lead_created) → пост B (deal_won 60 000):
- first_touch → A = 60 000; last_touch → B = 60 000; multi_touch → A = 30 000, B = 30 000.

## 2. Как AI понимает продажи

`analyze_content_revenue` (по last_touch, без записи) считает, что приносит деньги:
`{top_content, top_campaigns, best_cta, best_platform, revenue_sources, total_revenue}`.
`build_sales_profile` собирает `SalesIntelligenceProfile`:
- `best_lead_topics` — темы постов с выручкой;
- `best_campaigns` — кампании с выручкой (+ `campaign_revenue_score` 0..100);
- `best_cta` — CTA постов, которые продают;
- `best_platforms` — площадки с выручкой;
- `conversion_patterns` — лиды/сделки/won, `conversion_rate`, `click_signals` (из аналитики);
- `revenue_insights` — total_revenue, revenue_per_lead, revenue_sources, campaign_scores,
  `topics_liked_and_selling`.

## 3. Как связаны посты и деньги

Событие лида несёт `post_id`/`campaign_id`/`platform_key` и `value`. Пути лидов
восстанавливаются по `lead_ref`, атрибуция раскладывает выручку на конкретные посты и
кампании. Так каждая публикация получает измеримый вклад в выручку, а не только охваты.

## 4. Интеграции

- **AI Learning (v0.6.5)** — «что нравится аудитории» × «что продаёт»: пересечение
  `preferred_topics` (Learning) и тем с выручкой → `revenue_insights.topics_liked_and_selling`.
- **Campaign Manager (v0.6.7)** — атрибуция на кампании + `campaign_revenue_score`.
- **Analytics** — `PostAnalyticsSnapshot.clicks` как сигнал конверсии (clicks_per_lead).
- **CRM Adapter** — `sales_crm_adapter.py` пока только интерфейс `create_lead` /
  `get_lead_status` с **mock**-провайдером (без сети, без реальной CRM).

## 5. Рекомендации и объяснение

`recommend_growth_actions` → «увеличить кейсы», «сделать больше CTA», «масштабировать
Telegram», «повторить успешные кампании». `explain_revenue` → «эти публикации принесли
больше всего заявок/денег» на языке клиента. Рекомендации ничего не применяют.

## 6. Безопасность (инварианты, покрыты тестами)

- **НЕ** отправляет сообщения клиентам, **НЕ** меняет CRM, **НЕ** продаёт автоматически;
- **НЕ** включает live и **НЕ** публикует; **НЕ** ходит во внешние рекламные/CRM API
  (CRM-адаптер mock, без сети);
- каждое изменение (`sales_intelligence.analyzed/lead_created/attribution_created/reset`)
  пишется в **AuditLog**;
- `reset` сбрасывает агрегаты профиля и производную атрибуцию, но **НЕ удаляет** историю
  событий лидов;
- строго per-project (tenant isolation); секретов не хранит (`event_metadata`
  санитизируется, представления секреты наружу не отдают); всё **бесплатно** (0 units).

## 7. API / UI / CLI

API (под project-guard): `GET /projects/{id}/sales-intelligence`, `POST …/analyze`,
`POST …/leads`, `GET …/revenue`, `GET …/explanation`, `POST …/reset`.

UI: `/ui/projects/{id}/sales-intelligence` — «AI продажи из контента» (воронка
клики→лиды→сделки→выручка, что приносит деньги, рекомендации AI).

CLI: `make sales-analyze project_id=1`, `make sales-report project_id=1`,
`make sales-lead project_id=1 event=deal_won value=50000 post_id=12`.

## 8. Модель данных

`AILeadEvent` (сигналы) + `ContentRevenueAttribution` (строки атрибуции) +
`SalesIntelligenceProfile` (одна на проект). Миграция: **`0050_ai_sales_intelligence`**
(down_revision `0049_ai_campaign_manager`). Конфиг: `sales_intelligence_enabled`
(kill-switch, default true), `sales_intelligence_default_attribution_model` (`last_touch`).
