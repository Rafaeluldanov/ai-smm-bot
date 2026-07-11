# 34. Botfleet: Media Proxy и публичные image_url (v0.3.7)

Foundation для публичных HTTPS-ссылок на медиа. Нужен площадкам, которым для публикации
требуется **публичный image_url** (в первую очередь Instagram).

> На этом этапе **живая публикация Instagram выключена** и `media_publish` не вызывается.
> Это только инфраструктура публичных ссылок: модель, сервис, API, UI, CLI, тесты.

## 1. Зачем нужен media proxy

- **Telegram/VK** могут отправлять файл напрямую (multipart) — им публичный URL не нужен.
- **Instagram Graph API** публикует НЕ локальный файл, а по **публичному HTTPS image_url**
  (`/{ig-user-id}/media` → `/{ig-user-id}/media_publish`). Локальный файл и приватный
  Яндекс Диск не подходят.

Botfleet Media Proxy берёт `MediaAsset` проекта и выдаёт временную ссылку
`https://<base>/media/public/{token}`, доступную из интернета.

## 2. Как генерируется URL

1. Клиент/бот запрашивает ссылку для `media_asset_id` (или для медиа поста).
2. Сервис генерирует случайный токен `secrets.token_urlsafe(MEDIA_PROXY_TOKEN_BYTES)`.
3. В БД сохраняется **только** `sha256(token)` (`token_hash`) и короткий `token_prefix`.
4. Ссылка `= MEDIA_PROXY_PUBLIC_BASE_URL/media/public/{token}` (base берётся из
   `MEDIA_PROXY_PUBLIC_BASE_URL` → `PUBLIC_APP_URL` → `APP_BASE_URL`).
5. **Реальный URL отдаётся один раз** (в момент создания). Дальше — только маска.

## 3. Срок действия, отзыв, доступ

- `expires_at = now + ttl` (ttl из запроса, по умолчанию `MEDIA_PROXY_DEFAULT_TTL_SECONDS`,
  не больше `MEDIA_PROXY_MAX_TTL_SECONDS`).
- `status`: `active | revoked | expired`. Просроченная ссылка при обращении помечается
  `expired`. Отозванная (`DELETE`) — `revoked`.
- Публичный `GET /media/public/{token}` **не требует авторизации**, но обновляет
  `hit_count` и `last_accessed_at`. Неверный/истёкший/отозванный токен → **404**.

## 4. HEIC → JPEG

Если исходный файл HEIC/HEIF — при отдаче он конвертируется в JPEG в памяти
(`maybe_convert_heic` + `ImageEnhancementProcessor`). Оригинал не меняется. `content_type`
ссылки при этом — `image/jpeg`.

## 5. Модель безопасности

- raw-токен **не хранится** (только sha256-хеш) и **не пишется** в логи/аудит; в
  access-log путь `/media/public/{token}` маскируется как `/media/public/***`.
- ссылка привязана к `project_id`/`media_asset_id`; чужой актив/проект — отказ.
- `content_type` ограничен `MEDIA_PROXY_ALLOWED_CONTENT_TYPES` (по умолчанию
  jpeg/png/webp); превышение размера `MEDIA_PROXY_MAX_BYTES` — отказ.
- внутренние пути файлов **не раскрываются** в ответах и ошибках.
- базовый IP rate-limit на `/media/public/` (`RATE_LIMIT_MEDIA_PER_MINUTE`).

## 6. Production: HTTPS обязателен

Внешние платформы (Meta) не смогут загрузить `http://127.0.0.1/...`. В production нужен
публичный **HTTPS-домен** (`media_proxy_require_https_in_production=true`). Свойство
`media_proxy_https_ready` показывает готовность base URL.

## 7. Instagram preview

Dry-run preview (`/analytics`-независимо, через publication preview) для Instagram
показывает:

- `needs_public_image_url=true`, `would_prepare_public_image_url=true`;
- `media_proxy_enabled`, `public_media_base_url_ready`;
- `public_media_warning`, если base URL не HTTPS/недоступен извне.

**Dry-run НЕ создаёт публичные ссылки** и не вызывает внешние API. Для Telegram/VK
`needs_public_image_url=false`.

## 8. API

- `POST /media-proxy/projects/{project_id}/media-assets/{media_asset_id}/public-link`
- `POST /media-proxy/projects/{project_id}/posts/{post_id}/public-links`
- `GET  /media-proxy/projects/{project_id}/links` — список (маски, без токенов)
- `GET  /media-proxy/projects/{project_id}/status` — статус/лимиты
- `DELETE /media-proxy/projects/{project_id}/links/{link_id}` — отозвать
- `GET /media/public/{token}` — **публичная отдача** (без auth), заголовки
  `Content-Type`, `Content-Length`, `Cache-Control: public, max-age=300`,
  `X-Content-Type-Options: nosniff`.

Управляющие роуты — под `require_project_access` (tenant-изоляция).

## 9. CLI

```
make media-proxy-link project_id=1 media_asset_id=1 purpose=instagram
make media-proxy-cleanup dry_run=true
```
`create_public_media_link` по умолчанию печатает только маскированный URL; реальный —
лишь при `--show-url true`. `media_proxy_cleanup` по умолчанию dry-run (ничего не меняет).

## 10. Аудит

`media_proxy.link.created`, `media_proxy.link.revoked`, `media_proxy.link.expired` — с
`project_id`/`media_asset_id`/`link_id`/`purpose`/`expires_at`, **без raw-токена**.

## 11. Ограничения и что дальше

- живая публикация Instagram (`media_publish`) ещё не реализована;
- локальный HTTP URL не годится для Meta — нужен публичный HTTPS-домен и деплой;
- публичный URL должен быть доступен из интернета (reverse-proxy/домен);
- стратегия кэширования (`MEDIA_PROXY_CACHE_DIR`) — задел на будущее (CDN/кэш);
- реальные метрики внешних API — отдельным этапом.
