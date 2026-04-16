"""Add matter workspace tables and assignment."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0002"
down_revision = "20260416_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("matters", recreate="always") as batch_op:
        batch_op.add_column(sa.Column("assignee_membership_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_matters_assignee_membership_id",
            "company_memberships",
            ["assignee_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            op.f("ix_matters_assignee_membership_id"),
            ["assignee_membership_id"],
            unique=False,
        )

    op.create_table(
        "matter_notes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("author_membership_id", sa.String(length=36), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["author_membership_id"], ["company_memberships.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_matter_notes_author_membership_id"), "matter_notes", ["author_membership_id"], unique=False)
    op.create_index(op.f("ix_matter_notes_matter_id"), "matter_notes", ["matter_id"], unique=False)

    op.create_table(
        "matter_hearings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("hearing_on", sa.Date(), nullable=False),
        sa.Column("forum_name", sa.String(length=255), nullable=False),
        sa.Column("judge_name", sa.String(length=255), nullable=True),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("outcome_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_matter_hearings_matter_id"), "matter_hearings", ["matter_id"], unique=False)

    op.create_table(
        "matter_activity",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("actor_membership_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_matter_activity_actor_membership_id"), "matter_activity", ["actor_membership_id"], unique=False)
    op.create_index(op.f("ix_matter_activity_matter_id"), "matter_activity", ["matter_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_matter_activity_matter_id"), table_name="matter_activity")
    op.drop_index(op.f("ix_matter_activity_actor_membership_id"), table_name="matter_activity")
    op.drop_table("matter_activity")

    op.drop_index(op.f("ix_matter_hearings_matter_id"), table_name="matter_hearings")
    op.drop_table("matter_hearings")

    op.drop_index(op.f("ix_matter_notes_matter_id"), table_name="matter_notes")
    op.drop_index(op.f("ix_matter_notes_author_membership_id"), table_name="matter_notes")
    op.drop_table("matter_notes")

    with op.batch_alter_table("matters", recreate="always") as batch_op:
        batch_op.drop_index(op.f("ix_matters_assignee_membership_id"))
        batch_op.drop_constraint("fk_matters_assignee_membership_id", type_="foreignkey")
        batch_op.drop_column("assignee_membership_id")
