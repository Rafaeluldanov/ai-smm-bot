# 26. Botfleet SaaS UX: платформы, расписания, юнит-экономика, аналитика (v0.2.12)

Документ описывает продуктовую логику личного кабинета Botfleet: как устроены
аккаунты/проекты/платформы, рабочие области платформ, задачи расписания, гайды
подключения, юнит-экономику, правила биллинга, модель безопасности и аналитику.
Реализация — server-rendered `/ui/*` (`backend/app/api/ui.py`), без сборки/CDN,
адаптивная тема (light/dark). Живые публикации выключены, всё — preview/dry-run.

## Структура личного кабинета

```
Пользователь (User)
 └─ Аккаунт / workspace (Account)         ← видит только свои
     ├─ Биллинг (BillingAccount, units)
     └─ Проекты (Project)                 ← только проекты своего аккаунта
         ├─ Платформы (CrmSmmResource)    ← VK / Telegram / Instagram / Яндекс Диск / …
         │   ├─ Настройки (ключи/токены — только маска)
         │   ├─ Гайд подключения
         │   ├─ Расписания (CrmPublishingPlan) — отдельные задачи
         │   ├─ Preview (dry-run)
         │   └─ Аналитика
         ├─ Медиа-источники
         └─ Категории продвижения
```

- **Sidebar**: Проекты (со списком проектов пользователя, активный подсвечивается) /
  Тарифы / Аналитика / Гайд / Настройки.
- **Проектный дашборд** (`/ui/projects/{id}/dashboard`): заголовок «Проект: {имя}»,
  кнопки (Настройки проекта / Создать платформу / Создать расписание), горизонтальная
  сетка кликабельных карточек платформ (VK, Telegram, Instagram, Яндекс Диск, Website,
  будущие YouTube/RuTube), компактный блок «Активность» (next actions + последние посты)
  ниже. Длинных инструкций на дашборде нет — они в разделах платформ.

## Модель tenant / account / project

- `Account.owner_user_id` + `AccountMembership(account_id, user_id, role)` определяют
  доступ. `Project.account_id` привязывает проект к аккаунту (может быть `None` у
  старых сид-проектов — такой проект не принадлежит tenant).
- Guard-функции — `backend/app/services/saas_security_service.py`:
  `user_can_access_account` / `user_can_access_project` и `assert_*` (бросают
  `SaasAccessError` → HTTP 403). Пользователь видит только аккаунты, где он владелец
  или участник, и только проекты этих аккаунтов.

## Рабочая область платформы

`/ui/projects/{id}/platforms/{platform}` — вкладки (визуально tabs, секции + JS):

- **Обзор** — статус, идентификатор, наличие токена (маска), live выключен.
- **Настройки** — VK: OAuth-подключение (App ID / Group ID / Redirect URI / базовый
  домен, кнопка «Подключить VK», «Проверить доступ»); Instagram: карточка (App ID /
  App Secret маска / Redirect URI / Access Token маска / User ID, «Проверить настройки»
  без сети, «Скопировать Redirect URI»); Яндекс Диск: тип источника / root / public /
  теги; прочее — ссылка в настройки проекта.
- **Гайд подключения** — подробная инструкция площадки (см. ниже).
- **Расписание** — задачи расписания + «Создать расписание».
- **Preview** — переход в планировщик + dry-run.
- **Аналитика** — переход в раздел аналитики.

## Задачи расписания

Каждый `CrmPublishingPlan` показывается как отдельная **карточка-задача** внутри
платформы (`/ui/projects/{id}/platforms/{platform}/schedule` и вкладка «Расписание»):

- Название плана (категория), платформа, категория/тег, дни недели, время публикаций,
  период действия, режим (`draft | semi_auto | live_disabled`), статус (active/draft),
  **стоимость одной публикации в units** (из юнит-экономики), **следующая дата**
  (считается в браузере из дней/времени).
- Кнопки: **Изменить**, **Пауза/Возобновить**, **Preview ближайших постов**,
  **Удалить** — все безопасные: удаление/пауза не выполняют разрушительных действий и
  не трогают бота (плановая рассылка из UI не запускается).
- Можно создать несколько расписаний на одну платформу (напр. Telegram/футболки/Пн-Ср-Пт
  и Telegram/худи/Вт-Чт). Задачи берутся из `dashboard.extra.schedule_tasks`
  (лёгкий DTO в `build_dashboard`, без новой миграции).

## Гайды подключения (по платформам)

