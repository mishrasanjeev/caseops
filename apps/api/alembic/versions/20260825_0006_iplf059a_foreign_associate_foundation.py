"""Add the canonical foreign-associate coordination foundation.

Revision ID: 20260825_0006
Revises: 20260825_0005
Create Date: 2026-08-25

IPLF-059A adds one coordination aggregate. Client authority, outside-counsel
directory/assignment/spend, communications, documents, costs, deadlines,
docket events, access and audit remain with their existing canonical owners.

MIGRATION-LOCK-RISK: acknowledged: one additive empty table and one nullable
event-link column with indexes/constraints; PostgreSQL lock timeout is five
seconds. SQLite test upgrades may rebuild the altered event table.
MIGRATION-ROLLBACK: restore-forward once foreign-associate rows or linked docket
events exist. Downgrade is allowed only while both are empty.
DATA-GOVERNANCE-MAP: updated
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260825_0006"
down_revision = "20260825_0005"
branch_labels = None
depends_on = None


def _set_lock_timeout() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def upgrade() -> None:
    _set_lock_timeout()
    op.create_table(
        "ip_foreign_associate_instructions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("instruction_thread_key", sa.String(length=120), nullable=False),
        sa.Column("instruction_version", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("supersedes_instruction_id", sa.String(length=36), nullable=True),
        sa.Column("source_client_instruction_id", sa.String(length=36), nullable=True),
        sa.Column("client_authority_reference", sa.String(length=500), nullable=True),
        sa.Column("target_jurisdiction", sa.String(length=80), nullable=False),
        sa.Column("outside_counsel_id", sa.String(length=36), nullable=False),
        sa.Column("assignment_id", sa.String(length=36), nullable=True),
        sa.Column("responsible_membership_id", sa.String(length=36), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("selected_document_refs_json", sa.JSON(), nullable=False),
        sa.Column("privileged_document_refs_json", sa.JSON(), nullable=False),
        sa.Column("estimate_cost_item_id", sa.String(length=36), nullable=False),
        sa.Column("estimate_terms_json", sa.JSON(), nullable=False),
        sa.Column("budget_policy_reference", sa.String(length=500), nullable=False),
        sa.Column("approved_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "privileged_approved_by_membership_id", sa.String(length=36), nullable=True
        ),
        sa.Column("privileged_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatch_communication_id", sa.String(length=36), nullable=True),
        sa.Column("external_dispatch_reference", sa.String(length=500), nullable=True),
        sa.Column("external_delivery_reference", sa.String(length=500), nullable=True),
        sa.Column("external_delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledgement_reference", sa.String(length=500), nullable=True),
        sa.Column("response_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filing_identifier", sa.String(length=255), nullable=True),
        sa.Column("filing_reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("filing_evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("filing_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("actual_cost_item_id", sa.String(length=36), nullable=True),
        sa.Column("spend_record_id", sa.String(length=36), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "instruction_version > 0", name="ck_ip_foreign_associate_version_positive"
        ),
        sa.CheckConstraint(
            "row_version > 0", name="ck_ip_foreign_associate_row_version_positive"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'approved', 'dispatched', 'acknowledged', "
            "'in_progress', 'filing_reported', 'evidence_verified', 'invoiced', "
            "'completed', 'refused', 'superseded', 'cancelled')",
            name="ck_ip_foreign_associate_status",
        ),
        sa.CheckConstraint(
            "source_client_instruction_id IS NOT NULL OR "
            "(client_authority_reference IS NOT NULL AND "
            "length(trim(client_authority_reference)) > 0)",
            name="ck_ip_foreign_associate_client_authority",
        ),
        sa.CheckConstraint(
            "supersedes_instruction_id IS NULL OR supersedes_instruction_id <> id",
            name="ck_ip_foreign_associate_supersedes_not_self",
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'cancelled') OR "
            "(approved_at IS NOT NULL AND approved_by_membership_id IS NOT NULL)",
            name="ck_ip_foreign_associate_approved_state",
        ),
        sa.CheckConstraint(
            "dispatch_communication_id IS NULL OR external_dispatch_reference IS NULL",
            name="ck_ip_foreign_associate_single_dispatch_owner",
        ),
        sa.CheckConstraint(
            "status NOT IN ('dispatched', 'acknowledged', 'in_progress', "
            "'filing_reported', 'evidence_verified', 'invoiced', 'completed', "
            "'refused', 'superseded') OR "
            "(dispatch_communication_id IS NOT NULL OR "
            "external_dispatch_reference IS NOT NULL)",
            name="ck_ip_foreign_associate_dispatch_required",
        ),
        sa.CheckConstraint(
            "status NOT IN ('acknowledged', 'in_progress', 'filing_reported', "
            "'evidence_verified', 'invoiced', 'completed') OR "
            "(acknowledged_at IS NOT NULL AND acknowledgement_reference IS NOT NULL)",
            name="ck_ip_foreign_associate_acknowledgement_required",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_foreign_associate_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_client_instruction_id", "company_id"],
            ["ip_client_instructions.id", "ip_client_instructions.company_id"],
            name="fk_ip_foreign_associate_client_instruction_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_instruction_id", "company_id"],
            [
                "ip_foreign_associate_instructions.id",
                "ip_foreign_associate_instructions.company_id",
            ],
            name="fk_ip_foreign_associate_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["responsible_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_foreign_associate_responsible_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_foreign_associate_approver_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["privileged_approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_foreign_associate_privileged_approver_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_foreign_associate_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_foreign_associate_updater_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["outside_counsel_id"], ["outside_counsel.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["assignment_id"],
            ["matter_outside_counsel_assignments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["estimate_cost_item_id"], ["ip_cost_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["dispatch_communication_id"], ["communications.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["actual_cost_item_id"], ["ip_cost_items.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["spend_record_id"],
            ["outside_counsel_spend_records.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_foreign_associate_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "instruction_thread_key",
            "instruction_version",
            name="uq_ip_foreign_associate_thread_version",
        ),
    )
    op.create_index(
        "ix_ip_foreign_associate_instructions_docket_id",
        "ip_foreign_associate_instructions",
        ["docket_id"],
    )
    op.create_index(
        "ix_ip_foreign_associate_company_docket_status",
        "ip_foreign_associate_instructions",
        ["company_id", "docket_id", "status"],
    )
    op.create_index(
        "ix_ip_foreign_associate_company_response_due",
        "ip_foreign_associate_instructions",
        ["company_id", "response_due_at", "status"],
    )
    for column in (
        "outside_counsel_id",
        "assignment_id",
        "source_client_instruction_id",
        "supersedes_instruction_id",
        "responsible_membership_id",
        "approved_by_membership_id",
        "privileged_approved_by_membership_id",
        "created_by_membership_id",
        "updated_by_membership_id",
        "dispatch_communication_id",
        "estimate_cost_item_id",
        "actual_cost_item_id",
        "spend_record_id",
    ):
        op.create_index(
            f"ix_ip_foreign_associate_{column}",
            "ip_foreign_associate_instructions",
            [column],
        )

    with op.batch_alter_table("ip_docket_events") as batch:
        batch.add_column(
            sa.Column("foreign_associate_instruction_id", sa.String(length=36), nullable=True)
        )
        batch.create_foreign_key(
            "fk_ip_docket_event_foreign_associate_instruction_company",
            "ip_foreign_associate_instructions",
            ["foreign_associate_instruction_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_ip_docket_event_foreign_associate_kind",
            "foreign_associate_instruction_id IS NULL OR "
            "event_kind = 'foreign_associate_instruction_transaction'",
        )
        batch.create_index(
            "ix_ip_docket_events_foreign_associate_instruction_id",
            ["foreign_associate_instruction_id"],
        )
        batch.create_index(
            "ix_ip_docket_events_company_foreign_associate_sequence",
            ["company_id", "foreign_associate_instruction_id", "sequence"],
        )


def downgrade() -> None:
    _set_lock_timeout()
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM ip_foreign_associate_instructions LIMIT 1")
    ).first():
        raise RuntimeError("Restore-forward required: foreign-associate instructions exist.")
    if bind.execute(
        sa.text(
            "SELECT 1 FROM ip_docket_events "
            "WHERE foreign_associate_instruction_id IS NOT NULL LIMIT 1"
        )
    ).first():
        raise RuntimeError("Restore-forward required: linked foreign-associate events exist.")
    with op.batch_alter_table("ip_docket_events") as batch:
        batch.drop_index("ix_ip_docket_events_company_foreign_associate_sequence")
        batch.drop_index("ix_ip_docket_events_foreign_associate_instruction_id")
        batch.drop_constraint(
            "ck_ip_docket_event_foreign_associate_kind", type_="check"
        )
        batch.drop_constraint(
            "fk_ip_docket_event_foreign_associate_instruction_company",
            type_="foreignkey",
        )
        batch.drop_column("foreign_associate_instruction_id")
    op.drop_table("ip_foreign_associate_instructions")
