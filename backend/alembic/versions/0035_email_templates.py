"""Email template overrides (v0.5.3)

Revision ID: 0035_email_templates
Revises: 0034_notification_safety
Create Date: 2026-07-13

Foundation переопределений email-шаблонов (per account/project). Системные шаблоны — в коде;
override используется, только если задан. Реальной email-доставки нет; без секретов/сырых
токенов. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0035_email_templates"
down_revision: str | None = "0034_notification_safety"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.types.TypeEngine:
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
        "email_template_overrides",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column(
            "template_type", sa.String(length=40), nullable=False, server_default="system_notice"
        ),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("subject_template", sa.String(length=512), nullable=False, server_default=""),
        sa.Column("text_template", sa.Text(), nullable=False, server_default=""),
        sa.Column("html_template", sa.Text(), nullable=True),
        sa.Column("variables_schema", _json(), nullable=False, server_default="{}"),
        sa.Column("created_by_user_id", sa.Integer(), nullable=True),
        sa.Column("updated_by_user_id", sa.Integer(), nullable=True),
        sa.Column("override_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["updated_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_eto_account_id", "email_template_overrides", ["account_id"])
    op.create_index("ix_eto_project_id", "email_template_overrides", ["project_id"])
    op.create_index("ix_eto_template_type", "email_template_overrides", ["template_type"])
    op.create_index("ix_eto_status", "email_template_overrides", ["status"])
    op.create_index("ix_eto_created_at", "email_template_overrides", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_eto_created_at", table_name="email_template_overrides")
    op.drop_index("ix_eto_status", table_name="email_template_overrides")
    op.drop_index("ix_eto_template_type", table_name="email_template_overrides")
    op.drop_index("ix_eto_project_id", table_name="email_template_overrides")
    op.drop_index("ix_eto_account_id", table_name="email_template_overrides")
    op.drop_table("email_template_overrides")
