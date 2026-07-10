# 28. Botfleet SaaS: безопасность (v0.3.1)

Документ описывает модель безопасности публичной SaaS-платформы Botfleet: tenant-
изоляцию, владение аккаунтами/проектами, роли, маскирование секретов, защиту платных
действий, идемпотентность, безопасность счетов/вебхуков, аудит-лог и чек-лист перед
публичным запуском.

> Все опасные операции по-прежнему выключены: live-публикации off, боевые платежи off
> (`PAYMENTS_LIVE_ENABLED=false`), реальные внешние вызовы не выполняются.

## Tenant-изоляция (HTTP guards)

Гарды — `backend/app/api/security_guards.py`, поверх `saas_security_service`. Модель
**двухуровневая**:

- **Аутентифицированный** запрос (валидный dev-токен в `Authorization`) проверяется
  строго: пользователь должен быть владельцем/участником аккаунта ресурса. Чужой
  аккаунт/проект/счёт/ресурс → **404** (существование чужих ресурсов не раскрывается).
- **Анонимный** запрос допускается только вне production (dev/local) — сохраняется
  back-compat для существующих тестов и локальной разработки. В production (или при
  `SECURITY_REQUIRE_AUTH=true`) анонимный доступ к защищённым роутам → **401**.

Подключённые гарды по роутам:

| Область | Роут | Гард |
|---|---|---|
| SaaS | `GET /saas/accounts/{id}/projects` | `require_account_member` |
| SaaS | `POST /saas/onboarding/preview`,`apply` | `guard_account_in_body` |
| SaaS | `GET /saas/projects/{id}/dashboard` | `require_project_access` |
| SaaS | `POST /saas/projects/{id}/run-dry`,`run-semi-auto` | `require_project_access` + `guard_account_in_body` |
| Billing | `balance`,`ledger`,`usage-events`,`invoices`,`topup/preview` | `require_account_member` |
| Billing | `manual-topup`, `PUT profile` | `require_account_owner_or_admin` |
| Billing | `GET invoices/{id}`, `mock-pay` | `require_invoice_access` |
| Billing | `POST /billing/estimate` (при account_id) | `guard_account_in_body` |
| Billing | `POST /billing/webhooks/{provider}` | **без user-гарда** (подпись/идемпотентность) |
| Analytics | `projects/{id}/*` | `require_project_access` |
| Analytics | `posts/{id}/card`,`performance`,`manual-metrics` | `require_post_access` |
| Analytics | `accounts/{id}/preview`,`run-dry`,`run` | `require_account_member` + `guard_project_in_body` |
| Audit | `GET /audit/account/{id}` | `require_account_member` |
| Integrations | `GET /integrations/vk/status`, `POST /oauth/check` | `require_vk_resource_access` |
| Integrations | `/oauth/start`,`/oauth/callback` | signed `state` (не dev-токен) |

## Владение и роли

- `Account.owner_user_id` + `AccountMembership(account_id, user_id, role, status)`.
- Роли: **owner / admin / manager(member) / viewer**. Изменение billing-профиля и
  ручное пополнение — только `owner`/`admin` (`require_account_owner_or_admin`). Чтение
  баланса/леджера/аналитики — любой участник аккаунта.
- `Project.account_id` привязывает проект к аккаунту. Legacy/seed-проекты с
  `account_id=None` в production скрыты (`SECURITY_HIDE_LEGACY_PROJECTS_IN_PROD=true`),
  в dev — доступны.

## Маскирование секретов (no secret in HTML/API/log)

- CRM-ресурсы: `api_key_encrypted` **никогда** не в ответах — только `api_key_present`
  и `api_key_masked`. Сырой `api_key` — write-only.
- Дашборд/платформы: токен — только «сохранён/нет» + маска, никогда полное значение.
- OAuth callback: access_token не в HTML/логах; `state` подписан HMAC и не содержит
  секретов.
- Платёжные вебхуки: `payload_sanitized` / `raw_payload_sanitized` — без секретов и
  подписей.
- **Редакция логов/метаданных** — `backend/app/core/redaction.py`:
  `redact_sensitive_text(text)` замазывает `access_token=`, `api_key=`, `secret=`,
  `password=`, `Authorization: Bearer …`, VK `vk1.`, Meta `EAAG…`, Telegram bot-token,
  YooKassa `live_`/`test_`; `sanitize_metadata(dict)` вырезает значения под секретными
  ключами рекурсивно.

## Live flags

Все выключены по умолчанию и не включаются из UI:
`TELEGRAM_LIVE_PUBLISHING_ENABLED=false`, `VK_LIVE_PUBLISHING_ENABLED=false`,
`INSTAGRAM_LIVE_PUBLISHING_ENABLED=false`, `PAYMENTS_LIVE_ENABLED=false`. В UI —
индикаторы безопасности (`/ui/settings`, `/ui/billing`).

