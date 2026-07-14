# 59. Botfleet: Слой доставки медиа (Media Proxy Layer, v0.6.2)

Инфраструктурный слой доставки: Botfleet берёт `MediaAsset`, проверяет источник (Яндекс Диск /
локальная улучшенная копия), создаёт **временную подписанную публичную HTTPS-ссылку** и отдаёт по
ней оптимизированное изображение. Это нужно платформам, которые публикуют по публичному `image_url`
(Instagram Graph API), и как надёжный fallback для VK/Telegram.

> **Это только инфраструктура доставки.** Реальных публикаций (Instagram/VK/Telegram) НЕ выполняется,
> глобальные `*_LIVE_PUBLISHING_ENABLED` не меняются, production-env не трогается. Отдача оригинала по
> умолчанию **выключена** (`MEDIA_PROXY_ALLOW_ORIGINAL=false`) — наружу уходят только трансформации.

Продолжение существующего media-proxy ([раньше](57_Botfleet_Telegram_Live_Rollout.md) — foundation
`PublicMediaLink`): та же модель токена расширена (transform/token_type/max_requests), добавлены
трансформации на лету, per-platform URL, лимиты и журнал обращений. Новой параллельной архитектуры
не заводили.

## Зачем нужен proxy

- **Instagram** Graph API создаёт медиа-контейнер по **публичному HTTPS `image_url`** (не по файлу).
  Медиа Botfleet лежит на Яндекс Диске / в локальной улучшенной копии — недоступно Instagram напрямую.
- **VK** загрузка фото надёжнее с готового URL как fallback (когда нет локальной копии/диска).
- **Telegram** может принять URL напрямую.

Proxy выдаёт ссылку `https://<домен>/media/{token}`, ограниченную по времени, с лимитом запросов,
подходящего размера — и не раскрывает внутренние пути.

## Подписанные URL и безопасность

- Токен — случайный `secrets.token_urlsafe`; в БД хранится **только `sha256(token)`** и короткий
  `token_prefix` (для показа). Сырой токен показывается один раз при создании.
- Ссылка привязана к account/project/media_asset, ограничена `expires_at`, отзывается (`revoked`).
- **Журнал обращений** `MediaProxyAccessLog` пишет только хеши IP/UA (не сами IP/UA), HTTP-код,
  размер/тип ответа и трансформацию. Ни токена, ни внутренних путей.
- Content-type ограничен allowlist, размер — лимитом; ошибки не раскрывают путь файла.
- `MEDIA_PROXY_ALLOW_ORIGINAL=false`: токены `token_type=="original"` (создаются слоем доставки
  `create_media_url`/`build_social_media_url` при явном original) при отдаче блокируются (403).
  Флаг регулирует именно **слой доставки v0.6.2**; старые `create_public_link`/`public-link`-ссылки
  (`token_type=="image"`) отдают конвертированный+ограниченный по размеру оригинал как раньше.
- Хеш IP/UA в журнале использует **HMAC с `MEDIA_PROXY_SECRET_KEY`** (перец), если задан — иначе
  sha256; при заданном перце низкоэнтропийный IPv4 нельзя вскрыть перебором.
- Отдача помечается `Cache-Control: private, must-revalidate` (не `public`), чтобы отзыв/истечение
  токена не обходились shared-кешами (CDN).

## Трансформации (ресайз на лету)

`MediaProxyTransform`: `original`, `width_640`, `width_1080`, `square`, `social_preview`.
Применяются **на лету** при отдаче через `ImageEnhancementProcessor.transform_bytes` (Pillow),
результат кешируется (файловый кеш по хешу содержимого + `MEDIA_PROXY_CACHE_SECONDS`; заголовок
`Cache-Control: public, max-age=<cache_seconds>`). Вход: jpg/png/webp/heic (HEIC→JPEG); выход:
jpg/webp. `original` — без ресайза (и по умолчанию не отдаётся).

## Требования площадок (per-platform URL)

`build_social_media_url(platform)` подбирает трансформацию:

