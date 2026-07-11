# 27. Botfleet: глубокая аналитика и платёжная архитектура (v0.2.13)

Документ описывает аналитику постов (light/standard/deep), источники метрик, календарь,
ручной ввод метрик, юнит-экономику аналитики, платёжный слой для России (карта/СБП/QR/
счёт для ИП-ООО), правила биллинга, безопасность вебхуков и anti-free-use.

> **Реальных платежей нет.** `PAYMENTS_LIVE_ENABLED=false` по умолчанию; счета создаёт
> только mock-провайдер, остальные — sandbox/planned-скелеты без сетевых вызовов. Баланс
> пополняется только после статуса `paid` (mock-pay/webhook).

## Уровни аналитики

| Глубина | Цена (units/пост) | Что входит |
|---|---|---|
| **light** | 10 | базовые метрики + структура поста |
| **standard** | 20 | + оценка вовлечения и качества (estimated) |
| **deep** | 40 | + рекомендации, лучшее время, теги, следующий пост |

Цены фиксированы в конфиге (`ANALYTICS_LIGHT_UNITS`/`STANDARD`/`DEEP`), считаются
`unit_economics_service.estimate_analytics_units(depth, post_count)` = цена × число постов.
Неизвестная глубина → `ValueError`. Ручной ввод метрик и preview/dry-run — **0 units**.

## Источники данных (analytics_source)

Источник метрик **всегда указывается** — оценка не выдаётся за реальные данные:

- `internal` — данные из БД: пост, текст, дата, платформа, статус, media_count, external_url;
- `manual` — метрики, внесённые пользователем;
- `estimated` — оценка по тексту/медиа/структуре (когда реальных метрик нет);
- `api` — реальные метрики платформы (когда появится API);
- `demo` — демо-метрики для визуализации (офлайн-провайдер).

Внешние API Telegram/VK/Instagram **не вызываются**.

## Анализ контента и метрики

`post_analytics_service.py`:
- `analyze_post_content` — длина текста, ссылка, CTA, вопрос, цена/цифры, хэштеги, медиа,
  структура (абзацы), **B2B-релевантность**, `quality_score` (0..100), рекомендации;
- `estimate_post_metrics` — `engagement_score`, `quality_score`, `predicted_reach_level`
  (low/medium/high), `risk_flags` (no_media/too_long/no_cta/low_b2b_value…);
- `build_post_analytics_card(depth)` — карточка поста (метрики + источник + рекомендации);
- `list_project_posts_for_analytics`, `build_calendar` (дни со счётчиками статусов);
- `preview_analytics_cost` / `run_analytics_dry` (бесплатно) / `run_analytics` (платно).

Метрики поста: views, reach, impressions, likes, comments, shares, saves, clicks,
followers_delta, **ER** = (likes+comments+shares+saves)/max(reach,1),
**CTR** = clicks/max(impressions,1), media_count, text_length, has_link/has_cta,
hashtags_count, quality_score, engagement_score, b2b_relevance_score.

Рекомендации: усилить первый абзац, добавить CTA/оффер/цифры/ссылку/вопрос, сократить
текст, media-group, «пост без медиа получит меньше вовлечения», «для B2B добавить кейс».

## Ручной ввод метрик

`POST /analytics/posts/{post_id}/manual-metrics` (source=manual, **0 units**). Поля:
views/reach/impressions/likes/comments/shares/saves/clicks/followers_delta. UI: «Внести
метрики вручную» на `/ui/analytics`. Переиспользует `AnalyticsService.ingest_snapshot`.

## Юнит-экономика и правила биллинга

Списание — только через `BillingService.reserve_or_debit` (идемпотентно по ключу, не в
минус). usage_type: `post_analytics`, `post_generation`, `post_publication`,
`schedule_generation`, `media_processing`.

- аналитика списывает после успешного отчёта; dry-run/preview — 0 units;
- недостаток баланса → `InsufficientBalanceError` (API 402), отчёт не строится;
- повтор с тем же idempotency_key не списывает дважды.

## Платёжная архитектура (Россия)

Методы: `bank_card`, `sbp`, `qr`, `invoice_for_ip`, `invoice_for_company`,
`manual_admin_topup`. Провайдеры: **mock** (реально создаёт счёт), yookassa/tbank/
cloudpayments (sandbox-скелеты), robokassa (planned). Интерфейс —
`services/payments/payment_provider.py`; оркестрация — `payment_service.py`.

### Модель данных (миграция 0014)

- `BillingProfile` — реквизиты плательщика: `customer_type` (individual/ip/company),
  legal_name, inn, kpp, ogrn, ogrnip, legal_address, contact, email, phone;
- `PaymentInvoice` — счёт: provider, method, amount_units, amount_rub, status
  (draft/pending/paid/canceled/failed/expired), payment_url, qr_payload,
  provider_payment_id, **idempotency_key (unique)**, invoice_metadata, paid_at;
- `PaymentTransaction` — транзакция: **raw_payload_sanitized** (без секретов);
- `PaymentWebhookLog` — вебхуки: event_type, provider_payment_id, payload_sanitized,
  signature_valid, processed.

