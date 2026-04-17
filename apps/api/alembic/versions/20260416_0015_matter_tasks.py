"""add matter tasks

Revision ID: 20260416_0015
Revises: 20260416_0014
Create Date: 2026-04-16 23:59:59
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0015"
down_revision = "20260416_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_tasks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("owner_membership_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("priority", sa.String(length=24), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_matter_tasks_matter_id", "matter_tasks", ["matter_id"], unique=False)
    op.create_index(
        "ix_matter_tasks_created_by_membership_id",
        "matter_tasks",
        ["created_by_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_tasks_owner_membership_id",
        "matter_tasks",
        ["owner_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_matter_tasks_owner_membership_id", table_name="matter_tasks")
    op.drop_index("ix_matter_tasks_created_by_membership_id", table_name="matter_tasks")
    op.drop_index("ix_matter_tasks_matter_id", table_name="matter_tasks")
    op.drop_table("matter_tasks")
