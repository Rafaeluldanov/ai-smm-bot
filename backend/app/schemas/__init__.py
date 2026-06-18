"""Pydantic-схемы запросов/ответов API."""

from app.schemas.media_asset import MediaAssetBase, MediaAssetCreate, MediaAssetRead
from app.schemas.post import PostBase, PostCreate, PostRead
from app.schemas.project import ProjectBase, ProjectCreate, ProjectRead
from app.schemas.topic import TopicBase, TopicCreate, TopicRead

__all__ = [
    "MediaAssetBase",
    "MediaAssetCreate",
    "MediaAssetRead",
    "PostBase",
    "PostCreate",
    "PostRead",
    "ProjectBase",
    "ProjectCreate",
    "ProjectRead",
    "TopicBase",
    "TopicCreate",
    "TopicRead",
]
