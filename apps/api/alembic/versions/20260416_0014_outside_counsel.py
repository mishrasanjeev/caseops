"""add outside counsel and spend tracking

Revision ID: 20260416_0014
Revises: 20260416_0013
Create Date: 2026-04-16 23:59:30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision = "20260416_0014"
down_revision = "20260416_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outside_counsel",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("primary_contact_name", sa.String(length=255), nullable=True),
        sa.Column("primary_contact_email", sa.String(length=320), nullable=True),
        sa.Column("primary_contact_phone", sa.String(length=40), nullable=True),
        sa.Column("firm_city", sa.String(length=255), nullable=True),
        sa.Column("jurisdictions_json", sa.Text(), nullable=True),
        sa.Column("practice_areas_json", sa.Text(), nullable=True),
        sa.Column("panel_status", sa.String(length=24), nullable=False),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_outside_counsel_name"),
    )
    op.create_index("ix_outside_counsel_company_id", "outside_counsel", ["company_id"], unique=False)

    op.create_table(
        "matter_outside_counsel_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("counsel_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("role_summary", sa.String(length=255), nullable=True),
        sa.Column("budget_amount_minor", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assigned_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["counsel_id"], ["outside_counsel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("matter_id", "counsel_id", name="uq_matter_outside_counsel_assignment"),
    )
    op.create_index(
        "ix_matter_outside_counsel_assignments_assigned_by_membership_id",
        "matter_outside_counsel_assignments",
        ["assigned_by_membership_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_outside_counsel_assignments_company_id",
        "matter_outside_counsel_assignments",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_outside_counsel_assignments_counsel_id",
        "matter_outside_counsel_assignments",
        ["counsel_id"],
        unique=False,
    )
    op.create_index(
        "ix_matter_outside_counsel_assignments_matter_id",
        "matter_outside_counsel_assignments",
        ["matter_id"],
        unique=False,
    )

    op.create_table(
        "outside_counsel_spend_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("counsel_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=True),
        sa.Column("recorded_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("invoice_reference", sa.String(length=120), nullable=True),
        sa.Column("stage_label", sa.String(length=120), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("approved_amount_minor", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("billed_on", sa.Date(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["assignment_id"], ["matter_outside_counsel_assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["counsel_id"], ["outside_counsel.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["recorded_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outside_counsel_spend_records_assignment_id",
        "outside_counsel_spend_records",
        ["assignment_id"],
        unique=False,
    )
    op.create_index(
        "ix_outside_counsel_spend_records_company_id",
        "outside_counsel_spend_records",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        "ix_outside_counsel_spend_records_counsel_id",
        "outside_counsel_spend_records",
        ["counsel_id"],
        unique=False,
    )
    op.create_index(
        "ix_outside_counsel_spend_records_matter_id",
        "outside_counsel_spend_records",
        ["matter_id"],
        unique=False,
    )
    op.create_index(
        "ix_outside_counsel_spend_records_recorded_by_membership_id",
        "outside_counsel_spend_records",
        ["recorded_by_membership_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outside_counsel_spend_records_recorded_by_membership_id",
        table_name="outside_counsel_spend_records",
    )
    op.drop_index(
        "ix_outside_counsel_spend_records_matter_id",
        table_name="outside_counsel_spend_records",
    )
    op.drop_index(
        "ix_outside_counsel_spend_records_counsel_id",
        table_name="outside_counsel_spend_records",
    )
    op.drop_index(
        "ix_outside_counsel_spend_records_company_id",
        table_name="outside_counsel_spend_records",
    )
    op.drop_index(
        "ix_outside_counsel_spend_records_assignment_id",
        table_name="outside_counsel_spend_records",
    )
    op.drop_table("outside_counsel_spend_records")

    op.drop_index(
        "ix_matter_outside_counsel_assignments_matter_id",
        table_name="matter_outside_counsel_assignments",
    )
    op.drop_index(
        "ix_matter_outside_counsel_assignments_counsel_id",
        table_name="matter_outside_counsel_assignments",
    )
    op.drop_index(
        "ix_matter_outside_counsel_assignments_company_id",
        table_name="matter_outside_counsel_assignments",
    )
    op.drop_index(
        "ix_matter_outside_counsel_assignments_assigned_by_membership_id",
        table_name="matter_outside_counsel_assignments",
    )
    op.drop_table("matter_outside_counsel_assignments")

    op.drop_index("ix_outside_counsel_company_id", table_name="outside_counsel")
    op.drop_table("outside_counsel")