### Поток оплаты (billing flow)

1. `POST /billing/account/{id}/topup/preview` — units → рубли (бесплатно).
2. `POST /billing/account/{id}/invoices` — создать счёт (баланс **не** меняется).
3. `POST /billing/invoices/{id}/mock-pay` — подтвердить mock-оплату → paid + пополнение
   баланса (один раз, идемпотентно по `invoice-{id}-paid`).
4. `POST /billing/webhooks/{provider}` — вебхук: лог + проверка подписи + пополнение.
5. `GET /billing/account/{id}/invoices` / `.../ledger` / `.../usage-events` — история.

### Флаги провайдеров

`PAYMENTS_LIVE_ENABLED=false`, `PAYMENTS_DEFAULT_PROVIDER=mock`,
`PAYMENTS_SUCCESS_RETURN_URL`, `PAYMENTS_FAIL_RETURN_URL`, а также
`YOOKASSA_*`, `TBANK_*`, `CLOUDPAYMENTS_*`, `ROBOKASSA_*` (только placeholders в
`.env.example`; секреты не коммитятся, в UI — только маска).

## Безопасность вебхуков и anti-free-use

- **Webhook security**: неизвестный провайдер → ошибка; недоверенная подпись
  (`signature_valid=false`) не обрабатывается; дубликат по оплаченному счёту идемпотентен;
  `raw_payload_sanitized`/`payload_sanitized` не содержат секретов/подписей.
- **Anti-free-use**: платные действия (analytics run, генерация, публикация, пересборка
  расписания, media) проверяют баланс перед выполнением; списание атомарно-идемпотентно,
  не в минус; неуспех не списывает (или компенсируется refund); UI показывает стоимость до
  действия и делает кнопку «Пополнить баланс» при нехватке.
- **manual topup** — только через admin/CLI (`billing_topup`); создание счёта баланс не
  меняет; баланс растёт только после `paid`.

## Что реальные платежи выключены

Боевой эквайринг не подключён. Следующие шаги: договор с провайдером → sandbox-адаптер →
webhooks с проверкой подписи → включение `PAYMENTS_LIVE_ENABLED=true` только после аудита.

## Обновление v0.3.1: защита платных действий и безопасность

Платные действия защищены единым API `BillingService` (`ensure_balance`,
`debit_for_action`, `credit_payment`, `refund_or_compensate`): идемпотентно, не в минус,
dry-run бесплатно, 402 при нехватке. Счета/вебхуки идемпотентны; payload санитизируется;
аналитика/биллинг доступны только участнику аккаунта (HTTP-гарды). Аудит-лог фиксирует
invoice.created/paid и analytics.run. См.
[28_Botfleet_SaaS_безопасность.md](28_Botfleet_SaaS_безопасность.md).

## Обновление v0.3.4: платёжный контур ЮKassa/СБП/QR и идемпотентность вебхуков

Платёжный слой доведён до полноценного sandbox-flow (реальные платежи по-прежнему
выключены). Полностью описано в
[31_Botfleet_Платежи_ЮKassa_СБП_QR.md](31_Botfleet_Платежи_ЮKassa_СБП_QR.md):

- **Жизненный цикл счёта** стандартизирован: `draft → pending → paid | canceled | failed
  | expired`; константы `PAYMENT_STATUS_*`/`PAYMENT_METHOD_*`, статусы транзакций и
  вебхуков. Сумма счёта неизменяема после `pending`.
- **Mock-provider hardening**: `mock-pay/mock-fail/mock-cancel/mock-expire` (идемпотентно,
  с гардом доступа к счёту).
- **YooKassa sandbox-adapter**: `build_yookassa_payment_payload`, детерминированный
  fake-счёт без сети (`PAYMENTS_PROVIDER_HTTP_ENABLED=false`), проверка подписи вебхука;
  в production недоверенный вебхук → 403.
- **Идемпотентность вебхуков**: дубликат по `provider_event_id` игнорируется, двойного
  пополнения нет; миграция `0017` (provider_event_id/status/processed_at/error_message).
- **Реквизиты плательщика**: `BillingProfileService` (validate/mask/readiness) — готовность
  под метод (карта/СБП/QR/счёт ИП/ООО). Карта в Botfleet не вводится и не хранится.

## Обновление v0.3.5: demo-аналитика постов

Аналитика дополнена **демо-аналитикой по существующим публикациям** (offline, без API) —
подробно в [32_Botfleet_Каталог_платформ_и_аналитика_постов.md](32_Botfleet_Каталог_платформ_и_аналитика_постов.md).
`post_analytics_service.build_demo_post_analytics` строит по одной карточке на публикацию:
`estimated_views/reach/likes/comments/shares`, `er_percent`, `ctr_percent`,
`quality_score`, `engagement_score`, `source`. Формулы прозрачны и детерминированы;
источник (`internal`/`estimated`/`demo`) всегда указан и НЕ выдаётся за реальные
API-метрики. UI `/ui/analytics`: summary-cards, календарь, demo-карточки с иконками
площадок. Стоимость анализа (light/standard/deep) и правила списаний не изменились.
