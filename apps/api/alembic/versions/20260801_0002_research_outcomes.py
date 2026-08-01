"""Add privacy-preserving authority search outcome telemetry.

Revision ID: 20260801_0002
Revises: 20260801_0001
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260801_0002"
down_revision = "20260801_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "authority_search_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("query_fingerprint", sa.String(64), nullable=False),
        sa.Column("mode", sa.String(24), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("raw_candidate_count", sa.Integer(), nullable=False),
        sa.Column("unreadable_omitted_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_authority_search_observations_company_created",
        "authority_search_observations",
        ["company_id", "created_at"],
    )
    op.create_index(
        "ix_authority_search_observations_outcome",
        "authority_search_observations",
        ["outcome"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_search_observations_outcome",
        table_name="authority_search_observations",
    )
    op.drop_index(
        "ix_authority_search_observations_company_created",
        table_name="authority_search_observations",
    )
    op.drop_table("authority_search_observations")
