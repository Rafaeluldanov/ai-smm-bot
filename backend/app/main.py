"""Точка входа FastAPI-приложения."""

from fastapi import FastAPI

from app.api.analytics import router as analytics_router
from app.api.autonomous_runs import router as autonomous_runs_router
from app.api.external_images import router as external_images_router
from app.api.health import router as health_router
from app.api.media_assets import router as media_assets_router
from app.api.post_publications import router as post_publications_router
from app.api.post_reviews import router as post_reviews_router
from app.api.posts import router as posts_router
from app.api.projects import router as projects_router
from app.api.topics import router as topics_router
from app.config import get_settings
from app.core.logging import configure_logging, get_logger


def create_app() -> FastAPI:
    """Сконфигурировать и вернуть экземпляр FastAPI."""
    configure_logging()
    settings = get_settings()
    logger = get_logger(__name__)

    app = FastAPI(
        title="AI-SMM-бот",
        version="0.1.0",
        summary="Автоматическое ведение соцсетей проектов компании",
    )
    app.include_router(health_router)
    app.include_router(projects_router)
    app.include_router(media_assets_router)
    app.include_router(topics_router)
    app.include_router(posts_router)
    app.include_router(post_reviews_router)
    app.include_router(post_publications_router)
    app.include_router(analytics_router)
    app.include_router(external_images_router)
    app.include_router(autonomous_runs_router)

    logger.info("Приложение инициализировано (env=%s)", settings.app_env)
    return app


app = create_app()
