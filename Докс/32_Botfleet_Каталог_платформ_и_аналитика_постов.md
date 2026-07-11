# 32. Botfleet: каталог платформ, оригинальные иконки и demo-аналитика (v0.3.5)

Документ описывает продуктовый слой: единый каталог медиа-платформ (Россия +
международные), оригинальные inline SVG-иконки, красивую сетку платформ на дашборде,
платформенные workspace-страницы и демо-аналитику по уже опубликованным постам.

> Всё работает **offline**: никаких live API-вызовов, реальных публикаций и платежей.
> Live-публикации и боевые платежи выключены (`*_LIVE_PUBLISHING_ENABLED=false`,
> `PAYMENTS_LIVE_ENABLED=false`).

## 1. Единый каталог платформ

`backend/app/services/platform_catalog_service.py` — единственный источник правды о
площадках. Каждая площадка описана декларативно (`PlatformCatalogItem`):

- `key`, `title_ru`, `title_en`, `category`, `support_level`;
- `can_publish` / `can_schedule` / `can_analytics` / `can_media`;
- `requires_public_media_url` (нужна ли публичная ссылка на медиа);
- `notes_short`, `guide_anchor`, `icon_svg`, `accent_class`.

**Категории:** messenger, social, video, blog, marketplace, storage, website, email,
business_directory.

**Уровни поддержки:** `active` (активна) → `beta` (скоро) → `planned` (в планах) →
`research` (исследуем).

### Что активно
- **Telegram** — текст и фото, media-group (бот-администратор + токен).
- **ВКонтакте** — текст по ключу сообщества, фото по личному user-token (OAuth).
- **Instagram** — Meta Graph API, требуется публичный HTTPS `image_url`.
- **Сайт** — витрина/лендинг и SEO-контекст.
- **Яндекс Диск** — источник медиа (папки/теги, HEIC→JPEG).

### Ближайшие (beta)
YouTube, RuTube, Дзен, Одноклассники, Google Drive — адаптеры-скелеты, публикация
готовится.

### Планируемые / исследуем
Facebook (страница), TikTok, Pinterest, TenChat, VC.ru, LinkedIn, X (Twitter), Threads,
E-mail рассылки, Блог/CMS, WhatsApp Business, 2ГИС, Авито, Пикабу.

## 2. Почему иконки оригинальные, а не официальные логотипы

`backend/app/services/platform_icons.py` содержит `PLATFORM_ICON_SVG` — набор
**оригинальных inline SVG-иконок** «в духе» площадок:

- это **НЕ** официальные логотипы и **не копии** товарных знаков;
- только inline SVG, **никаких CDN/внешних URL** и растровых картинок;
- иконки используют `currentColor` и акцент-класс `accent-*`, поэтому аккуратно
  выглядят в **light и dark** темах;
- юридически безопасно: официальные логотипы часто нельзя перерисовывать/встраивать без
  разрешения — поэтому мы рисуем узнаваемые, но собственные символы.

CSS: `.platform-grid`, `.platform-card.active/beta/planned/research`, `.platform-icon`,
`.platform-icon svg`, `.pc-badge`, `.accent-*`.

## 3. Дашборд проекта

`/ui/projects/{id}/dashboard` — адаптивная сетка `.platform-grid` (desktop 3–4 в ряд,
tablet 2, mobile 1). Карточка: оригинальная иконка, название, бейдж уровня поддержки,
статус подключения (подключено / не подключено / скоро) и короткие ключевые данные
(Telegram channel, VK group, IG user, storage URL). Planned-площадки показаны как «в
планах», но **кликабельны** — открывают workspace с роадмапом. Длинные инструкции из
карточек убраны.

## 4. Платформенные workspace-страницы

`/ui/projects/{id}/platforms/{platform}` — вкладки Обзор / Настройки / Гайд / Расписание /
Preview / Аналитика. Заголовок: оригинальная иконка + название + уровень поддержки +
статус. Для planned-площадок — баннер «интеграция в разработке» и роадмап; кнопки
подключения/публикации недоступны. Гайды Telegram/VK/Instagram/Яндекс Диск — внутри
своих workspace; глобальный `/ui/guide` остаётся обзорным.

## 5. Demo-аналитика по существующим постам

`backend/app/services/post_analytics_service.py` (метод `build_demo_post_analytics`) —
демо-аналитика по **уже существующим публикациям** (`Post` + `PostPublication`). **Никаких
live API-вызовов**: метрики берутся из БД и оцениваются по тексту/структуре.

Помощники: `analyze_post_text`, `detect_cta`, `detect_links`, `detect_hashtags`,
`estimate_quality_score`, `estimate_engagement_score`, `build_recommendations`,
`estimate_engagement`.

Поля карточки: `post_id`, `publication_id`, `platform`, `status`, `external_url`,
`title`, `text_preview`, `media_count`, `text_length`, `has_link`, `has_cta`,
`hashtags_count`, `estimated_views/reach/likes/comments/shares`, `er_percent`,
`ctr_percent`, `quality_score`, `engagement_score`, `source`.

### Формулы демо-метрик (прозрачные, детерминированные)
```
views  = базовый охват площадки + бонус за медиа + бонус за CTA
reach  = views · 0.75
likes  = views · (1.5% … 4%)   # растёт с quality_score
comments = likes · 5%
shares   = likes · 8%
ER %   = (likes + comments + shares) / reach · 100
CTR %  = clicks / views · 100  (по наличию ссылки)
quality_score 0..100  # длина, ссылка, CTA, медиа, хэштеги, абзацы
```

### Источники метрик (`source`) — всегда указаны явно
- `internal` — реальные, введённые вручную (снапшот `manual`);
- `demo` — сохранённый снапшот (демо-данные);
- `estimated` — оценка по тексту/структуре (реальных метрик ещё нет).

**Демо/estimated НЕ выдаются за реальные API-метрики.** Реальные метрики платформенных
API будут подключаться отдельным этапом.

## 6. Analytics UI

`/ui/analytics`: фильтры (проект / платформа / период / статус / глубина), summary-cards
(всего / опубликовано / запланировано / failed / средние quality и engagement),
календарь, demo-карточки постов (иконка площадки, статус, источник, estimated
views/reach/ER/CTR, ссылка) и детальная карточка с рекомендациями. Стоимость анализа:
light 10 / standard 20 / deep 40 units; preview бесплатно, запуск платный. Реальный
платный запуск из UI не инициируется — только безопасный preview и estimated units.

## 7. Что реальные API дадут позже (следующие этапы)
- реальные метрики платформенных API (VK/Telegram/Instagram/…);
- реальный provider-sandbox платежей (см. [31](31_Botfleet_Платежи_ЮKassa_СБП_QR.md));
- media-proxy для публичных `image_url` (Instagram/Pinterest/CMS);
- домен/деплой (см. [30](30_Botfleet_Public_Launch_Readiness.md)).

> На этом этапе внешние API не вызываются: каталог, иконки и аналитика полностью
> офлайн-демо. Это витрина продукта, а не боевая интеграция.
