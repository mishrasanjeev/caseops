"""Add invoice payment attempts and webhook inbox."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0005"
down_revision = "20260416_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_invoice_payment_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("initiated_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("merchant_order_id", sa.String(length=120), nullable=False),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("amount_received_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("customer_name", sa.String(length=255), nullable=True),
        sa.Column("customer_email", sa.String(length=320), nullable=True),
        sa.Column("customer_phone", sa.String(length=40), nullable=True),
        sa.Column("payment_url", sa.String(length=1000), nullable=True),
        sa.Column("provider_reference", sa.String(length=255), nullable=True),
        sa.Column("provider_payload_json", sa.Text(), nullable=True),
        sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["initiated_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["invoice_id"], ["matter_invoices.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("merchant_order_id"),
    )
    op.create_index(
        op.f("ix_matter_invoice_payment_attempts_company_id"),
        "matter_invoice_payment_attempts",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_invoice_payment_attempts_invoice_id"),
        "matter_invoice_payment_attempts",
        ["invoice_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_invoice_payment_attempts_initiated_by_membership_id"),
        "matter_invoice_payment_attempts",
        ["initiated_by_membership_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_matter_invoice_payment_attempts_provider_order_id"),
        "matter_invoice_payment_attempts",
        ["provider_order_id"],
        unique=False,
    )

    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_order_id", sa.String(length=255), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=True),
        sa.Column("signature", sa.String(length=500), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("processing_status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_payment_webhook_events_provider_order_id"),
        "payment_webhook_events",
        ["provider_order_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_payment_webhook_events_provider_order_id"),
        table_name="payment_webhook_events",
    )
    op.drop_table("payment_webhook_events")

    op.drop_index(
        op.f("ix_matter_invoice_payment_attempts_provider_order_id"),
        table_name="matter_invoice_payment_attempts",
    )
    op.drop_index(
        op.f("ix_matter_invoice_payment_attempts_initiated_by_membership_id"),
        table_name="matter_invoice_payment_attempts",
    )
    op.drop_index(
        op.f("ix_matter_invoice_payment_attempts_invoice_id"),
        table_name="matter_invoice_payment_attempts",
    )
    op.drop_index(
        op.f("ix_matter_invoice_payment_attempts_company_id"),
        table_name="matter_invoice_payment_attempts",
    )
    op.drop_table("matter_invoice_payment_attempts")
