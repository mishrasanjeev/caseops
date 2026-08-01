"""Add fail-closed statute provenance and quarantine fields.

Revision ID: 20260801_0001
Revises: 20260723_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0001"
down_revision = "20260723_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("statute_sections") as batch_op:
        batch_op.add_column(
            sa.Column(
                "verification_status",
                sa.String(24),
                nullable=False,
                server_default="unverified",
            )
        )
        batch_op.add_column(sa.Column("source_sha256", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("source_publisher", sa.String(160), nullable=True))
        batch_op.add_column(
            sa.Column("source_version", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "verified_by_membership_id",
                sa.String(36),
                nullable=True,
            )
        )
        batch_op.create_foreign_key(
            "fk_statute_sections_verified_by_membership",
            "company_memberships",
            ["verified_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.add_column(sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("quarantine_reason", sa.String(500), nullable=True))
        batch_op.create_index(
            "ix_statute_sections_verification_status",
            ["verification_status"],
        )
        batch_op.create_index(
            "ix_statute_sections_verified_by_membership_id",
            ["verified_by_membership_id"],
        )

    op.execute(
        sa.text(
            "UPDATE statute_sections "
            "SET verification_status = 'quarantined', "
            "quarantine_reason = 'AI-generated legal text is not authoritative', "
            "quarantined_at = CURRENT_TIMESTAMP "
            "WHERE section_text_source = 'haiku_generated'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE statute_sections SET source_publisher = 'India Code' "
            "WHERE section_text_source = 'indiacode_scrape'"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("statute_sections") as batch_op:
        batch_op.drop_index("ix_statute_sections_verified_by_membership_id")
        batch_op.drop_index("ix_statute_sections_verification_status")
        batch_op.drop_constraint(
            "fk_statute_sections_verified_by_membership",
            type_="foreignkey",
        )
        batch_op.drop_column("quarantine_reason")
        batch_op.drop_column("quarantined_at")
        batch_op.drop_column("verified_by_membership_id")
        batch_op.drop_column("verified_at")
        batch_op.drop_column("source_version")
        batch_op.drop_column("source_sha256")
        batch_op.drop_column("source_publisher")
        batch_op.drop_column("verification_status")