Общий `/ui/guide` — **обзорный** (что такое Botfleet, проекты, платформы, расписание,
units, preview/dry-run, почему live выключен) + ссылки на платформенные гайды.
Подробные инструкции — на `/ui/guide/{platform}` и во вкладке «Гайд подключения»:

- **Telegram** — BotFather, токен, бот-админ канала, `@channel_username`/id, проверки
  `getMe`/`getChat`/`getChatMember`, ошибка `Bad Request: chat not found` и причины,
  media group, live off.
- **VK** — Group ID, community token (text-only), user-token для фото, `error 27`
  (Group authorization failed), стратегии wall/album, публичный HTTPS-домен для OAuth
  (localhost/туннели не годятся), проверки `users.get` / `groups.get filter=admin` /
  `vk-api-photo-probe-upload`.
- **Instagram** — Professional (Business/Creator) → Facebook Page → Meta Developer App →
  Graph API; при проблемах — accountquality, «Instagram API with Instagram Login»,
  обход блокировки Meta Developer на новом устройстве; `/{ig-user-id}/media` +
  `media_publish`; **публичный image_url** (media-proxy — позже).
- **Яндекс Диск** — публичная ссылка, root folder, теги/папки, HEIC/HEIF→JPEG; Telegram/VK
  качают файл, Instagram требует публичный image_url.

## Юнит-экономика

Сервис `backend/app/services/unit_economics_service.py`. Цены провайдера и наценка —
в конфиге (`config.py` / `.env`), НЕ в коде:

```
себестоимость_usd = in/1M*AI_INPUT_USD_PER_1M + out/1M*AI_OUTPUT_USD_PER_1M
цена_клиента_usd  = себестоимость_usd * BILLING_MARKUP_MULTIPLIER
units = max(min_units, ceil(цена_клиента_usd * BILLING_USD_TO_UNIT_RATE))
```

Настройки: `AI_PRICING_MODEL`, `AI_INPUT_USD_PER_1M`, `AI_OUTPUT_USD_PER_1M`,
`BILLING_MARKUP_MULTIPLIER`, `BILLING_USD_TO_UNIT_RATE`, `BILLING_MIN_POST_UNITS`,
`BILLING_MIN_ANALYTICS_UNITS`.

Функции: `estimate_generation_units(in, out, action_type)`,
`estimate_publication_units(platform, media_count, has_ai_generation)`,
`estimate_analytics_units(post_count, depth)`, `estimate_schedule_generation_units`,
`build_pricing_table()`. Витрина цен — на `/ui/tariffs`.

Примеры (при значениях по умолчанию): генерация короткого поста (2000/500) → **5 units**
(минимальный порог); публикация text-only **2**, с медиа **3**, Instagram **4**;
аналитика basic **3** / standard **5** / deep **15**.

## Правила биллинга

- Списание — через `BillingService.reserve_or_debit` (единая точка: ledger +
  `usage_events`). usage_type: `post_generation | post_publication | post_analytics |
  schedule_generation | media_processing`.
- Публикация списывает **только после успешной** публикации; генерация — после
  создания черновика; аналитика — после успешного отчёта; **dry-run/preview — 0 units**.
- **Неуспешная публикация не списывает**; если списали, а публикация упала —
  компенсирующий `refund`. **Повтор не списывает дважды** (идемпотентность по
  `idempotency_key`, уникальный constraint в ledger).
- Нельзя уйти в минус: `reserve_or_debit` проверяет баланс и бросает
  `InsufficientBalanceError` (→ 402/409).

## Модель безопасности (checklist)

1. **Tenant-изоляция**: пользователь видит только свои аккаунты и проекты; guard-функции
   `saas_security_service`. _Follow-up: подключить guard как FastAPI-зависимость к
   `/saas/*` read-эндпоинтам (dashboard/projects/billing)._
2. **Секреты**: api_key/access_token/app_secret никогда не показываются, только маска;
   не встраиваются в HTML, не логируются, не возвращаются через API.
3. **Биллинг**: нельзя в минус (если тариф не разрешает credit); действие не выполняется
   без баланса; списание идемпотентно; неуспех не списывает; повтор не списывает дважды.
4. **Live safety**: live-флаги false по умолчанию; UI не включает live; плановая рассылка
   не запускается случайной кнопкой; разрушительные действия — с confirm.
5. **Rate limits / abuse (TODO)**: rate limit на аккаунт (API); лимит запланированных
   постов в день; лимит отчётов аналитики в день; audit log действий.
6. **Тесты**: `test_saas_security.py` (изоляция, маска), `test_ui_pages.py` (нет секретов/
   publish-due/live=true в HTML), `test_unit_economics_service.py` (идемпотентность,
   неуспех не списывает).

