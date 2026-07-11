"""Middleware наблюдаемости: X-Request-ID и структурный access-log.

Без внешних сервисов (Sentry/Prometheus добавляются позже). Access-log редактирует
секреты (query ``access_token=``, ``token=`` и т. п.) через ``core.redaction`` и не
логирует тела запросов. Каждому запросу присваивается ``request_id`` (или берётся
входящий ``X-Request-ID``) и добавляется в заголовок ответа.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import get_logger
from app.core.redaction import redact_sensitive_text

# Публичный media-токен в пути (/media/public/<token>) — маскируем в access-log.
_MEDIA_TOKEN_RE = re.compile(r"/media/public/[^/?\s]+")

logger = get_logger("botfleet.access")

_REQUEST_ID_HEADER = "X-Request-ID"
Handler = Callable[[Request], Awaitable[Response]]


def _new_request_id() -> str:
    return uuid.uuid4().hex


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Присвоить/пробросить X-Request-ID (в request.state и заголовок ответа)."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        incoming = request.headers.get(_REQUEST_ID_HEADER)
        request_id = incoming.strip() if incoming and incoming.strip() else _new_request_id()
        # Санитизируем длину/символы входящего id (защита от log-injection).
        request_id = redact_sensitive_text(request_id)[:64]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers[_REQUEST_ID_HEADER] = request_id
        return response


class AccessLogMiddleware(BaseHTTPMiddleware):
    """Логировать method/path/status/duration/request_id (с редакцией секретов)."""

    async def dispatch(self, request: Request, call_next: Handler) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        request_id = getattr(request.state, "request_id", "-")
        # Полный путь с query, но с замазанными секретами.
        raw_path = request.url.path
        if request.url.query:
            raw_path = f"{raw_path}?{request.url.query}"
        safe_path = redact_sensitive_text(raw_path)
        # Публичный media-токен (сегмент пути) не логируем целиком.
        safe_path = _MEDIA_TOKEN_RE.sub("/media/public/***", safe_path)
        logger.info(
            "access method=%s path=%s status=%s duration_ms=%s request_id=%s",
            request.method,
            safe_path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response
