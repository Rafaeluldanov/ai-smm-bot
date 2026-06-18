"""Общие фикстуры pytest.

Тесты используют изолированную базу SQLite в памяти, поэтому ``make check``
не зависит от запущенного PostgreSQL/Docker. На каждый тест создаётся свежая
схема (через ``Base.metadata.create_all``) и удаляется после.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  -- регистрирует все модели в Base.metadata
from app.api.deps import get_db
from app.db.base import Base
from app.main import app


@pytest.fixture
def db_engine() -> Iterator[Engine]:
    """Свежий движок SQLite в памяти со всеми таблицами."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    try:
        yield engine
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def session_factory(db_engine: Engine) -> sessionmaker[Session]:
    """Фабрика сессий, привязанная к тестовому движку."""
    return sessionmaker(bind=db_engine, autoflush=False, autocommit=False, future=True)


@pytest.fixture
def db_session(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Сессия БД для прямых тестов репозитория."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(session_factory: sessionmaker[Session]) -> Iterator[TestClient]:
    """TestClient с переопределённой зависимостью БД на тестовую сессию."""

    def override_get_db() -> Iterator[Session]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
