# 23. Telegram-пост с фотоальбомом из Яндекс Диска (v0.1.15)

Расширение медиа-пайплайна (см. [22_Группировка_медиа_и_VK_посты.md](./22_Группировка_медиа_и_VK_посты.md))
на Telegram: тот же пост с группой медиа публикуется в канал одним фотоальбомом
через `sendMediaGroup`. Всё офлайн-детерминированно; живая публикация — только
вручную и только под флагом.

## Канал уже подключён

Канал `@teeon_merch` подключён и проверен (бот — администратор с правом
`can_post_messages`). Токен хранится в `.env` (`TELEGRAM_BOT_TOKEN`) и НИКОГДА не
логируется, не попадает в `raw` ответа и в тексты ошибок.

## Схема

```
group (общий тег)  →  create post (текст + SEO-ссылка + группа медиа)
        →  dry-run preview (media_kind/media_count/would_attach_media)
        →  publish telegram (вручную, TELEGRAM_LIVE_PUBLISHING_ENABLED=true)
```

`PostPublicationService.build_publish_request` кладёт `media_items` в payload для
ЛЮБОЙ платформы (не только VK), поэтому Telegram-клиент видит ту же группу медиа.

## Как отправляется

- **2–10 фото → `sendMediaGroup`.** `media` — JSON-массив
  `[{"type":"photo","media":"attach://photo0","caption":<текст>}, {"type":"photo","media":"attach://photo1"}, …]`,
  файлы прикладываются как `photo0..photoN` (multipart). **Caption — только в
  первом элементе** альбома (остальные без подписи).
- **Ровно одно фото → `sendPhoto`** (multipart `photo` + `caption`).
- Лимит фото в альбоме — `TELEGRAM_MEDIA_GROUP_MAX_PHOTOS` (по умолчанию 10;
  Telegram допускает до 10). Лишние фото отсекаются с предупреждением.
- **Видео пока не загружается**: пропускается с предупреждением
  `Telegram video upload is not implemented; video skipped`; фото и текст уходят.
- **HEIC/HEIF → JPEG в памяти** (Pillow / `ImageEnhancementProcessor`) перед
  отправкой; оригинал на диске не перезаписывается.
- Источник байтов: локальная enhanced-копия (`media_path`) либо публичная папка
  Яндекс Диска (`public://yandex/...`) через `MediaDownloadService`.

## Фолбэки и безопасность

- Если все фото недоступны (не скачались / только видео) — публикуется текст
  (`sendMessage`), а в `raw`: `media_upload_skipped=true` + `media_warnings`.
- `live_enabled=false` (`TELEGRAM_LIVE_PUBLISHING_ENABLED`) останавливает ДО любых
  сетевых вызовов — `PublishError` без сети.
- Ошибка Bot API (`ok:false`) или HTTP ≥ 400 → `PublishError` (без токена).
- `raw` ответа содержит: `media_source`, `media_kind`, `media_count`,
  `attached_photos_count`, `media_warnings`.

## Dry-run preview

`publish_post --dry-run` (или `preview_publication`) для Telegram показывает:
`media_kind` (image/image_group/video/mixed/none), `media_count`,
`would_attach_media`, `media_asset_ids`. Ничего не отправляет.

## Ручной прогон (ничего не публикуется автоматически)

```bash
make media-group-post project_slug=teeon tag=футболка
export POST_ID=<new_id>
python -m app.scripts.review_post --post-id "$POST_ID" --action approve --comment "Telegram media test"
python -m app.scripts.schedule_post --post-id "$POST_ID" --platform telegram
# Dry-run превью (без сети):
TELEGRAM_LIVE_PUBLISHING_ENABLED=true VK_LIVE_PUBLISHING_ENABLED=false \
  python -m app.scripts.publish_post --post-id "$POST_ID" --platform telegram --dry-run
# Только после dry-run — живая публикация ОДНОГО поста:
TELEGRAM_LIVE_PUBLISHING_ENABLED=true VK_LIVE_PUBLISHING_ENABLED=false \
  python -m app.scripts.publish_post --post-id "$POST_ID" --platform telegram
```

> `publish-due` не использовать. Старые опубликованные посты не трогать. Живую
> публикацию делать только вручную, по одному посту, после dry-run.

## Общий код

Загрузка байтов медиа и конвертация HEIC/HEIF вынесены в общий модуль
`backend/app/integrations/media_attachments.py` и используются и VK-, и
Telegram-клиентом (единый источник правды, без дублирования).

Telegram — часть общей мультиплатформенной архитектуры (VK/Telegram/Instagram/
YouTube/RuTube). Матрица возможностей и capability-слой —
[24_Мультиплатформенная_публикация_медиа.md](24_Мультиплатформенная_публикация_медиа.md).
