# 60. Botfleet: Telegram live production runbook (v0.6.3)

Первый безопасный **production-ready** Telegram autopost flow. Клиентский «запуск Telegram
автопилота»: проверить готовность, собрать preview тестового поста и сделать **один ручной
production-тест** — под всеми safety-gates. Runbook сам live не включает; реальная отправка
делегируется существующему [TelegramLiveRolloutService](57_Botfleet_Telegram_Live_Rollout.md).

> **Это НЕ включатель live и НЕ обход safety-gates.** Реальная публикация **невозможна** без
> глобального ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` (админ). Runbook лишь агрегирует готовность и
> делегирует отправку под всеми гейтами. По умолчанию ``TELEGRAM_RUNBOOK_DRY_RUN=true``,
> подтверждение ``ENABLE_TELEGRAM_LIVE`` обязательно. В тестах реальной сети/публикаций нет (только
> fake-клиент); env не меняется.

## Первый production-канал — Telegram

Telegram технически проще прочих (групповой бот-токен постит текст и изображения без OAuth), поэтому
это первый реальный канал, на котором обкатывается весь production-flow: чек-лист → preview →
подтверждение → одна реальная публикация → журнал → мониторинг.

## Checklist готовности

``TelegramLiveRunbookService.build_checklist`` агрегирует 6 пунктов (переиспользуя существующие
проверки, не дублируя их):

| Пункт | Источник |
|---|---|
| Telegram канал | ``PlatformConnectionService.get_connection`` (connected + токен + channel_id) |
| Media Proxy | ``MediaProxyService.validate_public_base_url`` (enabled + без ошибок) |
| Календарь | ``LiveReadinessService.run_project_readiness_check`` → checklist.calendar |
| Баланс | тот же readiness → checklist.balance |
| Готовность к публикации | ``build_effective_live_gate`` → readiness_ready |
| Мониторинг | ``LIVE_AUTOPILOT_MONITORING_ENABLED`` |

Статус runbook: ``draft`` → ``ready`` (чек-лист пройден) → ``enabled`` (все гейты + allow_real_send)
/ ``blocked`` (есть блокеры) / ``paused``. Результат сохраняется в ``TelegramLiveRunbook`` при
``POST .../check``.

## Preview тестового поста (без отправки)

``prepare_test_post`` берёт пост (указанный или последний проекта), через
``PostPublicationService.preview_publication`` (dry-run) достаёт текст/хэштеги/media_asset_id, а
через ``MediaProxyService.build_social_media_url`` — публичную ссылку доставки. Создаётся
``TelegramLiveRunAttempt`` (status=preview). Ничего не отправляется; в payload сохраняется только
**маскированный** media_url (без raw-токена).

## Условия реальной отправки (все обязательны)

Реальная публикация сработает **только если ВСЕ** true (проверяет делегат, а не runbook):

1. глобальный ``TELEGRAM_LIVE_PUBLISHING_ENABLED`` (админ);
2. ``project_live_enabled`` ([56](56_Botfleet_Live_Autopost_Readiness.md));
3. ``platform_live_enabled`` (Telegram);
4. ``full_auto_live_enabled``;
5. ``readiness_ready``;
6. ``TELEGRAM_LIVE_ROLLOUT_ALLOW_REAL_SEND`` (rollout kill-switch);
7. подтверждение ``ENABLE_TELEGRAM_LIVE``;
8. существующие safety-gates ``PostPublicationService`` (баланс/креды/would_send).

``confirm_live_publish`` показывает, разрешено ли (без отправки). ``publish_test_post`` делегирует
``TelegramLiveRolloutService.publish_once_if_allowed`` — та создаёт технический ``LivePublishAttempt``,
проверяет ВСЕ гейты и делает реальную отправку; runbook лишь оборачивает результат клиентской записью
``TelegramLiveRunAttempt`` (preview/blocked/sending/published/failed + external_post_id/url/error).

## Как проходит первый production publish

```
build_checklist → всё зелёное (status=enabled)
   ↓
prepare_test_post → preview (text/media_url/hashtags), TelegramLiveRunAttempt=preview
   ↓
publish_test_post(confirmation=ENABLE_TELEGRAM_LIVE)
   ↓ delegate
TelegramLiveRolloutService.publish_once_if_allowed  → все гейты → PostPublicationService.publish_post
   ↓
LivePublishAttempt=published (external_post_id/url)  →  TelegramLiveRunAttempt=published
   ↓ автоматически
Monitoring (читает LivePublishAttempt) · Learning/Analytics (через pipeline публикации)
```

## Мониторинг / learning / analytics

Ничего проталкивать не нужно: реальная попытка создаёт ``LivePublishAttempt``, который
``LiveAutopilotMonitoringService.run_health_check`` [v0.6.1](58_Botfleet_Live_Autopilot_Monitoring.md)
агрегирует автоматически. Runbook дополнительно обновляет снимок здоровья (best-effort).
Learning/analytics питаются через существующий pipeline публикации.

## Rollback / пауза

``pause_runbook`` ставит runbook в ``paused`` — production-тест блокируется до следующей проверки
готовности. Для полной остановки live-публикации используется стоп-кран мониторинга
([58](58_Botfleet_Live_Autopilot_Monitoring.md)) и/или выключение глобального флага админом.

## API

Под ``require_project_access``:
- ``GET /projects/{id}/telegram-runbook`` — дашборд (чек-лист/статус/история);
- ``POST /projects/{id}/telegram-runbook/check`` — проверка + сохранение чек-листа;
- ``POST /projects/{id}/telegram-runbook/preview`` — preview тестового поста;
- ``POST /projects/{id}/telegram-runbook/publish-test`` — ручной production-тест (подтверждение в теле);
- ``POST /projects/{id}/telegram-runbook/pause`` — пауза.

UI: ``/ui/projects/{id}/telegram-runbook`` («Запуск Telegram автопилота»).

## Данные

Модели ``TelegramLiveRunbook`` (готовность проекта) + ``TelegramLiveRunAttempt`` (журнал тестов),
миграция **``0045_telegram_live_runbook``** (down_revision ``0044_media_proxy_layer``). Секретов/сырых
токенов/payload не хранит; SQLite+PostgreSQL.

## Настройки (безопасные дефолты)

```
TELEGRAM_RUNBOOK_ENABLED=true
TELEGRAM_RUNBOOK_DRY_RUN=true
# Гейты реальной отправки — существующие (по умолчанию всё выключено):
TELEGRAM_LIVE_PUBLISHING_ENABLED=false
TELEGRAM_LIVE_ROLLOUT_ALLOW_REAL_SEND=false
```

## CLI

```
make telegram-runbook-check project_id=1
make telegram-runbook-preview project_id=1 [post_id=1]
make telegram-runbook-publish-test project_id=1 confirmation=ENABLE_TELEGRAM_LIVE [dry_run=true]
```