## Модель аналитики

Раздел `/ui/analytics`: выбор проекта, платформы, периода (today/7d/30d/custom) и глубины
(basic/standard/deep); календарный вид (статусы published/scheduled/failed/needs_review);
детализация поста (impressions, reach, views, likes, comments, shares, saves, clicks,
ER, CTR) и рекомендации (что улучшить, лучшее время, лучшие теги, тип контента, следующий
пост). Стоимость отчёта показывается **до** запуска (dry-run оценка в units).

Сервис `backend/app/services/analytics_planning_service.py` — офлайн: оценивает units
через юнит-экономику и готовит превью. Реальные метрики берутся из `PostAnalyticsSnapshot`
и офлайн-провайдера (`FakeAnalyticsProvider`); **внешние API не вызываются**.

Платность: basic **2** (порог 3), standard **5**, deep **15** units; AI-рекомендации —
отдельным списанием по токенам ×наценка.

## Будущие интеграции

- **YouTube / RuTube** — публикация видео (адаптеры-скелеты; live планируется).
- **Google Drive** — медиа-источник (planned).
- **Media-proxy Botfleet** — публичные HTTPS image_url для Instagram (planned).
- **Аналитика** — реальные метрики соцсетей и глубокие AI-отчёты (planned).

## Обновление v0.2.13: глубокая аналитика и платежи

Глубина аналитики переведена на **light/standard/deep** (10/20/40 units за пост),
добавлены анализ контента постов, календарь, ручной ввод метрик и платёжная архитектура
для России (карта/СБП/QR/счёт для ИП-ООО, mock/sandbox). Реальные платежи выключены
(`PAYMENTS_LIVE_ENABLED=false`). Полное описание —
[27_Botfleet_аналитика_и_платежи.md](27_Botfleet_аналитика_и_платежи.md).

## Обновление v0.3.1: безопасность и tenant-изоляция

Добавлены HTTP-гарды владения (аккаунт/проект/счёт/ресурс), роли owner/admin/member,
редакция секретов в логах/вебхуках, единый API платных действий (idempotent, не в минус)
и аудит-лог. Live/payments по-прежнему выключены. См.
[28_Botfleet_SaaS_безопасность.md](28_Botfleet_SaaS_безопасность.md).

## Обновление v0.3.5: каталог платформ, иконки и demo-аналитика

Продуктовый слой обновлён (подробно —
[32_Botfleet_Каталог_платформ_и_аналитика_постов.md](32_Botfleet_Каталог_платформ_и_аналитика_постов.md)):

- Единый **каталог платформ** (`platform_catalog_service.py`) — Россия + международные,
  с уровнями поддержки (active/beta/planned/research) и флагами возможностей.
- **Оригинальные inline SVG-иконки** (`platform_icons.py`), не официальные логотипы, без
  CDN; аккуратны в light/dark.
- **Дашборд** — адаптивная сетка платформ с иконками, бейджами и статусом; planned-карточки
  кликабельны (roadmap).
- **Workspace** площадки — иконка + уровень поддержки, гайды, «интеграция в разработке» для
  planned.
- **Demo-аналитика** по существующим публикациям (offline): estimated views/reach/ER/CTR +
  quality/engagement, источник метрик (internal/estimated/demo) всегда указан. Live-вызовов
  внешних API нет.

## Обновление v0.3.6: self-service подключение платформ

В workspace площадки добавлена вкладка **«Настройки» → «Подключение»**: клиент вводит
токен/ID сам (без `.env`), секреты хранятся зашифрованно в проекте, показывается только
маска. Кнопки «Сохранить / Проверить подключение / Отключить», блок last-check и **«Журнал
действий»** (автоматический audit, без секретов). Расписания и публикации используют
credentials проекта; preview показывает источник кредов (project_connection/env_fallback/
missing). Подробно —
[33_Botfleet_Self_Service_Platform_Connections.md](33_Botfleet_Self_Service_Platform_Connections.md).

## Обновление v0.3.7: media proxy для Instagram

В Instagram workspace добавлена секция **«Публичные ссылки на медиа»** и страница
`/ui/projects/{id}/media-proxy` (статус base URL/HTTPS/TTL, список ссылок, отзыв). Instagram
preview показывает `needs_public_image_url`, готовность media-proxy и предупреждение, если
base URL не HTTPS. Ссылки `/media/public/{token}` временные, отзываемые, raw-токен не
хранится. Живая публикация Instagram выключена. Подробно —
[34_Botfleet_Media_Proxy_Public_Image_URL.md](34_Botfleet_Media_Proxy_Public_Image_URL.md).
