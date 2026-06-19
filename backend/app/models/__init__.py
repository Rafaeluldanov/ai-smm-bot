"""SQLAlchemy-модели. Импорт здесь регистрирует их в общих метаданных Base."""

from app.db.base import Base
from app.models.autonomous_run import AutonomousRun
from app.models.autonomous_run_step import AutonomousRunStep
from app.models.external_image_candidate import ExternalImageCandidate
from app.models.media_asset import MediaAsset
from app.models.media_asset_variant import MediaAssetVariant
from app.models.post import Post
from app.models.post_analytics_snapshot import PostAnalyticsSnapshot
from app.models.post_publication import PostPublication
from app.models.post_review_action import PostReviewAction
from app.models.project import Project
from app.models.topic import Topic

__all__ = [
    "AutonomousRun",
    "AutonomousRunStep",
    "Base",
    "ExternalImageCandidate",
    "MediaAsset",
    "MediaAssetVariant",
    "Post",
    "PostAnalyticsSnapshot",
    "PostPublication",
    "PostReviewAction",
    "Project",
    "Topic",
]