## Защита платных действий (paid-action guards)

Единый API в `BillingService`:
- `ensure_balance(account_id, units)` — проверка баланса;
- `debit_for_action(account_id, units, usage_type, idempotency_key, metadata)` —
  списание за действие (идемпотентно, не в минус; уважает `PAID_ACTIONS_ENFORCED`);
- `credit_payment(account_id, units, provider_payment_id, idempotency_key)` — зачисление
  после оплаты (один раз);
- `refund_or_compensate(account_id, units, reason, idempotency_key)` — компенсация.

Правила: dry-run/preview и ручной ввод метрик — **бесплатно (0 units)**; недостаток
баланса → `InsufficientBalanceError` (HTTP **402**), действие не выполняется; успех
списывает один раз; повтор с тем же `idempotency_key` не списывает дважды; неуспех не
списывает. Платные действия: `post_generation`, `post_publication`, `post_analytics`,
`schedule_generation`, `media_processing`, `payment_invoice_topup`.

## Безопасность счетов и вебхуков (idempotency)

- Создание счёта **не** меняет баланс; баланс пополняется только после `paid`
  (mock-pay/webhook), один раз (идемпотентность по `invoice-{id}-paid`).
- Дубликат mock-pay/вебхука не пополняет дважды; неуспешный/отменённый счёт не
  пополняет. Неизвестный провайдер → ошибка; недоверенная подпись → не обрабатывается;
  payload логируется санитизированным.

## Аудит-лог

`AuditLogEntry` (миграция **0015**), сервис `audit_log_service.py`, API
`GET /audit/account/{account_id}` (guard `require_account_member`). Действия:
`user.registered`, `user.login`, `project.*`, `platform.*`, `schedule.*`,
`analytics.run`, `billing.invoice.created/paid`, `billing.balance.debited/credited`,
`oauth.connected/failed`. Метаданные санитизируются; аудит **не роняет** основное
действие (при `AUDIT_LOG_ENABLED=false` — пропуск, ошибки проглатываются). Чужой аудит
недоступен (404). Записывается для register/login/invoice-created/invoice-paid/
analytics-run (IP/User-Agent — из запроса для auth).

## Конфиг безопасности

`AUTH_TOKEN_SECRET`, `AUDIT_LOG_ENABLED=true`,
`SECURITY_HIDE_LEGACY_PROJECTS_IN_PROD=true`, `PAID_ACTIONS_ENFORCED=true`,
`SECURITY_REQUIRE_AUTH=false`, `PAYMENTS_LIVE_ENABLED=false`. Свойства `Settings`:
`is_production`, `audit_log_enabled`, `security_hide_legacy_projects_in_prod`,
`paid_actions_enforced`, `security_require_auth`.

## Production checklist (перед публичным запуском)

- [ ] HTTPS only (TLS, HSTS).
- [ ] Сильный `AUTH_TOKEN_SECRET`; **dev-токен запрещён** в production.
- [ ] Реальная сессия/JWT вместо dev-токена (`<id>.<hmac>` — только заглушка).
- [ ] Secure/HttpOnly cookie или Authorization-заголовок; **CSRF-стратегия** при cookie.
- [ ] `SECURITY_REQUIRE_AUTH=true` (форс авторизации), `APP_ENV=production`.
- [ ] Rate limiting (на аккаунт/IP), лимиты платных действий и отчётов в день.
- [ ] Проверка подписи вебхуков реальных провайдеров.
- [ ] Sandbox платёжного провайдера до включения `PAYMENTS_LIVE_ENABLED=true`; аудит.
- [ ] Редакция логов (`core/redaction`) на всех точках логирования.
- [ ] Бэкапы БД, миграции применены (`alembic upgrade head`).
- [ ] Отделённая админ-панель; мониторинг и алерты.
- [ ] Юридическое: terms / privacy / оферта платежей.

## Обновление v0.3.2: production auth / сессии / CSRF / rate limiting

Dev-токен заменён на production-grade слой: access/refresh-токены (HMAC), серверные
сессии (`AuthSession`, миграция 0016, в БД только хеш refresh), cookie-auth, CSRF
(double-submit), rate limiting (in-memory), security headers (CSP/HSTS). В production
dev-токен запрещён, `AUTH_TOKEN_SECRET` обязателен, cookies Secure, авторизация
обязательна — иначе приложение не стартует / `/health/security-readiness` → 503.
logout/logout-all ревокируют сессии; аудит login/logout/refresh. Подробно —
[29_Botfleet_Production_Auth_Sessions.md](29_Botfleet_Production_Auth_Sessions.md).
