"""Keep automatic processing of native uploads inside CaseOps.

Revision ID: 20261108_0003
Revises: 20261108_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. Adds one nonnullable boolean with a
constant default (no data rewrite); PostgreSQL DDL uses bounded lock/statement
timeouts. Existing attachments retain their previously admitted behavior.
MIGRATION-ROLLBACK: restore-forward. Downgrade would discard persistent
upload provenance and could reenable third-party processing.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261108_0003"
down_revision = "20261108_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.add_column(
        "matter_attachments",
        sa.Column(
            "native_local_processing_only",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    raise RuntimeError(
        "Restore-forward required: removing native attachment provenance could "
        "reenable third-party processing without consent."
    )
