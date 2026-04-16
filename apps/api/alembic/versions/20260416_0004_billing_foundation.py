"""Add billing foundation tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0004"
down_revision = "20260416_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_time_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("author_membership_id", sa.String(length=36), nullable=True),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("billable", sa.Boolean(), nullable=False),
        sa.Column("rate_currency", sa.String(length=8), nullable=False),
        sa.Column("rate_amount_minor", sa.Integer(), nullable=True),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["author_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_matter_time_entries_author_membership_id"),
        "matter_time_entries",
        ["author_membership_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_time_entries_matter_id"),
        "matter_time_entries",
        ["matter_id"],
        unique=False,
    )

    op.create_table(
        "matter_invoices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("issued_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("invoice_number", sa.String(length=80), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("subtotal_amount_minor", sa.Integer(), nullable=False),
        sa.Column("tax_amount_minor", sa.Integer(), nullable=False),
        sa.Column("total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_received_minor", sa.Integer(), nullable=False),
        sa.Column("balance_due_minor", sa.Integer(), nullable=False),
        sa.Column("issued_on", sa.Date(), nullable=False),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("pine_labs_payment_url", sa.String(length=1000), nullable=True),
        sa.Column("pine_labs_order_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["issued_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "invoice_number", name="uq_company_invoice_number"),
    )
    op.create_index(op.f("ix_matter_invoices_company_id"), "matter_invoices", ["company_id"], unique=False)
    op.create_index(
        op.f("ix_matter_invoices_issued_by_membership_id"),
        "matter_invoices",
        ["issued_by_membership_id"],
        unique=False,
    )
    op.create_index(op.f("ix_matter_invoices_matter_id"), "matter_invoices", ["matter_id"], unique=False)

    op.create_table(
        "matter_invoice_line_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("time_entry_id", sa.String(length=36), nullable=True),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("unit_rate_amount_minor", sa.Integer(), nullable=True),
        sa.Column("line_total_amount_minor", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["invoice_id"], ["matter_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["time_entry_id"],
            ["matter_time_entries.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("time_entry_id", name="uq_invoice_line_item_time_entry"),
    )
    op.create_index(
        op.f("ix_matter_invoice_line_items_invoice_id"),
        "matter_invoice_line_items",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_invoice_line_items_time_entry_id"),
        "matter_invoice_line_items",
        ["time_entry_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_matter_invoice_line_items_time_entry_id"),
        table_name="matter_invoice_line_items",
    )
    op.drop_index(
        op.f("ix_matter_invoice_line_items_invoice_id"),
        table_name="matter_invoice_line_items",
    )
    op.drop_table("matter_invoice_line_items")

    op.drop_index(op.f("ix_matter_invoices_matter_id"), table_name="matter_invoices")
    op.drop_index(
        op.f("ix_matter_invoices_issued_by_membership_id"),
        table_name="matter_invoices",
    )
    op.drop_index(op.f("ix_matter_invoices_company_id"), table_name="matter_invoices")
    op.drop_table("matter_invoices")

    op.drop_index(op.f("ix_matter_time_entries_matter_id"), table_name="matter_time_entries")
    op.drop_index(
        op.f("ix_matter_time_entries_author_membership_id"),
        table_name="matter_time_entries",
    )
    op.drop_table("matter_time_entries")
