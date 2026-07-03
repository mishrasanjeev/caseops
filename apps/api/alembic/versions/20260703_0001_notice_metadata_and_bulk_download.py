"""Add structured notice metadata to matter attachments."""

import sqlalchemy as sa

from alembic import op

revision = "20260703_0001"
down_revision = "20260625_0002"
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
        "matter_attachments",
        sa.Column("notice_source", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_subject", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_received_on", sa.Date(), nullable=True),
    )
    op.add_column(
        "matter_attachments",
        sa.Column("notice_response", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_matter_attachments_notice_received_on",
        "matter_attachments",
        ["notice_received_on"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_attachments_notice_received_on",
        table_name="matter_attachments",
    )
    op.drop_column("matter_attachments", "notice_response")
    op.drop_column("matter_attachments", "notice_received_on")
    op.drop_column("matter_attachments", "notice_subject")
    op.drop_column("matter_attachments", "notice_source")
