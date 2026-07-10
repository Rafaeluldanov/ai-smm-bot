"""Простой in-memory rate limiter (fixed-window) для local/dev/MVP.

НЕ подходит для распределённого production (несколько процессов не делят состояние) —
для боевого масштабирования нужен Redis-backend. Здесь — потокобезопасный счётчик по
(bucket, key, окно) с TTL-очисткой. Возвращает (allowed, retry_after_seconds).
"""

from __future__ import annotations

import threading
import time

_MAX_KEYS = 50_000


class InMemoryRateLimiter:
    """Потокобезопасный fixed-window счётчик запросов."""

    def __init__(self) -> None:
        self._hits: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()

    def check(self, key: str, limit: int, window: int = 60) -> tuple[bool, int]:
        """Учесть запрос по ключу. Возврат (разрешён, retry_after сек)."""
        if limit <= 0:
            return True, 0
        now = int(time.time())
        window_start = now - (now % window)
        with self._lock:
            bucket = (key, window_start)
            count = self._hits.get(bucket, 0) + 1
            self._hits[bucket] = count
            if len(self._hits) > _MAX_KEYS:
                # Очистка прошлых окон, чтобы память не росла бесконечно.
                self._hits = {k: v for k, v in self._hits.items() if k[1] >= window_start}
            if count > limit:
                return False, window - (now % window)
            return True, 0

    def reset(self) -> None:
        """Сбросить состояние (для тестов)."""
        with self._lock:
            self._hits.clear()


# Глобальный лимитер процесса (для тестов доступен через ``rate_limiter.reset()``).
rate_limiter = InMemoryRateLimiter()
