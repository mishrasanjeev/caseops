"""Persist bounded, integrity-checked case-tracking source text.

Revision ID: 20260828_0002
Revises: 20260828_0001

MIGRATION-LOCK-RISK: acknowledged. The source payload and digest columns are
nullable; the bounded truncation flag uses a constant default. No table scan,
backfill, or index build is performed during deployment.
MIGRATION-ROLLBACK: downgrade refuses to discard retained provider source text.
DATA-GOVERNANCE-MAP: extends the existing tracked-case update evidence owner;
it adds no parallel provider, source, retention, or disposition owner.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260828_0002"
down_revision = "20260828_0001"
branch_labels = None
depends_on = None


def _set_postgres_timeouts() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(sa.text("SET LOCAL lock_timeout = '5s'"))
        op.execute(sa.text("SET LOCAL statement_timeout = '10min'"))


def upgrade() -> None:
    _set_postgres_timeouts()
    with op.batch_alter_table("tracked_case_updates") as batch:
        batch.add_column(sa.Column("source_text", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_text_sha256", sa.String(length=64), nullable=True))
        batch.add_column(
            sa.Column(
                "source_text_truncated",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.create_check_constraint(
            "ck_tracked_case_update_source_text_hash",
            "(source_text IS NULL AND source_text_sha256 IS NULL) OR "
            "(source_text IS NOT NULL AND source_text_sha256 IS NOT NULL)",
        )


def downgrade() -> None:
    _set_postgres_timeouts()
    retained_count = op.get_bind().execute(
        sa.text(
            "SELECT count(*) FROM tracked_case_updates "
            "WHERE source_text IS NOT NULL OR source_text_sha256 IS NOT NULL "
            "OR source_text_truncated = true"
        )
    ).scalar_one()
    if retained_count:
        raise RuntimeError(
            "Refusing destructive downgrade: tracked-case provider source text exists; "
            "use governed export/disposition and restore-forward."
        )
    with op.batch_alter_table("tracked_case_updates") as batch:
        batch.drop_constraint(
            "ck_tracked_case_update_source_text_hash", type_="check"
        )
        batch.drop_column("source_text_truncated")
        batch.drop_column("source_text_sha256")
        batch.drop_column("source_text")
