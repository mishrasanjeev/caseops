"""Add versioned IP deadline, rule, calendar and responsibility evidence.

Revision ID: 20260807_0005
Revises: 20260807_0004
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260807_0005"
down_revision = "20260807_0004"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def upgrade() -> None:
    op.create_table(
        "legal_working_calendars",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("office", sa.String(120), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_legal_working_calendar_id_company"),
        sa.UniqueConstraint("company_id", "key", name="uq_legal_working_calendar_company_key"),
    )
    op.create_index(
        "ix_legal_working_calendars_company_id",
        "legal_working_calendars",
        ["company_id"],
    )
    op.create_index(
        "ix_legal_working_calendars_scope",
        "legal_working_calendars",
        ["company_id", "jurisdiction", "office"],
    )
    op.create_index(
        "ix_legal_working_calendars_created_by_membership_id",
        "legal_working_calendars",
        ["created_by_membership_id"],
    )

    op.create_table(
        "legal_working_calendar_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("calendar_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("weekend_days_json", sa.JSON(), nullable=False),
        sa.Column("holidays_json", sa.JSON(), nullable=False),
        sa.Column("exceptional_working_days_json", sa.JSON(), nullable=False),
        sa.Column("source_priority_json", sa.JSON(), nullable=False),
        sa.Column("source_reference", sa.String(512), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("proposed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("proposer_label_snapshot", sa.String(255), nullable=False),
        sa.Column("approved_by_membership_id", sa.String(36), nullable=True),
        sa.Column("approver_label_snapshot", sa.String(255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["calendar_id", "company_id"],
            ["legal_working_calendars.id", "legal_working_calendars.company_id"],
            name="fk_legal_calendar_version_calendar_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_calendar_version_proposer_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_calendar_version_approver_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_legal_calendar_version_id_company"),
        sa.UniqueConstraint("calendar_id", "version", name="uq_legal_calendar_version_number"),
        sa.CheckConstraint("version > 0", name="ck_legal_calendar_version_positive"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_legal_calendar_version_effective_range",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_legal_calendar_version_status",
        ),
    )
    op.create_index(
        "ix_legal_working_calendar_versions_company_id",
        "legal_working_calendar_versions",
        ["company_id"],
    )
    op.create_index(
        "ix_legal_working_calendar_versions_calendar_id",
        "legal_working_calendar_versions",
        ["calendar_id"],
    )
    for column in ("proposed_by_membership_id", "approved_by_membership_id"):
        op.create_index(
            f"ix_legal_working_calendar_versions_{column}",
            "legal_working_calendar_versions",
            [column],
        )

    op.create_table(
        "ip_rule_sets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("key", sa.String(160), nullable=False),
        sa.Column("rule_kind", sa.String(24), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("office", sa.String(120), nullable=True),
        sa.Column("right_kind", sa.String(40), nullable=False),
        sa.Column("proceeding_kind", sa.String(40), nullable=True),
        sa.Column("role", sa.String(40), nullable=True),
        sa.Column("stage", sa.String(80), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key", name="uq_ip_rule_set_key"),
        sa.CheckConstraint("rule_kind IN ('deadline', 'form', 'fee')", name="ck_ip_rule_set_kind"),
    )

    op.create_table(
        "ip_rule_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rule_set_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source_record_id", sa.String(120), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_reference", sa.String(512), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_until", sa.Date(), nullable=True),
        sa.Column("engine_compatibility", sa.String(80), nullable=False),
        sa.Column("fixture_set_json", sa.JSON(), nullable=False),
        sa.Column("definition_json", sa.JSON(), nullable=False),
        sa.Column("proposed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("proposer_label_snapshot", sa.String(255), nullable=False),
        sa.Column("reviewed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("reviewer_label_snapshot", sa.String(255), nullable=True),
        sa.Column("legal_approved_by_membership_id", sa.String(36), nullable=True),
        sa.Column("legal_approver_label_snapshot", sa.String(255), nullable=True),
        sa.Column("fixtures_passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["rule_set_id"], ["ip_rule_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["proposed_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["legal_approved_by_membership_id"],
            ["company_memberships.id"],
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("id", "rule_set_id", name="uq_ip_rule_version_id_set"),
        sa.UniqueConstraint("rule_set_id", "version", name="uq_ip_rule_version_number"),
        sa.CheckConstraint("version > 0", name="ck_ip_rule_version_positive"),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_rule_version_effective_range",
        ),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_ip_rule_version_status",
        ),
        sa.CheckConstraint(
            "proposed_by_membership_id IS NULL OR legal_approved_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> legal_approved_by_membership_id",
            name="ck_ip_rule_version_legal_approver_distinct",
        ),
    )
    op.create_index("ix_ip_rule_versions_rule_set_id", "ip_rule_versions", ["rule_set_id"])
    for column in (
        "proposed_by_membership_id",
        "reviewed_by_membership_id",
        "legal_approved_by_membership_id",
    ):
        op.create_index(f"ix_ip_rule_versions_{column}", "ip_rule_versions", [column])

    op.create_table(
        "company_ip_rule_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("rule_set_id", sa.String(36), nullable=False),
        sa.Column("active_rule_version_id", sa.String(36), nullable=False),
        sa.Column("auto_confirm_eligible", sa.Boolean(), nullable=False),
        sa.Column("internal_target_policy_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(36), nullable=True),
        sa.Column("updater_label_snapshot", sa.String(255), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["ip_rule_sets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["active_rule_version_id", "rule_set_id"],
            ["ip_rule_versions.id", "ip_rule_versions.rule_set_id"],
            name="fk_company_ip_policy_version_set",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("company_id", "rule_set_id", name="uq_company_ip_rule_policy"),
        sa.CheckConstraint("version > 0", name="ck_company_ip_rule_policy_version_positive"),
    )
    op.create_index(
        "ix_company_ip_rule_policies_company_id",
        "company_ip_rule_policies",
        ["company_id"],
    )
    for column in ("rule_set_id", "active_rule_version_id", "updated_by_membership_id"):
        op.create_index(
            f"ix_company_ip_rule_policies_{column}",
            "company_ip_rule_policies",
            [column],
        )

    op.create_table(
        "ip_deadlines",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("trigger_event_id", sa.String(36), nullable=True),
        sa.Column("rule_version_id", sa.String(36), nullable=False),
        sa.Column("calendar_version_id", sa.String(36), nullable=False),
        sa.Column("matter_deadline_id", sa.String(36), nullable=True),
        sa.Column("supersedes_deadline_id", sa.String(36), nullable=True),
        sa.Column("deadline_kind", sa.String(40), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("trigger_kind", sa.String(80), nullable=False),
        sa.Column("base_date", sa.Date(), nullable=True),
        sa.Column("duration_value", sa.Integer(), nullable=True),
        sa.Column("duration_unit", sa.String(32), nullable=True),
        sa.Column("calendar_method", sa.String(64), nullable=False),
        sa.Column("timezone", sa.String(64), nullable=False),
        sa.Column("date_precision", sa.String(16), nullable=False),
        sa.Column("certainty", sa.String(24), nullable=False),
        sa.Column("result_on", sa.Date(), nullable=True),
        sa.Column("result_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("calculation_inputs_json", sa.JSON(), nullable=False),
        sa.Column("calculation_trace_json", sa.JSON(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("rule_citation", sa.String(512), nullable=False),
        sa.Column("engine_version", sa.String(80), nullable=False),
        sa.Column("source_version", sa.String(120), nullable=False),
        sa.Column("is_critical", sa.Boolean(), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("confirmer_label_snapshot", sa.String(255), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("override_reason", sa.Text(), nullable=True),
        sa.Column("override_evidence_ref", sa.String(512), nullable=True),
        sa.Column("completed_evidence_ref", sa.String(512), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column("creator_label_snapshot", sa.String(255), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_deadline_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_deadline_trigger_event_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["rule_version_id"], ["ip_rule_versions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["calendar_version_id", "company_id"],
            ["legal_working_calendar_versions.id", "legal_working_calendar_versions.company_id"],
            name="fk_ip_deadline_calendar_version_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["matter_deadline_id"], ["matter_deadlines.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_deadline_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_deadline_id_company"),
        sa.UniqueConstraint("matter_deadline_id", name="uq_ip_deadline_operational_projection"),
        sa.CheckConstraint("version > 0", name="ck_ip_deadline_version_positive"),
        sa.CheckConstraint(
            "state IN ('provisional', 'candidate', 'confirmed', 'overdue', 'completed', "
            "'superseded', 'cancelled')",
            name="ck_ip_deadline_state",
        ),
        sa.CheckConstraint(
            "date_precision IN ('unknown', 'date', 'datetime', 'session')",
            name="ck_ip_deadline_precision",
        ),
        sa.CheckConstraint(
            "state = 'provisional' OR result_on IS NOT NULL OR result_at IS NOT NULL",
            name="ck_ip_deadline_nonprovisional_result",
        ),
    )
    for column in (
        "docket_id",
        "trigger_event_id",
        "rule_version_id",
        "calendar_version_id",
        "matter_deadline_id",
        "supersedes_deadline_id",
        "confirmed_by_membership_id",
        "created_by_membership_id",
        "result_on",
    ):
        op.create_index(f"ix_ip_deadlines_{column}", "ip_deadlines", [column])
    op.create_index(
        "ix_ip_deadlines_company_state_result",
        "ip_deadlines",
        ["company_id", "state", "result_on"],
    )

    op.create_table(
        "ip_responsibility_assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("deadline_id", sa.String(36), nullable=False),
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("membership_label_snapshot", sa.String(255), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delegation_reason", sa.Text(), nullable=True),
        sa.Column("replacement_source", sa.String(120), nullable=False),
        sa.Column("escalation_policy_json", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=True),
        sa.Column("creator_label_snapshot", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_responsibility_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["deadline_id", "company_id"],
            ["ip_deadlines.id", "ip_deadlines.company_id"],
            name="fk_ip_responsibility_deadline_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_responsibility_membership_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "role IN ('primary', 'backup', 'supervisor', 'docketing')",
            name="ck_ip_responsibility_role",
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_until >= effective_from",
            name="ck_ip_responsibility_effective_range",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_responsibility_version_positive"),
    )
    for column in (
        "company_id",
        "docket_id",
        "deadline_id",
        "membership_id",
        "created_by_membership_id",
    ):
        op.create_index(
            f"ix_ip_responsibility_assignments_{column}",
            "ip_responsibility_assignments",
            [column],
        )
    op.create_index(
        "ix_ip_responsibility_active_deadline_role",
        "ip_responsibility_assignments",
        ["deadline_id", "role", "effective_until"],
    )


def downgrade() -> None:
    op.drop_table("ip_responsibility_assignments")
    op.drop_table("ip_deadlines")
    op.drop_table("company_ip_rule_policies")
    op.drop_table("ip_rule_versions")
    op.drop_table("ip_rule_sets")
    op.drop_table("legal_working_calendar_versions")
    op.drop_table("legal_working_calendars")
