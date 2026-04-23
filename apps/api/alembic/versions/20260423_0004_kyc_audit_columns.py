"""Phase B M11 slice 3 — KYC audit columns on the clients table.

Closes US-037 (KYC) + FT-049 (KYC create + status update flow works
where enabled). MOD-TS-013 reconciliation.

The ``Client.kyc_status`` enum already exists from MOD-TS-009 (slice
S1). What was missing: an audit trail showing WHO verified, WHEN,
and the REASON for rejection. Without that, the status badge is
just a coloured pill — useless under a compliance audit. This
migration adds the columns; the new submit / verify / reject
service functions populate them.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260423_0004"
down_revision = "20260423_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.add_column(
            sa.Column(
                "kyc_submitted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "kyc_verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column(
                "kyc_verified_by_membership_id",
                sa.String(length=36),
                nullable=True,
            ),
        )
        batch.add_column(
            sa.Column("kyc_rejection_reason", sa.Text(), nullable=True),
        )
        # Documents collected during this KYC cycle. Stored as JSON
        # array of {name, status, note} so adding fields later
        # (e.g. external doc URL once secure storage is wired) does
        # not require another migration.
        batch.add_column(
            sa.Column("kyc_documents_json", sa.JSON(), nullable=True),
        )
        batch.create_foreign_key(
            "fk_clients_kyc_verified_by_membership",
            "company_memberships",
            ["kyc_verified_by_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("clients") as batch:
        batch.drop_constraint(
            "fk_clients_kyc_verified_by_membership", type_="foreignkey",
        )
        batch.drop_column("kyc_documents_json")
        batch.drop_column("kyc_rejection_reason")
        batch.drop_column("kyc_verified_by_membership_id")
        batch.drop_column("kyc_verified_at")
        batch.drop_column("kyc_submitted_at")
