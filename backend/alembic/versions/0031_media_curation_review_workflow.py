"""Media curation collaborative review workflow (v0.4.9)

Revision ID: 0031_media_curation_review_workflow
Revises: 0030_media_curation_tasks
Create Date: 2026-07-12

Расширяет ``media_curation_tasks`` полями workflow согласования (review_status, priority,
assignee/reviewer, сроки, before/after/decision) и добавляет таблицу комментариев
``media_curation_comments``. Изменения применяются ТОЛЬКО после подтверждения; файлы НЕ
удаляются; внешнего AI нет; без секретов/внутренних путей. Совместимо со SQLite и PostgreSQL.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
# NB: ``alembic_version.version_num`` — varchar(32), поэтому id укорочен (файл — полное имя).
revision: str = "0031_media_curation_review"
down_revision: str | None = "0030_media_curation_tasks"
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
    # --- Поля workflow согласования на media_curation_tasks --- #
    op.add_column(
        "media_curation_tasks",
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="proposed"),
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("priority", sa.String(length=20), nullable=False, server_default="normal"),
    )
    op.add_column(
        "media_curation_tasks", sa.Column("assignee_user_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "media_curation_tasks", sa.Column("reviewer_user_id", sa.Integer(), nullable=True)
    )
    op.add_column(
        "media_curation_tasks", sa.Column("due_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "media_curation_tasks", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "media_curation_tasks", sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("changes_requested_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("decision_summary", _json(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("before_state", _json(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("after_state", _json(), nullable=False, server_default="{}"),
    )
    op.add_column(
        "media_curation_tasks",
        sa.Column("review_metadata", _json(), nullable=False, server_default="{}"),
    )
    op.create_index(
        "ix_media_curation_tasks_review_status", "media_curation_tasks", ["review_status"]
    )
    op.create_index("ix_media_curation_tasks_priority", "media_curation_tasks", ["priority"])
    op.create_index(
        "ix_media_curation_tasks_assignee", "media_curation_tasks", ["assignee_user_id"]
    )
    op.create_index(
        "ix_media_curation_tasks_reviewer", "media_curation_tasks", ["reviewer_user_id"]
    )
    op.create_index("ix_media_curation_tasks_due_at", "media_curation_tasks", ["due_at"])

    # --- Таблица комментариев курирования --- #
    op.create_table(
        "media_curation_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("account_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("comment_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("comment_type", sa.String(length=30), nullable=False, server_default="comment"),
        sa.Column("comment_metadata", _json(), nullable=False, server_default="{}"),
        *_timestamps(),
        sa.ForeignKeyConstraint(["account_id"], ["accounts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["media_curation_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_curation_comments_account_id", "media_curation_comments", ["account_id"]
    )
    op.create_index(
        "ix_media_curation_comments_project_id", "media_curation_comments", ["project_id"]
    )
    op.create_index("ix_media_curation_comments_task_id", "media_curation_comments", ["task_id"])
    op.create_index("ix_media_curation_comments_user_id", "media_curation_comments", ["user_id"])
    op.create_index(
        "ix_media_curation_comments_comment_type", "media_curation_comments", ["comment_type"]
    )
    op.create_index(
        "ix_media_curation_comments_created_at", "media_curation_comments", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_media_curation_comments_created_at", table_name="media_curation_comments")
    op.drop_index("ix_media_curation_comments_comment_type", table_name="media_curation_comments")
    op.drop_index("ix_media_curation_comments_user_id", table_name="media_curation_comments")
    op.drop_index("ix_media_curation_comments_task_id", table_name="media_curation_comments")
    op.drop_index("ix_media_curation_comments_project_id", table_name="media_curation_comments")
    op.drop_index("ix_media_curation_comments_account_id", table_name="media_curation_comments")
    op.drop_table("media_curation_comments")

    op.drop_index("ix_media_curation_tasks_due_at", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_reviewer", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_assignee", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_priority", table_name="media_curation_tasks")
    op.drop_index("ix_media_curation_tasks_review_status", table_name="media_curation_tasks")
    op.drop_column("media_curation_tasks", "review_metadata")
    op.drop_column("media_curation_tasks", "after_state")
    op.drop_column("media_curation_tasks", "before_state")
    op.drop_column("media_curation_tasks", "decision_summary")
    op.drop_column("media_curation_tasks", "changes_requested_at")
    op.drop_column("media_curation_tasks", "approved_at")
    op.drop_column("media_curation_tasks", "reviewed_at")
    op.drop_column("media_curation_tasks", "due_at")
    op.drop_column("media_curation_tasks", "reviewer_user_id")
    op.drop_column("media_curation_tasks", "assignee_user_id")
    op.drop_column("media_curation_tasks", "priority")
    op.drop_column("media_curation_tasks", "review_status")
