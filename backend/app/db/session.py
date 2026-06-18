"""Подключение к базе данных и фабрика сессий.

Движок создаётся лениво, чтобы импорт модуля не требовал установленного
драйвера БД и доступного PostgreSQL (важно для Этапа 0 и тестов).
"""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Создать (однократно) и вернуть движок SQLAlchemy."""
    settings = get_settings()
    return create_engine(settings.database_url, pool_pre_ping=True, future=True)


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    """Вернуть фабрику сессий, привязанную к движку."""
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def get_session() -> Iterator[Session]:
    """FastAPI-зависимость: выдать сессию БД и гарантированно закрыть её."""
    factory = get_sessionmaker()
    session = factory()
    try:
        yield session
    finally:
        session.close()
