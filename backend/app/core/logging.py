"""Настройка логирования.

Сложные и необратимые действия (обращения к внешним API, публикация постов)
должны логироваться. Здесь — единая точка конфигурации логгеров.
"""

import logging

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"

_configured = False


def configure_logging(level: int = logging.INFO) -> None:
    """Настроить корневой логгер один раз за время жизни процесса."""
    global _configured
    if _configured:
        return
    logging.basicConfig(level=level, format=_LOG_FORMAT)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Вернуть именованный логгер."""
    return logging.getLogger(name)
