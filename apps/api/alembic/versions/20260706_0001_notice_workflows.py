"""Expand notice workflows on matter attachments."""

import sqlalchemy as sa

from alembic import op

revision = "20260706_0001"
down_revision = "20260703_0001"
branch_labels = None
depends_on = None

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)


def upgrade() -> None:
    op.add_column(
        "matter_attachments", sa.Column("notice_direction", sa.String(length=16), nullable=True)
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_type", sa.String(length=120), nullable=True)
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_mode", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_authority", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_received_from", sa.String(length=120), nullable=True),
    )
    op.add_column("matter_attachments", sa.Column("notice_summary", sa.Text(), nullable=True))
    op.add_column("matter_attachments", sa.Column("notice_remarks", sa.Text(), nullable=True))
    op.add_column(
        "matter_attachments", sa.Column("notice_status", sa.String(length=80), nullable=True)
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_department", sa.String(length=160), nullable=True)
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_internal_spoc", sa.String(length=160), nullable=True),
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_internal_remarks", sa.Text(), nullable=True)
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_amount_minor", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_dispute_amount_minor", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_recovered_amount_minor", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_currency", sa.String(length=3), nullable=False, server_default="INR"),
    )
    op.add_column("matter_attachments", sa.Column("notice_reply_due_on", sa.Date(), nullable=True))
    op.add_column(
        "matter_attachments",
        sa.Column("notice_reply_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_reply_sent", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("matter_attachments", sa.Column("notice_reply_sent_on", sa.Date(), nullable=True))
    op.add_column("matter_attachments", sa.Column("notice_sent_on", sa.Date(), nullable=True))
    op.add_column(
        "matter_attachments",
        sa.Column("notice_counsel_engaged", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_parent_attachment_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column(
            "notice_document_role", sa.String(length=24), nullable=False, server_default="notice"
        ),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_reply_deadline_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "matter_attachments", sa.Column("notice_reminder_offsets_json", sa.JSON(), nullable=True)
    )

    op.create_index(
        "ix_matter_attachments_notice_direction", "matter_attachments", ["notice_direction"]
    )
    op.create_index(
        "ix_matter_attachments_notice_reply_due_on", "matter_attachments", ["notice_reply_due_on"]
    )
    op.create_index(
        "ix_matter_attachments_notice_parent_attachment_id",
        "matter_attachments",
        ["notice_parent_attachment_id"],
    )
    op.create_index(
        "ix_matter_attachments_notice_reply_deadline_id",
        "matter_attachments",
        ["notice_reply_deadline_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_matter_attachments_notice_reply_deadline_id", table_name="matter_attachments")
    op.drop_index(
        "ix_matter_attachments_notice_parent_attachment_id", table_name="matter_attachments"
    )
    op.drop_index("ix_matter_attachments_notice_reply_due_on", table_name="matter_attachments")
    op.drop_index("ix_matter_attachments_notice_direction", table_name="matter_attachments")

    op.drop_column("matter_attachments", "notice_reminder_offsets_json")
    op.drop_column("matter_attachments", "notice_reply_deadline_id")
    op.drop_column("matter_attachments", "notice_document_role")
    op.drop_column("matter_attachments", "notice_parent_attachment_id")
    op.drop_column("matter_attachments", "notice_counsel_engaged")
    op.drop_column("matter_attachments", "notice_sent_on")
    op.drop_column("matter_attachments", "notice_reply_sent_on")
    op.drop_column("matter_attachments", "notice_reply_sent")
    op.drop_column("matter_attachments", "notice_reply_required")
    op.drop_column("matter_attachments", "notice_reply_due_on")
    op.drop_column("matter_attachments", "notice_currency")
    op.drop_column("matter_attachments", "notice_recovered_amount_minor")
    op.drop_column("matter_attachments", "notice_dispute_amount_minor")
    op.drop_column("matter_attachments", "notice_amount_minor")
    op.drop_column("matter_attachments", "notice_internal_remarks")
    op.drop_column("matter_attachments", "notice_internal_spoc")
    op.drop_column("matter_attachments", "notice_department")
    op.drop_column("matter_attachments", "notice_status")
    op.drop_column("matter_attachments", "notice_remarks")
    op.drop_column("matter_attachments", "notice_summary")
    op.drop_column("matter_attachments", "notice_received_from")
    op.drop_column("matter_attachments", "notice_authority")
    op.drop_column("matter_attachments", "notice_mode")
    op.drop_column("matter_attachments", "notice_type")
    op.drop_column("matter_attachments", "notice_direction")
