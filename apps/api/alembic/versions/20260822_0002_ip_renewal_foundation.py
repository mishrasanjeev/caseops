"""Add the IPLF-037A renewal and client-instruction foundation.

Revision ID: 20260822_0002
Revises: 20260822_0001
Create Date: 2026-08-22

The two new tenant-scoped tables link renewal legal state to the existing
deadline, docket-event, cost, document, communication, and membership owners.
They do not duplicate operational calendars, billing/payment state, document
bytes, provider delivery state, or notification delivery.

MIGRATION-LOCK-RISK: additive table and index DDL only; no existing row is
rewritten. PostgreSQL takes brief catalogue locks while creating empty tables.
MIGRATION-ROLLBACK: safe before dependent renewal data is relied upon; the
downgrade drops only these new tables and their indexes.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260822_0002"
down_revision = "20260822_0001"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def upgrade() -> None:
    op.create_table(
        "ip_renewal_terms",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("term_sequence", sa.Integer(), nullable=False),
        sa.Column("registration_event_id", sa.String(length=36), nullable=False),
        sa.Column("renewal_deadline_id", sa.String(length=36), nullable=False),
        sa.Column("grace_deadline_id", sa.String(length=36), nullable=True),
        sa.Column("fee_cost_item_id", sa.String(length=36), nullable=True),
        sa.Column("filing_initiated_reference", sa.String(length=500), nullable=True),
        sa.Column("filing_event_id", sa.String(length=36), nullable=True),
        sa.Column("acceptance_event_id", sa.String(length=36), nullable=True),
        sa.Column("certificate_document_id", sa.String(length=36), nullable=True),
        sa.Column("next_term_deadline_id", sa.String(length=36), nullable=True),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "term_sequence > 0", name="ck_ip_renewal_term_sequence_positive"
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_renewal_term_version_positive"),
        sa.CheckConstraint(
            "state IN ('due', 'instructed', 'filing_in_progress', 'filed', "
            "'accepted', 'grace', 'overdue', 'completed', 'cancelled')",
            name="ck_ip_renewal_term_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('filed', 'accepted', 'completed') OR filing_event_id IS NOT NULL",
            name="ck_ip_renewal_term_filed_evidence",
        ),
        sa.CheckConstraint(
            "state NOT IN ('accepted', 'completed') OR acceptance_event_id IS NOT NULL",
            name="ck_ip_renewal_term_acceptance_evidence",
        ),
        sa.CheckConstraint(
            "state <> 'completed' OR (certificate_document_id IS NOT NULL "
            "AND next_term_deadline_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_ip_renewal_term_completion_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_renewal_term_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["registration_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_registration_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["renewal_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_deadline_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["grace_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_grace_deadline_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["filing_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_filing_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acceptance_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_renewal_term_acceptance_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["next_term_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_renewal_term_next_deadline_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["certificate_document_id", "company_id"],
            ["ip_documents.id", "ip_documents.company_id"],
            name="fk_ip_renewal_term_certificate_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["fee_cost_item_id"],
            ["ip_cost_items.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_renewal_term_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_renewal_term_updater_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_renewal_term_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "docket_id",
            "registration_event_id",
            "renewal_deadline_id",
            name="uq_ip_renewal_term_legal_basis",
        ),
    )
    op.create_index(
        "ix_ip_renewal_terms_company_state_deadline",
        "ip_renewal_terms",
        ["company_id", "state", "renewal_deadline_id"],
    )

    op.create_table(
        "ip_client_instructions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("renewal_term_id", sa.String(length=36), nullable=False),
        sa.Column("instruction_version", sa.Integer(), nullable=False),
        sa.Column("row_version", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scope_json", sa.JSON(), nullable=False),
        sa.Column("options_json", sa.JSON(), nullable=False),
        sa.Column("instruction_deadline_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_channel", sa.String(length=40), nullable=False),
        sa.Column("source_communication_id", sa.String(length=36), nullable=True),
        sa.Column("authority_name", sa.String(length=255), nullable=False),
        sa.Column("authority_reference", sa.String(length=255), nullable=True),
        sa.Column("evidence_refs_json", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("acknowledged_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("acknowledgement_reason", sa.Text(), nullable=True),
        sa.Column("supersedes_instruction_id", sa.String(length=36), nullable=True),
        sa.Column("resulting_event_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "instruction_version > 0",
            name="ck_ip_client_instruction_version_positive",
        ),
        sa.CheckConstraint(
            "row_version > 0", name="ck_ip_client_instruction_row_version_positive"
        ),
        sa.CheckConstraint(
            "decision IN ('renew', 'do_not_renew', 'defer', 'clarification_required')",
            name="ck_ip_client_instruction_decision",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected', 'clarification_required', "
            "'superseded')",
            name="ck_ip_client_instruction_status",
        ),
        sa.CheckConstraint(
            "supersedes_instruction_id IS NULL OR supersedes_instruction_id <> id",
            name="ck_ip_client_instruction_supersedes_not_self",
        ),
        sa.CheckConstraint(
            "status NOT IN ('accepted', 'rejected', 'clarification_required') OR "
            "(acknowledged_at IS NOT NULL AND acknowledged_by_membership_id IS NOT NULL)",
            name="ck_ip_client_instruction_acknowledged",
        ),
        sa.CheckConstraint(
            "resulting_event_id IS NULL OR status = 'accepted'",
            name="ck_ip_client_instruction_result_requires_acceptance",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_client_instruction_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["renewal_term_id", "company_id"],
            ["ip_renewal_terms.id", "ip_renewal_terms.company_id"],
            name="fk_ip_client_instruction_renewal_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_instruction_id", "company_id"],
            ["ip_client_instructions.id", "ip_client_instructions.company_id"],
            name="fk_ip_client_instruction_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["resulting_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_client_instruction_result_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_communication_id"],
            ["communications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_client_instruction_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acknowledged_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_client_instruction_acknowledger_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_client_instruction_id_company"),
        sa.UniqueConstraint(
            "renewal_term_id",
            "instruction_version",
            name="uq_ip_client_instruction_term_version",
        ),
    )
    op.create_index(
        "ix_ip_client_instructions_company_term_status",
        "ip_client_instructions",
        ["company_id", "renewal_term_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_client_instructions_company_term_status",
        table_name="ip_client_instructions",
    )
    op.drop_table("ip_client_instructions")
    op.drop_index(
        "ix_ip_renewal_terms_company_state_deadline",
        table_name="ip_renewal_terms",
    )
    op.drop_table("ip_renewal_terms")
