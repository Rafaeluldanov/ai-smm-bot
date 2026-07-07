"""CRM Bot SMM Configurator: конфиг, ресурсы, ключи, источники, категории, планы

Revision ID: 0011_crm_bot_smm_configurator
Revises: 0010_media_asset_variants
Create Date: 2026-07-07

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_crm_bot_smm_configurator"
down_revision: str | None = "0010_media_asset_variants"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
    """JSON-тип: JSONB на PostgreSQL, JSON на прочих СУБД."""
    return sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )


def upgrade() -> None:
    op.create_table(
        "crm_bot_project_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("crm_external_id", sa.String(length=255), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("website_url", sa.String(length=512), nullable=True),
        sa.Column("has_website", sa.Boolean(), nullable=False),
        sa.Column("manual_topics", _json(), nullable=False),
        sa.Column("reference_sites", _json(), nullable=False),
        sa.Column("business_description", sa.Text(), nullable=False),
        sa.Column("geography", _json(), nullable=False),
        sa.Column("brand_tone", sa.String(length=255), nullable=False),
        sa.Column("forbidden_phrases", _json(), nullable=False),
        sa.Column("required_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_bot_project_configs_project_id", "crm_bot_project_configs", ["project_id"]
    )
    op.create_index(
        "ix_crm_bot_project_configs_crm_external_id",
        "crm_bot_project_configs",
        ["crm_external_id"],
    )
    op.create_index("ix_crm_bot_project_configs_status", "crm_bot_project_configs", ["status"])

    op.create_table(
        "crm_smm_resources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("resource_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("api_key_masked", sa.String(length=64), nullable=True),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("yandex_public_url", sa.String(length=512), nullable=True),
        sa.Column("yandex_root_folder", sa.String(length=255), nullable=True),
        sa.Column("tags", _json(), nullable=False),
        sa.Column("keywords", _json(), nullable=False),
        sa.Column("live_enabled", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["crm_bot_project_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_smm_resources_project_id", "crm_smm_resources", ["project_id"])
    op.create_index("ix_crm_smm_resources_config_id", "crm_smm_resources", ["config_id"])
    op.create_index("ix_crm_smm_resources_resource_type", "crm_smm_resources", ["resource_type"])

    op.create_table(
        "crm_keywords",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=True),
        sa.Column("query", sa.String(length=512), nullable=False),
        sa.Column("frequency", sa.Integer(), nullable=False),
        sa.Column("cluster", sa.String(length=255), nullable=False),
        sa.Column("product", sa.String(length=255), nullable=True),
        sa.Column("technology", sa.String(length=255), nullable=True),
        sa.Column("intent", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["crm_bot_project_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["crm_smm_resources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_keywords_project_id", "crm_keywords", ["project_id"])
    op.create_index("ix_crm_keywords_config_id", "crm_keywords", ["config_id"])
    op.create_index("ix_crm_keywords_resource_id", "crm_keywords", ["resource_id"])

    op.create_table(
        "crm_content_sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=True),
        sa.Column("root_folder", sa.String(length=255), nullable=True),
        sa.Column("allowed_folders", _json(), nullable=False),
        sa.Column("media_tags", _json(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["crm_bot_project_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_content_sources_project_id", "crm_content_sources", ["project_id"])
    op.create_index("ix_crm_content_sources_config_id", "crm_content_sources", ["config_id"])
    op.create_index("ix_crm_content_sources_source_type", "crm_content_sources", ["source_type"])

    op.create_table(
        "crm_promotion_categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("resource_ids", _json(), nullable=False),
        sa.Column("keyword_ids", _json(), nullable=False),
        sa.Column("product_priorities", _json(), nullable=False),
        sa.Column("technology_priorities", _json(), nullable=False),
        sa.Column("media_tags", _json(), nullable=False),
        sa.Column("default_site_url", sa.String(length=512), nullable=True),
        sa.Column("cta", sa.Text(), nullable=False),
        sa.Column("tone", sa.String(length=255), nullable=False),
        sa.Column("require_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["crm_bot_project_configs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crm_promotion_categories_project_id", "crm_promotion_categories", ["project_id"]
    )
    op.create_index(
        "ix_crm_promotion_categories_config_id", "crm_promotion_categories", ["config_id"]
    )
    op.create_index("ix_crm_promotion_categories_status", "crm_promotion_categories", ["status"])

    op.create_table(
        "crm_publishing_plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("config_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("weekdays", _json(), nullable=False),
        sa.Column("posts_per_day", sa.Integer(), nullable=False),
        sa.Column("publish_times", _json(), nullable=False),
        sa.Column("platforms", _json(), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.String(length=20), nullable=True),
        sa.Column("end_date", sa.String(length=20), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["crm_bot_project_configs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["category_id"], ["crm_promotion_categories.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_publishing_plans_project_id", "crm_publishing_plans", ["project_id"])
    op.create_index("ix_crm_publishing_plans_config_id", "crm_publishing_plans", ["config_id"])
    op.create_index("ix_crm_publishing_plans_category_id", "crm_publishing_plans", ["category_id"])
    op.create_index("ix_crm_publishing_plans_mode", "crm_publishing_plans", ["mode"])

    op.create_table(
        "crm_onboarding_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("step", sa.String(length=64), nullable=False),
        sa.Column("payload", _json(), nullable=False),
        sa.Column("validation_errors", _json(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_crm_onboarding_drafts_project_id", "crm_onboarding_drafts", ["project_id"])
    op.create_index("ix_crm_onboarding_drafts_status", "crm_onboarding_drafts", ["status"])


def downgrade() -> None:
    op.drop_table("crm_onboarding_drafts")
    op.drop_table("crm_publishing_plans")
    op.drop_table("crm_promotion_categories")
    op.drop_table("crm_content_sources")
    op.drop_table("crm_keywords")
    op.drop_table("crm_smm_resources")
    op.drop_table("crm_bot_project_configs")
