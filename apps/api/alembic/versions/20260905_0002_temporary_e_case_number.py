"""Retain an independent temporary e-filing identifier on each Matter.

Revision ID: 20260905_0002
Revises: 20260904_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged: nullable column without default; existing
table search indexes built concurrently on PostgreSQL, never under a long DDL
transaction. No existing identifier or lifecycle row is rewritten.
MIGRATION-ROLLBACK: restore-forward: populated temporary identifiers must not
be discarded by a downgrade.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260905_0002"
down_revision = "20260904_0002"
branch_labels = None
depends_on = None

_IDENTIFIERS = ("temporary_e_case_number", "case_number", "cnr_number", "filing_number")
_INDEX_HEALTH = sa.text(
    "SELECT i.indisvalid AND i.indisready FROM pg_index i "
    "JOIN pg_class c ON c.oid = i.indexrelid "
    "JOIN pg_namespace n ON n.oid = c.relnamespace "
    "WHERE n.nspname = current_schema() AND c.relname = :name"
)


def upgrade() -> None:
    bind = op.get_bind()
    existing = next(
        (column for column in sa.inspect(bind).get_columns("matters")
         if column["name"] == "temporary_e_case_number"),
        None,
    )
    # The autocommit block persists this column before every index has finished.
    # A failed concurrent build must be restartable without dropping identifiers.
    if existing is None:
        op.add_column(
            "matters", sa.Column("temporary_e_case_number", sa.String(120), nullable=True)
        )
    elif not (
        isinstance(existing["type"], sa.String)
        and existing["type"].length == 120
        and existing["nullable"]
        and existing["default"] is None
    ):
        raise RuntimeError("Existing temporary E-Case column does not match this migration.")
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            for column in _IDENTIFIERS:
                name = f"ix_matters_{column}_trgm"
                if bind.scalar(_INDEX_HEALTH, {"name": name}) is False:
                    op.execute(sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {name}"))
                op.execute(
                    sa.text(
                        f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} "
                        f"ON matters USING gin ({column} gin_trgm_ops)"
                    )
                )
                if bind.scalar(_INDEX_HEALTH, {"name": name}) is not True:
                    raise RuntimeError(f"Matter identifier search index is not ready: {name}")


def downgrade() -> None:
    if op.get_bind().scalar(
        sa.text("SELECT 1 FROM matters WHERE temporary_e_case_number IS NOT NULL LIMIT 1")
    ):
        raise RuntimeError(
            "Temporary E-Case identifiers exist; restore forward instead of dropping them."
        )
    if op.get_bind().dialect.name == "postgresql":
        # Downgrades share one transaction so later evidence refusals restore
        # both the column and every performance index, not just the version row.
        for column in _IDENTIFIERS:
            op.execute(sa.text(f"DROP INDEX IF EXISTS ix_matters_{column}_trgm"))
    op.drop_column("matters", "temporary_e_case_number")
