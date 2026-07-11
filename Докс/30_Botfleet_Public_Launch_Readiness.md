# 30. Botfleet: готовность к публичному запуску и деплой (v0.3.3)

## 1. Цель документа

Подготовить репозиторий к **безопасному production-деплою**: production-конфиг, Docker
Compose, reverse-proxy/HTTPS, security-readiness, бэкапы, admin-инструменты, legal и
основы мониторинга. Это **foundation**, а не запуск: реальный сервер, боевые платежи и
live-публикации не включаются здесь.

## 2. Что уже готово (предыдущие релизы)

- Auth/session: access/refresh-токены (HMAC), серверные сессии, cookie-auth, CSRF,
  rate limiting, security headers, запрет dev-токена в production (v0.3.2).
- Tenant-изоляция (guards), роли owner/admin/member/viewer, аудит-лог (v0.3.1).
- Billing/units, payments foundation (**mock/sandbox**, `PAYMENTS_LIVE_ENABLED=false`).
- Миграции до `0016_auth_sessions`.

## 3. Что нужно для сервера

- VPS/облако (Linux), Docker + Docker Compose.
- Домен (например `app.botfleet.ru`) и DNS **A/AAAA** на сервер.
- **HTTPS** (Caddy — автоматически; или nginx + certbot).
- **PostgreSQL** (в compose — сервис `db`) и **Redis** (сервис `redis`).
- Регулярные **бэкапы** БД (см. §9).

## 4. Production env

```bash
cp .env.production.example .env.production
# Сгенерировать надёжный AUTH_TOKEN_SECRET:
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Обязательно `true` в production: `AUTH_REQUIRE_AUTH`, `AUTH_COOKIE_SECURE`,
`CSRF_PROTECTION_ENABLED`, `RATE_LIMIT_ENABLED`, `SECURITY_HEADERS_ENABLED`. Обязательно
`false`: `AUTH_ALLOW_DEV_TOKEN`, `PAYMENTS_LIVE_ENABLED`, все `*_LIVE_PUBLISHING_ENABLED`.
`DATABASE_URL` — PostgreSQL. Секреты — только в server env / secret manager, не в Git.

## 5. Docker Compose (prod)

```bash
cp docker-compose.prod.example.yml docker-compose.prod.yml
docker compose -f docker-compose.prod.yml up -d
```

Сервисы: `app` (uvicorn, порт 8000 внутрь), `db` (postgres:16), `redis` (redis:7),
`caddy` (reverse-proxy + авто-HTTPS). Порт приложения наружу не публикуется.

## 6. Caddy / Nginx

- **Caddy** (рекомендуется): `deploy/Caddyfile.example` — автоматический Let's Encrypt.
- **Nginx** (опционально): `deploy/nginx.conf.example` — TLS через certbot вручную.

## 7. Миграции

```bash
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
# или локально: make migrate
```

## 8. Security readiness

```bash
make prod-check                        # exit 0 ok / exit 2 небезопасно
curl -s https://app.botfleet.ru/health/security-readiness   # 200 ok / 503 при ошибках
```

В production приложение **не стартует** с небезопасной auth-конфигурацией (fail-fast).
Endpoint `/health/security-readiness` отдаёт `status/environment/production_ready/checks`
и 503 при фатальных ошибках. `/health` остаётся публичным и простым.

## 9. Backup / restore

```bash
make backup-db                         # backups/botfleet_YYYYMMDD_HHMMSS.dump (pg_dump)
make backup-db dry_run=1               # показать план без выполнения
make restore-db backup_path=backups/... confirm=RESTORE understand=true
```

Пароль БД **не печатается** (передаётся через `PGPASSWORD`). Восстановление требует
`confirm=RESTORE`; в production дополнительно `understand=true`.

## 10. Payments

Только **mock/sandbox**. `PAYMENTS_LIVE_ENABLED=false`. Боевой эквайринг включается
отдельно после аудита sandbox и проверки подписей вебхуков.

## 11. Live publishing

Выключены (`*_LIVE_PUBLISHING_ENABLED=false`) до отдельных платформенных тестов
(Telegram/VK/Instagram). Из UI не включаются.

## 12. Legal

Черновики: `/ui/legal/terms`, `/ui/legal/privacy`, `/ui/legal/offer`,
`/ui/legal/payments`. **Требуется юридическая проверка** перед публичным запуском —
тексты не являются юридической консультацией.

## 13. Monitoring / logging

- **X-Request-ID** на каждый запрос (входящий сохраняется), в заголовке ответа.
- **Access-log**: method/path/status/duration_ms/request_id, секреты редактируются
  (`core/redaction`).
- Уровень логов — `LOG_LEVEL`.
- Планируется: Sentry (ошибки), Prometheus/Grafana (метрики), uptime-проверки, алерты.

## 14. Launch checklist

- [ ] Домен + DNS A/AAAA, HTTPS работает.
- [ ] `.env.production` заполнен, `AUTH_TOKEN_SECRET` надёжный.
- [ ] `make prod-check` → exit 0; `/health/security-readiness` → 200 `production_ready=true`.
- [ ] `alembic upgrade head` применён; бэкап настроен (cron).
- [ ] `PAYMENTS_LIVE_ENABLED=false`, live-публикации off.
- [ ] Legal-документы проверены юристом.
- [ ] Мониторинг/алерты подключены; логи собираются.
- [ ] Admin-пользователь создан (`make admin-create-user`).

## 15. Rollback checklist

- [ ] Остановить новую версию: `docker compose -f docker-compose.prod.yml down`.
- [ ] Восстановить предыдущий образ/тег.
- [ ] При необходимости — restore БД из последнего бэкапа (§9), `confirm=RESTORE`.
- [ ] Проверить `/health` и `/health/security-readiness`.
- [ ] Проверить логи (request_id) на ошибки.

## 16. Платежи перед боевым запуском (v0.3.4)

Платёжный контур подготовлен как sandbox/mock (`PAYMENTS_LIVE_ENABLED=false`,
`PAYMENTS_PROVIDER_HTTP_ENABLED=false`). Детали и полный чек-лист —
[31_Botfleet_Платежи_ЮKassa_СБП_QR.md](31_Botfleet_Платежи_ЮKassa_СБП_QR.md). Перед
включением боевого эквайринга:

- [ ] договор с провайдером (ЮKassa/банк), shop/merchant id;
- [ ] webhook URL (HTTPS) + `YOOKASSA_WEBHOOK_SECRET` и проверка подписи;
- [ ] успешный sandbox-прогон оплаты и вебхука;
- [ ] реализованный боевой HTTP-клиент, затем аккуратно включить
      `PAYMENTS_PROVIDER_HTTP_ENABLED`, потом `PAYMENTS_LIVE_ENABLED`;
- [ ] бухгалтерия/налоги/оферта/privacy/terms/payment policy (вывести из черновиков);
- [ ] мониторинг платежей и алерты по расхождению баланса.
