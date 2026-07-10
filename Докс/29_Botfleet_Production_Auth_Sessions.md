# 29. Botfleet: production auth, сессии, CSRF, rate limiting (v0.3.2)

Документ описывает production-grade auth/session-слой Botfleet: access/refresh-токены,
серверные сессии, cookie-auth, CSRF, rate limiting, security headers, запрет dev-токена в
production, logout/revoke и security-readiness. Живые публикации и реальные платежи
по-прежнему выключены.

## Access-токен

HMAC-SHA256, формат `header.payload.signature` (base64url), сервис
`auth_token_service.py`. Payload access: `sub` (user_id), `typ=access`, `iat`, `exp`,
`jti`, `account_ids`. Проверка постоянного времени + валидация `exp`/`typ`. Некорректный/
просроченный/подделанный токен → `None` (без исключений наружу). Токены не логируются
(есть редакция в `core/redaction.py`). Выдаётся при login/register (тело ответа
`access_token`, TTL `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES`).

## Refresh-токен и серверные сессии

Payload refresh: `sub`, `typ=refresh`, `iat`, `exp`, `jti`, `sid` (session_id). Сессия —
`AuthSession` (миграция **0016**): `session_id` (unique), **`refresh_token_hash`** (в БД
только хеш, не токен), `user_agent`, `ip_address`, `status` (active/revoked/expired),
`last_seen_at`, `expires_at`, `revoked_at`. `auth_session_service.py`:
`create_login_session`, `refresh_session` (ротация + reuse-detection: повторное
использование старого refresh отзывает сессию), `logout_session`, `logout_all`.

## Cookie-auth

Refresh-токен ставится **HttpOnly** cookie `botfleet_refresh` (шлётся автоматически,
используется только `/auth/refresh`). Access-cookie `botfleet_session` ставится только
при `AUTH_COOKIE_AUTH_ENABLED=true` (по умолчанию SPA/тесты используют
`Authorization: Bearer`). CSRF-cookie `botfleet_csrf` (не HttpOnly — фронтенд читает) —
при включённом CSRF. Флаги: `Secure` (в production всегда), `SameSite` (lax по умолчанию),
`HttpOnly`.

## CSRF (double-submit cookie)

Middleware `CSRFMiddleware`. Проверяется только для небезопасных методов
(POST/PUT/PATCH/DELETE), только при `CSRF_PROTECTION_ENABLED` (в production — всегда) и
наличии csrf-cookie (cookie-auth). Клиент шлёт `X-CSRF-Token`, значение должно совпасть с
cookie. **Освобождены**: `Authorization: Bearer`-клиенты (нет cookie-контекста), вебхуки
`/billing/webhooks/*`, OAuth-callback `*/oauth/callback`, bootstrap `/auth/login|register|
refresh`. Безопасные методы (GET/HEAD/OPTIONS) не проверяются.

## Rate limiting

In-memory fixed-window (`core/rate_limit.py`) — MVP для local/dev; для распределённого
production нужен **Redis-backend** (TODO). Middleware `RateLimitMiddleware`, при
`RATE_LIMIT_ENABLED` (в production — всегда). Buckets: `/auth/*` →
`RATE_LIMIT_AUTH_PER_MINUTE` (10), `/billing/*` → `RATE_LIMIT_PAYMENT_PER_MINUTE` (30),
`/saas|/analytics|/integrations|/audit/*` → `RATE_LIMIT_API_PER_MINUTE` (120). Ключ:
Authorization / X-Forwarded-For / client IP. Превышение → **429** с `Retry-After`.

## Security headers

Middleware `SecurityHeadersMiddleware` (при `SECURITY_HEADERS_ENABLED=true`, по
умолчанию): `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
strict-origin-when-cross-origin`, `Permissions-Policy: geolocation=(), microphone=(),
camera=()`, `Content-Security-Policy` (`default-src 'self'`, `script/style 'unsafe-inline'`,
`img 'self' data: https:`, `connect 'self'`). **HSTS** — только в production/secure
(`max-age=31536000; includeSubDomains`).

## Запрет dev-токена в production

`deps.get_current_user`/`get_optional_user` разрешают access-токен (Bearer/cookie), а
dev-токен (`make_dev_token`) — только при `auth_allow_dev_token_effective`
(`AUTH_ALLOW_DEV_TOKEN=true` и **не** production). В production dev-токен → 401 (как
анонимный). Ответ не раскрывает существование пользователя.

## logout / logout-all / revoke

- `POST /auth/logout` — ревокирует текущую сессию (по refresh-cookie), чистит cookies,
  аудит `user.logout`.
- `POST /auth/logout-all` — ревокирует все сессии пользователя, аудит `user.logout_all`.
- `GET /auth/sessions` — список активных сессий (без хешей токенов).
- Аудит: `user.registered`, `user.login`, `user.logout`, `user.refresh`,
  `user.logout_all`, `user.session.revoked`.

## security-readiness endpoint

`GET /health/security-readiness` — строгий чек-лист (auth_token_secret_configured,
require_auth, dev_token_allowed, secure_cookies, csrf, rate_limit, headers, audit,
payments_live). В production при фатальных ошибках → **503**; в local → **200** (с
warnings). `/health` остаётся публичным и простым. Плюс: приложение **не стартует** в
production при небезопасной auth-конфигурации (`production_security_errors`).

## Env-переменные

`AUTH_TOKEN_SECRET`, `AUTH_ACCESS_TOKEN_EXPIRE_MINUTES=30`,
`AUTH_REFRESH_TOKEN_EXPIRE_DAYS=30`, `AUTH_SESSION_COOKIE_NAME=botfleet_session`,
`AUTH_REFRESH_COOKIE_NAME=botfleet_refresh`, `AUTH_COOKIE_SECURE=false`,
`AUTH_COOKIE_SAMESITE=lax`, `AUTH_COOKIE_HTTPONLY=true`, `AUTH_COOKIE_AUTH_ENABLED=false`,
`AUTH_ALLOW_DEV_TOKEN=true`, `AUTH_REQUIRE_AUTH=false`, `CSRF_PROTECTION_ENABLED=false`,
`CSRF_COOKIE_NAME=botfleet_csrf`, `RATE_LIMIT_ENABLED=false`,
`RATE_LIMIT_AUTH_PER_MINUTE=10`, `RATE_LIMIT_API_PER_MINUTE=120`,
`RATE_LIMIT_PAYMENT_PER_MINUTE=30`, `SECURITY_HEADERS_ENABLED=true`.

## Local vs production

| Аспект | local/dev | production |
|---|---|---|
| dev-токен | принимается | **запрещён** (401) |
| анонимный доступ к защищённым | back-compat (guards) | **401** |
| AUTH_TOKEN_SECRET | dev-фолбэк | **обязателен** и надёжен (иначе падение/503) |
| cookies Secure | false | **true** |
| CSRF | по флагу | **включён** |
| rate limiting | по флагу | **включён** |
| HSTS | нет | **есть** |

## Что осталось перед public launch

- Реальный домен + HTTPS/TLS; secure cookie domain.
- **Redis rate limiter** вместо in-memory (масштабирование на несколько процессов).
- При желании — «настоящий» JWT/JWK (сейчас — совместимый HMAC-формат).
- Отдельная админ-панель; CSRF-стратегия при полном cookie-auth в SPA.
- Юридические документы (terms/privacy/оферта), мониторинг/алерты, бэкапы.
- Sandbox платёжного провайдера до включения `PAYMENTS_LIVE_ENABLED=true`.
