"""Middleware безопасности: security headers, CSRF-защита, rate limiting.

Все три управляются флагами конфига и по умолчанию не мешают local-разработке/тестам:
- security headers — включены по умолчанию (безвредны для тел ответов);
- CSRF — только при ``csrf_enabled_effective`` и cookie-auth (Bearer-клиенты освобождены);
- rate limiting — только при ``rate_limit_enabled_effective`` (в production — всегда).

Настройки читаются per-request через ``get_settings()``, поэтому тесты могут менять их
через окружение + ``get_settings.cache_clear()``.
"""

from __future__ import annotations

import secrets
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings, get_settings
from app.core.rate_limit import rate_limiter

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
# Пути, освобождённые от CSRF (внешние вызовы + bootstrap авторизации).
_CSRF_EXEMPT_EXACT = {"/auth/login", "/auth/register", "/auth/refresh"}
_CSRF_EXEMPT_PREFIXES = ("/billing/webhooks/",)

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "connect-src 'self'"
)

Handler = Callable[[Request], Awaitable[Response]]


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Добавляет заголовки безопасности (при SECURITY_HEADERS_ENABLED)."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        response = await call_next(request)
        settings = get_settings()
        if not settings.security_headers_enabled:
            return response
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        headers.setdefault("Content-Security-Policy", _CSP)
        # HSTS — только когда HTTPS (production или secure-cookie).
        if settings.is_production or settings.secure_cookies_effective:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """CSRF-защита для cookie-auth (double-submit cookie).

    Проверяет только небезопасные методы, только при включённом CSRF и наличии
    csrf-cookie (cookie-auth). Bearer-клиенты (Authorization) и вебхуки/oauth-callback
    освобождены — у них нет cookie-контекста.
    """

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        settings = get_settings()
        if settings.csrf_enabled_effective and request.method in _UNSAFE_METHODS:
            path = request.url.path
            exempt = (
                path in _CSRF_EXEMPT_EXACT
                or path.endswith("/oauth/callback")
                or any(path.startswith(p) for p in _CSRF_EXEMPT_PREFIXES)
            )
            has_bearer = bool(request.headers.get("authorization"))
            csrf_cookie = request.cookies.get(settings.csrf_cookie_name)
            if not exempt and not has_bearer and csrf_cookie:
                header = request.headers.get("x-csrf-token") or ""
                if not header or not secrets.compare_digest(header, csrf_cookie):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF-токен отсутствует или неверен"},
                    )
        return await call_next(request)


def _rate_bucket(path: str, settings: Settings) -> tuple[str, int] | None:
    """Определить (имя bucket, лимит/мин) по пути, или None (без лимита)."""
    if path.startswith("/auth/"):
        return "auth", settings.rate_limit_auth_per_minute
    if path.startswith("/billing/"):
        return "payment", settings.rate_limit_payment_per_minute
    if path.startswith(("/saas/", "/analytics/", "/integrations/", "/audit/")):
        return "api", settings.rate_limit_api_per_minute
    return None


class RateLimitMiddleware(BaseHTTPMiddleware):
    """In-memory rate limiting (при RATE_LIMIT_ENABLED / production)."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        settings = get_settings()
        if settings.rate_limit_enabled_effective:
            bucket = _rate_bucket(request.url.path, settings)
            if bucket is not None:
                name, limit = bucket
                ident = (
                    request.headers.get("authorization")
                    or request.headers.get("x-forwarded-for")
                    or (request.client.host if request.client else "anon")
                )
                allowed, retry_after = rate_limiter.check(f"{name}:{ident}", limit)
                if not allowed:
                    return JSONResponse(
                        status_code=429,
                        content={"detail": "Слишком много запросов, попробуйте позже"},
                        headers={"Retry-After": str(retry_after)},
                    )
        return await call_next(request)
