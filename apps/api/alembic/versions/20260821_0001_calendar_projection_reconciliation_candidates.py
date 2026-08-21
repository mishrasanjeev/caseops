"""Persist immutable, content-minimised external-calendar drift candidates.

CaseOps is the authoritative legal-work record.  This additive table stores a
bounded snapshot of the provider event state observed by the drift reader so a
human can make a later accept/reject decision against stable evidence.  It
intentionally excludes titles, descriptions, attendees, locations and provider
tokens; only event identity, date-level state and lifecycle metadata are kept.

DATA-GOVERNANCE-MAP: updated
Calendar projection reconciliation candidates inherit the
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
IMMUTABLE_TRIGGER = "trg_calendar_projection_reconciliation_evidence_immutable"
IMMUTABLE_FUNCTION = "caseops_reject_calendar_reconciliation_evidence_mutation"
REPAIR_CLAIM_INDEX = "ix_calendar_event_syncs_reconciliation_candidate_id"


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
            "snapshot_schema_version > 0 AND length(snapshot_sha256) = 64",
            name="ck_calendar_projection_reconciliation_snapshot_identity",
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
            ["calendar_event_sync_id"], ["calendar_event_syncs.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["calendar_connection_id"], ["user_calendar_connections.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["detected_by_membership_id"], ["company_memberships.id"], ondelete="RESTRICT"
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
    op.add_column(
        "calendar_event_syncs",
        sa.Column("reconciliation_candidate_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("reconciliation_snapshot_sha256", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "calendar_event_syncs",
        sa.Column("reconciliation_provider_revision", sa.String(length=500), nullable=True),
    )
    op.create_index(
        REPAIR_CLAIM_INDEX,
        "calendar_event_syncs",
        ["reconciliation_candidate_id"],
    )
    if bind.dialect.name == "postgresql":
        op.create_foreign_key(
            "fk_calendar_event_sync_reconciliation_candidate",
            "calendar_event_syncs",
            TABLE,
            ["reconciliation_candidate_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_check_constraint(
            "ck_calendar_event_sync_reconciliation_claim_complete",
            "calendar_event_syncs",
            "(reconciliation_candidate_id IS NULL AND "
            "reconciliation_snapshot_sha256 IS NULL AND "
            "reconciliation_provider_revision IS NULL) OR "
            "(reconciliation_candidate_id IS NOT NULL AND "
            "reconciliation_snapshot_sha256 IS NOT NULL AND "
            "reconciliation_provider_revision IS NOT NULL)",
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {IMMUTABLE_FUNCTION}() RETURNS trigger AS $$
                BEGIN
                    IF NEW.company_id IS DISTINCT FROM OLD.company_id
                       OR NEW.calendar_event_sync_id IS DISTINCT FROM OLD.calendar_event_sync_id
                       OR NEW.calendar_connection_id IS DISTINCT FROM OLD.calendar_connection_id
                       OR NEW.source_type IS DISTINCT FROM OLD.source_type
                       OR NEW.source_id IS DISTINCT FROM OLD.source_id
                       OR NEW.ip_docket_id IS DISTINCT FROM OLD.ip_docket_id
                       OR NEW.drift_status IS DISTINCT FROM OLD.drift_status
                       OR NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version
                       OR NEW.expected_snapshot_json::text
                          IS DISTINCT FROM OLD.expected_snapshot_json::text
                       OR NEW.observed_snapshot_json::text
                          IS DISTINCT FROM OLD.observed_snapshot_json::text
                       OR NEW.snapshot_sha256 IS DISTINCT FROM OLD.snapshot_sha256
                       OR NEW.detected_by_membership_id
                          IS DISTINCT FROM OLD.detected_by_membership_id
                       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION 'Calendar reconciliation snapshot evidence is immutable'
                            USING ERRCODE = 'restrict_violation';
                    END IF;
                    IF OLD.status <> 'pending'
                       OR NEW.status NOT IN ('accepted', 'rejected', 'superseded') THEN
                        RAISE EXCEPTION 'Calendar reconciliation decision is terminal'
                            USING ERRCODE = 'restrict_violation';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {IMMUTABLE_TRIGGER}
                BEFORE UPDATE ON {TABLE}
                FOR EACH ROW EXECUTE FUNCTION {IMMUTABLE_FUNCTION}()
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    recorded = bind.execute(sa.text(f"SELECT COUNT(*) FROM {TABLE}")).scalar_one()
    if recorded:
        raise RuntimeError(
            f"refusing to downgrade: {recorded} calendar reconciliation candidate(s) "
            "would be destroyed; export the evidence or roll forward instead."
        )
    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {IMMUTABLE_TRIGGER} ON {TABLE}"))
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {IMMUTABLE_FUNCTION}()"))
        op.drop_constraint(
            "ck_calendar_event_sync_reconciliation_claim_complete",
            "calendar_event_syncs",
            type_="check",
        )
        op.drop_constraint(
            "fk_calendar_event_sync_reconciliation_candidate",
            "calendar_event_syncs",
            type_="foreignkey",
        )
    op.drop_index(REPAIR_CLAIM_INDEX, table_name="calendar_event_syncs")
    op.drop_column("calendar_event_syncs", "reconciliation_provider_revision")
    op.drop_column("calendar_event_syncs", "reconciliation_snapshot_sha256")
    op.drop_column("calendar_event_syncs", "reconciliation_candidate_id")
    op.drop_index("ix_calendar_projection_reconciliation_sync", table_name=TABLE)
    op.drop_index("ix_calendar_projection_reconciliation_company_status", table_name=TABLE)
    op.drop_table(TABLE)
