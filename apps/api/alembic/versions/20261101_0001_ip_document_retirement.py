"""Record an audited retirement on IP documents (never a hard delete).

Revision ID: 20261101_0001
Revises: 20261031_0002
DATA-GOVERNANCE-MAP: updated
Map: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml.
``ip_documents.retired_at``, ``retired_by_membership_id`` and
``retirement_reason`` record who withdrew a document from current use, when and
why, under the table's existing tenant-restricted legal-content profile. The
document, its versions, links and bytes are retained; no new retention, provider
transmission or disposition is authorized.

All three columns are nullable and are either all empty (current document) or
all set (retired document). The retiring member is a same-company membership.

MIGRATION-LOCK-RISK: acknowledged. Additive nullable columns, one composite
foreign key and its support index on a bounded tenant table, within env.py's
migration lock and statement budgets; no backfill runs.
MIGRATION-ROLLBACK: restore-forward. Do not downgrade after any document was
retired: the retirement evidence would be lost and retired documents would
re-enter pickers and validators.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20261101_0001"
down_revision = "20261031_0002"
branch_labels = None
depends_on = None

_TABLE = "ip_documents"
_CHECK = "ck_ip_document_retirement_complete"
_CHECK_SQL = (
    "(retired_at IS NULL AND retired_by_membership_id IS NULL AND retirement_reason IS NULL)"
    " OR (retired_at IS NOT NULL AND retired_by_membership_id IS NOT NULL"
    " AND retirement_reason IS NOT NULL)"
)


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns(_TABLE)}
    with op.batch_alter_table(_TABLE) as batch:
        if "retired_at" not in columns:
            batch.add_column(sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True))
        if "retired_by_membership_id" not in columns:
            batch.add_column(sa.Column("retired_by_membership_id", sa.String(36), nullable=True))
        if "retirement_reason" not in columns:
            batch.add_column(sa.Column("retirement_reason", sa.String(1000), nullable=True))
    with op.batch_alter_table(_TABLE) as batch:
        batch.create_foreign_key(
            "fk_ip_document_retired_by_company",
            "company_memberships",
            ["retired_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(_CHECK, _CHECK_SQL)
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes(_TABLE)}
    if "ix_fk_ip_documents_retired_by_memb_e0c5369f" not in indexes:
        op.create_index(
            "ix_fk_ip_documents_retired_by_memb_e0c5369f",
            "ip_documents",
            ["retired_by_membership_id", "company_id"],
        )


def downgrade() -> None:
    raise RuntimeError(
        "IP document retirement is restore-forward only; dropping it would return "
        "retired documents to pickers and validators."
    )
