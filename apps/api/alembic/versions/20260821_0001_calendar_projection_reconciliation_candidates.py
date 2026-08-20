"""Persist immutable, content-minimised external-calendar drift candidates.

CaseOps is the authoritative legal-work record.  This additive table stores a
bounded snapshot of the provider event state observed by the drift reader so a
human can make a later accept/reject decision against stable evidence.  It
intentionally excludes titles, descriptions, attendees, locations and provider
tokens; only event identity, date-level state and lifecycle metadata are kept.

DATA-GOVERNANCE-MAP: calendar projection reconciliation candidates inherit the
existing tenant_operational_record calendar-sync classification.  The stored
JSON is restricted by service code to a content-minimised schema.

MIGRATION-LOCK-RISK: acknowledged.  This creates a new empty table and indexes;
it does not rewrite or scan existing calendar rows.

MIGRATION-ROLLBACK: restore-forward.  Downgrade refuses to destroy any recorded
candidate because it is evidence for a reconciliation decision.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260821_0001"
down_revision = "20260820_0002"
branch_labels = None
depends_on = None

TABLE = "calendar_projection_reconciliation_candidates"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("calendar_event_sync_id", sa.String(length=36), nullable=False),
        sa.Column("calendar_connection_id", sa.String(length=36), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=36), nullable=False),
        sa.Column("ip_docket_id", sa.String(length=36), nullable=True),
        sa.Column("drift_status", sa.String(length=16), nullable=False),
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("expected_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("observed_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("detected_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("decided_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("decision_evidence_reference", sa.String(length=500), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "drift_status IN ('moved', 'missing', 'unknown')",
            name="ck_calendar_projection_reconciliation_drift_status",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'superseded')",
            name="ck_calendar_projection_reconciliation_status",
        ),
        sa.CheckConstraint(
            "(status IN ('pending', 'superseded') AND decided_at IS NULL "
            "AND decided_by_membership_id IS NULL AND decision_evidence_reference IS NULL) OR "
            "(status IN ('accepted', 'rejected') AND decided_at IS NOT NULL "
            "AND decided_by_membership_id IS NOT NULL AND decision_evidence_reference IS NOT NULL)",
            name="ck_calendar_projection_reconciliation_decision_evidence",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["calendar_event_sync_id"], ["calendar_event_syncs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["calendar_connection_id"], ["user_calendar_connections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["detected_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_membership_id"], ["company_memberships.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "calendar_event_sync_id",
            "snapshot_sha256",
            name="uq_calendar_projection_reconciliation_snapshot",
        ),
    )
    op.create_index(
        "ix_calendar_projection_reconciliation_company_status",
        TABLE,
        ["company_id", "status"],
    )
    op.create_index(
        "ix_calendar_projection_reconciliation_sync",
        TABLE,
        ["calendar_event_sync_id", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    recorded = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
    if recorded:
        raise RuntimeError(
            f"refusing to downgrade: {recorded} calendar reconciliation candidate(s) "
            "would be destroyed; export the evidence or roll forward instead."
        )
    op.drop_index("ix_calendar_projection_reconciliation_sync", table_name=TABLE)
    op.drop_index("ix_calendar_projection_reconciliation_company_status", table_name=TABLE)
    op.drop_table(TABLE)
