"""Add append-only IP docket events and lifecycle anchor fields.

Revision ID: 20260807_0003
Revises: 20260807_0002
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260807_0003"
down_revision = "20260807_0002"
branch_labels = None
depends_on = None

TERMINAL_STATUSES = "'archived', 'abandoned', 'transferred', 'retired', 'closed'"


def upgrade() -> None:
    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.add_column(
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.add_column(
            sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("lifecycle_effective_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(sa.Column("lifecycle_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("lifecycle_outcome", sa.String(120), nullable=True))
        batch_op.add_column(sa.Column("lifecycle_source", sa.String(80), nullable=True))
        batch_op.add_column(sa.Column("lifecycle_evidence_ref", sa.String(512), nullable=True))
        batch_op.add_column(sa.Column("successor_docket_id", sa.String(36), nullable=True))

    # Existing matter-disposal integration uses `archived`; normalize its new
    # activity projection before installing the fail-closed consistency check.
    op.execute(sa.text("UPDATE ip_docket_records SET is_active = false WHERE status = 'archived'"))

    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.create_foreign_key(
            "fk_ip_docket_successor_company",
            "ip_docket_records",
            ["successor_docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_status_active_consistent",
            f"(status IN ({TERMINAL_STATUSES}) AND is_active = false) OR "
            f"(status NOT IN ({TERMINAL_STATUSES}) AND is_active = true)",
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_lifecycle_version_nonnegative",
            "lifecycle_version >= 0",
        )
        batch_op.create_check_constraint(
            "ck_ip_docket_successor_not_self",
            "successor_docket_id IS NULL OR successor_docket_id <> id",
        )
        batch_op.create_index(
            "ix_ip_docket_records_successor_docket_id",
            ["successor_docket_id"],
        )

    op.create_table(
        "ip_docket_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("proceeding_id", sa.String(36), nullable=True),
        sa.Column("event_kind", sa.String(64), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("source_reference", sa.String(255), nullable=True),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "entered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("responsible_membership_id", sa.String(36), nullable=False),
        sa.Column("entered_by_membership_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("document_refs_json", sa.JSON(), nullable=False),
        sa.Column("resulting_stage", sa.String(64), nullable=True),
        sa.Column("resulting_deadline_refs_json", sa.JSON(), nullable=False),
        sa.Column("before_phase", sa.String(64), nullable=True),
        sa.Column("after_phase", sa.String(64), nullable=True),
        sa.Column(
            "candidate_status",
            sa.String(24),
            nullable=False,
            server_default="confirmed",
        ),
        sa.Column("supersedes_event_id", sa.String(36), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        sa.Column("reconciles_event_id", sa.String(36), nullable=True),
        sa.Column("reconciliation_decision", sa.String(40), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_docket_event_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_docket_event_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_docket_event_proceeding_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["responsible_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_event_responsible_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entered_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_docket_event_entered_by_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_docket_event_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reconciles_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_docket_event_reconciles_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_docket_event_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "docket_id",
            "sequence",
            name="uq_ip_docket_event_company_docket_sequence",
        ),
        sa.CheckConstraint(
            "NOT (application_id IS NOT NULL AND proceeding_id IS NOT NULL)",
            name="ck_ip_docket_event_single_legal_target",
        ),
        sa.CheckConstraint("sequence > 0", name="ck_ip_docket_event_sequence_positive"),
        sa.CheckConstraint(
            "source <> 'manual' OR (reason IS NOT NULL AND length(trim(reason)) > 0)",
            name="ck_ip_docket_event_manual_reason",
        ),
        sa.CheckConstraint(
            "supersedes_event_id IS NULL OR "
            "(correction_reason IS NOT NULL AND length(trim(correction_reason)) > 0)",
            name="ck_ip_docket_event_correction_reason",
        ),
        sa.CheckConstraint(
            "supersedes_event_id IS NULL OR supersedes_event_id <> id",
            name="ck_ip_docket_event_supersedes_not_self",
        ),
        sa.CheckConstraint(
            "reconciles_event_id IS NULL OR reconciles_event_id <> id",
            name="ck_ip_docket_event_reconciles_not_self",
        ),
    )
    op.create_index("ix_ip_docket_events_docket_id", "ip_docket_events", ["docket_id"])
    op.create_index("ix_ip_docket_events_application_id", "ip_docket_events", ["application_id"])
    op.create_index("ix_ip_docket_events_proceeding_id", "ip_docket_events", ["proceeding_id"])
    op.create_index(
        "ix_ip_docket_events_responsible_membership_id",
        "ip_docket_events",
        ["responsible_membership_id"],
    )
    op.create_index(
        "ix_ip_docket_events_entered_by_membership_id",
        "ip_docket_events",
        ["entered_by_membership_id"],
    )
    op.create_index(
        "ix_ip_docket_events_supersedes_event_id",
        "ip_docket_events",
        ["supersedes_event_id"],
    )
    op.create_index(
        "ix_ip_docket_events_reconciles_event_id",
        "ip_docket_events",
        ["reconciles_event_id"],
    )
    op.create_index(
        "ix_ip_docket_events_company_effective",
        "ip_docket_events",
        ["company_id", "docket_id", "effective_at"],
    )
    op.create_index(
        "ix_ip_docket_events_company_candidate",
        "ip_docket_events",
        ["company_id", "candidate_status"],
    )


def downgrade() -> None:
    op.drop_table("ip_docket_events")
    with op.batch_alter_table("ip_docket_records") as batch_op:
        batch_op.drop_index("ix_ip_docket_records_successor_docket_id")
        batch_op.drop_constraint("ck_ip_docket_successor_not_self", type_="check")
        batch_op.drop_constraint("ck_ip_docket_lifecycle_version_nonnegative", type_="check")
        batch_op.drop_constraint("ck_ip_docket_status_active_consistent", type_="check")
        batch_op.drop_constraint("fk_ip_docket_successor_company", type_="foreignkey")
        batch_op.drop_column("successor_docket_id")
        batch_op.drop_column("lifecycle_evidence_ref")
        batch_op.drop_column("lifecycle_source")
        batch_op.drop_column("lifecycle_outcome")
        batch_op.drop_column("lifecycle_reason")
        batch_op.drop_column("lifecycle_effective_at")
        batch_op.drop_column("lifecycle_version")
        batch_op.drop_column("is_active")