| Площадка | Трансформация | Примечание |
|---|---|---|
| Instagram | `width_1080` | Graph API `image_url`, квадрат/1080 |
| VK | `original`→`width_1080` | оригинал, если разрешён; иначе 1080 |
| Telegram | `original`→`width_1080` | как есть; иначе 1080 |

`generate_preview_url()` — `social_preview` для UI. Если `ALLOW_ORIGINAL=false`, «original» везде
понижается до `width_1080`, чтобы доставка работала.

## Интеграция с публикацией (только подготовка)

`PostPublicationService.prepare_media_delivery(post, platform)` — для instagram/vk/telegram: если у
поста есть медиа и proxy включён, создаёт публичную ссылку и возвращает URL. Вызывается в
`_publish_one` **перед** обращением к клиенту и кладёт URL в `PublishRequest.media_url`. Это только
**подготовка** — реальная отправка ниже всё равно под всеми safety-gates (по умолчанию выключена):

- `InstagramPublishingClient.public_image_url(request)` — читает подготовленный `image_url` (dormant,
  live не реализован);
- `VKPublishingClient.public_media_url(request)` — fallback-источник (dormant, live off по умолчанию).

## API

Публичная отдача (без auth):
- `GET /media/{token}` — основной endpoint доставки (трансформа применяется, журнал пишется);
- `GET /media/public/{token}` — совместимость.

Управление (под `require_project_access`):
- `POST /media-proxy/projects/{id}/assets/{asset_id}/generate` — создать URL с трансформацией;
- `POST /media-proxy/projects/{id}/assets/{asset_id}/platform-urls` — набор ссылок (preview/ig/vk/tg);
- `GET /media-proxy/projects/{id}/assets/{asset_id}` — токены актива (маскированные) + обращения;
- `GET /media-proxy/projects/{id}/links`, `/status`;
- `DELETE /media-proxy/tokens/{token_id}` — отключить токен (гард `require_media_proxy_token_access`).

UI: `/ui/projects/{id}/media-proxy` («Доставка медиа»): статус, генерация ссылок для актива,
доступные URL, обращения, отзыв.

## Данные

- Расширена `public_media_links`: `token_type`, `transform`, `max_requests` (request_count = hit_count).
- `media_assets`: `proxy_ready`, `last_proxy_generated_at`.
- Новая `media_proxy_access_logs` (только хеши IP/UA).
- Миграция **`0044_media_proxy_layer`** (down_revision `0043_live_autopilot_monitoring`). SQLite+PostgreSQL.

## Настройки (безопасные дефолты)

```
MEDIA_PROXY_ENABLED=true
MEDIA_PROXY_DOMAIN=                 # приоритет над MEDIA_PROXY_PUBLIC_BASE_URL
MEDIA_PROXY_SECRET_KEY=            # необязательный «перец»
MEDIA_PROXY_DEFAULT_TTL_SECONDS=86400
MEDIA_PROXY_MAX_REQUESTS=10000
MEDIA_PROXY_ENABLE_RESIZE=true
MEDIA_PROXY_CACHE_ENABLED=true
MEDIA_PROXY_CACHE_SECONDS=86400
MEDIA_PROXY_ALLOW_ORIGINAL=false
```

## CLI

```
make media-proxy-check
make media-proxy-generate project_id=1 media_asset_id=1 transform=width_1080 [platform=instagram]
make media-proxy-cleanup [dry_run=true]
```

## Архитектура (поток)

```
create_media_url / build_social_media_url / generate_preview_url
   → PublicMediaLink (token_hash, transform, token_type, max_requests, expires_at)
   → mark MediaAsset.proxy_ready
GET /media/{token}
   → validate (hash/TTL/active/лимит/allow_original)
   → download (локальная копия → Яндекс Диск) → HEIC→JPEG
   → transform_bytes (ресайз/кроп, кеш)
   → MediaProxyAccessLog (хеши IP/UA, статус, размер) → StreamingResponse
```
