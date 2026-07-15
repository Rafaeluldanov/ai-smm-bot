# Botfleet AI Campaign Manager (v0.6.7)

Botfleet переходит от «создавать хорошие посты» к «управлять маркетинговыми
кампаниями». Кампания — это цель + продукт + аудитория + период + стратегия
(этапы воронки / темы / форматы / CTA / KPI). Это слой **планирования и рекомендаций**;
он НЕ публикует и ничего не запускает сам.

## 1. Зачем кампании

Отдельные хорошие посты не дают системного результата. Кампания задаёт **цель** и
**воронку**: серию постов, ведущих аудиторию от знакомства к целевому действию, с
измеримыми KPI и понятной логикой «зачем каждый пост».

## 2. Отличие от стратегии (v0.6.6)

- **Content Strategy (v0.6.6)** — постоянная «настройка» проекта: какие темы усиливать,
  какие форматы делать чаще, какая частота. Бессрочно и не привязано к цели.
- **Campaign Manager (v0.6.7)** — **временная, целевая** конструкция: у кампании есть
  цель (`sales`/`awareness`/`launch`/…), продукт, аудитория, **период** и **этапы
  воронки**. Кампания ОПИРАЕТСЯ на стратегию и обучение, но организует их вокруг цели.

## 3. Как AI строит кампанию

`plan_campaign` (один снапшот проекта) делает три шага:
1. **build_campaign_strategy** — берёт снапшот `ContentStrategistService` (v0.6.6:
   бизнес-цель + AI Learning + аналитика + SEO + тренды) и деривит стратегию кампании:
   `{campaign_theme, stages, content_mix, best_topics, posting_frequency, seo_keywords,
   trends, kpi}`. KPI подбираются по цели (sales→conversions/ctr, awareness→reach/…).
2. **generate_campaign_plan** — создаёт `AICampaignStage` (воронка). Набор этапов зависит
   от цели: `sales → awareness · interest · trust · conversion`; `awareness → awareness ·
   interest`; и т. д. Каждому этапу — темы/форматы (из обучения/аналитики), CTA-стратегия
   и длительность (по периоду кампании).
3. **generate_recommendations** — `AICampaignRecommendation` (topic/media/schedule/cta/
   post) с обоснованием, уверенностью и ожидаемым результатом. Дедуп по (type, title).

## 4. Как используются learning + strategy

- **AI Learning (v0.6.5)** — если клиенту лучше заходит формат `case`, кампания включает
  больше `case` в этапах и в `content_mix`.
- **Content Strategy (v0.6.6)** — сильные темы попадают в `best_topics` и темы этапов,
  слабые темы уходят в `weak_topics` и не продвигаются.
- SEO-спрос и тренды добавляются как дополнительные сигналы темы.

## 5. Как работает approve flow

Flow: **Campaign → AI Plan → Review → Approve → Calendar Draft → Autopilot Execution**.

1. **Create** — `create_campaign` (status=draft).
2. **Plan** — `generate` → стратегия + этапы + рекомендации (status planning→review).
3. **Review** — клиент принимает/отклоняет рекомендации (accept/reject).
4. **Approve** — `approve_campaign` (status=approved) — обязательный шаг.
5. **Apply** — `apply_campaign` срабатывает ТОЛЬКО при `status==approved` **И**
   `confirmation=="APPLY_CAMPAIGN"`.

## 6. Как создаётся календарный draft

`apply_campaign` вызывает `AutopilotCalendarAssistantService.create_calendar_plan(…,
dry_run=False)`, что создаёт `AutopilotCalendarPlan` со **status=draft**. Это:
- **НЕ** активный календарь (`CrmPublishingPlan` не создаётся/не меняется);
- **НЕ** публикация и **НЕ** включение live (`live_enabled=False`);
- лишь черновик, который клиент дальше запускает через автопилот отдельно.

`campaign_calendar_preview` показывает будущий календарь по неделям (week 1..4)
**без записи** (dry_run).

## 7. Безопасность (инварианты, покрыты тестами)

- кампания **НЕ публикует**, **НЕ включает** live и **НЕ меняет** глобальные
  `*_LIVE_PUBLISHING_ENABLED`;
- **НЕ меняет активный календарь** (нет `apply_calendar_to_project`);
- **НЕ вызывает внешние рекламные API**;
- `apply` невозможен без `approved` + `APPLY_CAMPAIGN`; `apply` даёт `live_enabled=False`;
- `ai_campaign_auto_apply_enabled` по умолчанию `false` (только Approve→Apply);
- каждое изменение (`campaign.created/planned/recommendation_generated/approved/applied`)
  пишется в **AuditLog**;
- строго per-project (tenant isolation через `require_campaign_access`); секретов не
  хранит; всё **бесплатно** (0 units).

## 8. API / UI / CLI

API: `POST/GET /projects/{id}/campaigns`, `GET /campaigns/{id}`, `POST …/generate`,
`GET …/strategy`, `GET …/explanation`, `GET …/recommendations`,
`POST …/recommendations/{id}/accept|reject`, `POST …/approve`, `POST …/apply`,
`GET …/calendar-preview`.

UI: `/ui/projects/{id}/campaigns` — «AI кампании» (создать кампанию, план по неделям,
«почему AI выбрал это», карточки рекомендаций с Принять/Отклонить, Одобрить/Применить).

CLI: `make campaign-create project_id=1 name=… goal=sales`, `make campaign-plan
campaign_id=1`, `make campaign-apply campaign_id=1`.

## 9. Модель данных

`AICampaign` (цель/статус/период/продукт/аудитория/strategy_snapshot/kpi) +
`AICampaignStage` (воронка) + `AICampaignRecommendation` (Review→Apply).
Миграция: **`0049_ai_campaign_manager`** (down_revision `0048_content_strategy`).
Термины: `CampaignGoal`, `CampaignStatus`, `CampaignStage`, `CampaignRecommendationStatus`.
