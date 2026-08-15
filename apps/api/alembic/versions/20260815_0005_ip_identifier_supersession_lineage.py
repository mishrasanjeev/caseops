"""Persist forward lineage for reconciled duplicate identifiers.

``supersedes_identifier_id`` points backward from a newly-created correction
to the identifier it replaced. Duplicate reconciliation retires the duplicate
row instead, so it needs the opposite direction: a forward pointer from that
retired row to the surviving identifier. Keeping the meanings separate avoids
an inverted history chain.

The change is additive. Existing identifiers remain unlinked rather than
guessing a survivor, and composite foreign keys make both the existing
backward correction pointer and the new forward replacement pointer
same-tenant identifiers at the database boundary.

Revision ID: 20260815_0005
Revises: 20260815_0004

DATA-GOVERNANCE-MAP: updated
``superseded_by_identifier_id`` extends the existing ``ip_identifiers``
``tenant_restricted_legal_content`` record as a
``tenant_or_access_identifier``; it adds no new retention class.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0005"
down_revision = "20260815_0004"
branch_labels = None
depends_on = None

TABLE = "ip_identifiers"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # SQLite needs batch mode for the self-referential composite foreign key
    # and check constraint; PostgreSQL follows the same deterministic shape.
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column("superseded_by_identifier_id", sa.String(36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_ip_identifier_supersedes_company",
            TABLE,
            ["supersedes_identifier_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_identifier_superseded_by_company",
            TABLE,
            ["superseded_by_identifier_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_ip_identifier_superseded_by_not_self",
            "superseded_by_identifier_id IS NULL OR superseded_by_identifier_id <> id",
        )

    op.create_index(
        "ix_ip_identifiers_superseded_by_identifier_id",
        TABLE,
        ["superseded_by_identifier_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_identifiers_superseded_by_identifier_id",
        table_name=TABLE,
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint(
            "ck_ip_identifier_superseded_by_not_self",
            type_="check",
        )
        batch.drop_constraint(
            "fk_ip_identifier_superseded_by_company",
            type_="foreignkey",
        )
        batch.drop_constraint(
            "fk_ip_identifier_supersedes_company",
            type_="foreignkey",
        )
        batch.drop_column("superseded_by_identifier_id")
