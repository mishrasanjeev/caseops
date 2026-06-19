"""GBA law office PRD foundation.

Revision ID: 20260606_0001
Revises: 20260531_0001
Create Date: 2026-06-06 16:30:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260606_0001"
down_revision = "20260531_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def _create_index(table: str, column: str) -> None:
    op.create_index(op.f(f"ix_{table}_{column}"), table, [column])


def _drop_index(table: str, column: str) -> None:
    op.drop_index(op.f(f"ix_{table}_{column}"), table_name=table)


def upgrade() -> None:
    op.execute("UPDATE matters SET status = 'disposed' WHERE status = 'closed'")

    op.create_table(
        "matter_billing_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("firm_legal_name", sa.String(length=255), nullable=True),
        sa.Column("firm_address", sa.Text(), nullable=True),
        sa.Column("firm_gstin", sa.String(length=32), nullable=True),
        sa.Column("firm_pan", sa.String(length=16), nullable=True),
        sa.Column("default_place_of_supply", sa.String(length=120), nullable=True),
        sa.Column("default_sac_hsn", sa.String(length=32), nullable=True),
        sa.Column("gst_applicable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("gstin_state_code", sa.String(length=2), nullable=True),
        sa.Column("cgst_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sgst_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("igst_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tax_rate_bps", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("invoice_prefix", sa.String(length=40), nullable=False, server_default="INV"),
        sa.Column("next_invoice_sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("billing_mode", sa.String(length=24), nullable=False, server_default="hourly"),
        sa.Column("default_rate_minor_per_hour", sa.Integer(), nullable=True),
        sa.Column("notes_template", sa.Text(), nullable=True),
        sa.Column("footer_text", sa.Text(), nullable=True),
        sa.Column("invoice_template_json", sa.JSON(), nullable=True),
        sa.Column("expense_categories_json", sa.JSON(), nullable=True),
        sa.Column("retainer_adjustments_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "name", name="uq_matter_billing_profile_name"),
    )
    for column in ("company_id", "is_default", "billing_mode"):
        _create_index("matter_billing_profiles", column)

    op.create_table(
        "matter_billing_rates",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("billing_profile_id", sa.String(length=36), nullable=False),
        sa.Column("rate_scope", sa.String(length=32), nullable=False),
        sa.Column("membership_id", sa.String(length=36), nullable=True),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("practice_area", sa.String(length=120), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("amount_minor_per_hour", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["billing_profile_id"], ["matter_billing_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["membership_id"], ["company_memberships.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "company_id",
        "billing_profile_id",
        "rate_scope",
        "membership_id",
        "role",
        "practice_area",
        "effective_from",
        "effective_to",
        "is_active",
    ):
        _create_index("matter_billing_rates", column)

    for column in (
        sa.Column("case_number", sa.String(length=120), nullable=True),
        sa.Column("cnr_number", sa.String(length=32), nullable=True),
        sa.Column("next_hearing_source", sa.String(length=40), nullable=False, server_default="unknown"),
        sa.Column("next_hearing_source_ref_type", sa.String(length=40), nullable=True),
        sa.Column("next_hearing_source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("next_hearing_updated_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("next_hearing_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_hearing_manual_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("billing_profile_id", sa.String(length=36), nullable=True),
    ):
        op.add_column("matters", column)
    for column in (
        "case_number",
        "cnr_number",
        "next_hearing_updated_by_membership_id",
        "billing_profile_id",
    ):
        _create_index("matters", column)

    op.create_table(
        "matter_compliance_extraction_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("court_order_id", sa.String(length=36), nullable=True),
        sa.Column("attachment_id", sa.String(length=36), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("trigger", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("skip_reason", sa.String(length=255), nullable=True),
        sa.Column("model_run_id", sa.String(length=36), nullable=True),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message_redacted", sa.Text(), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["attachment_id"], ["matter_attachments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["court_order_id"], ["matter_court_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["model_run_id"], ["model_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in (
        "company_id",
        "matter_id",
        "court_order_id",
        "attachment_id",
        "source_type",
        "trigger",
        "status",
        "model_run_id",
        "source_hash",
        "created_by_membership_id",
    ):
        _create_index("matter_compliance_extraction_runs", column)

    op.create_table(
        "matter_compliance_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("court_order_id", sa.String(length=36), nullable=True),
        sa.Column("attachment_id", sa.String(length=36), nullable=True),
        sa.Column("extraction_run_id", sa.String(length=36), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("responsible_party", sa.String(length=255), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("timeline_text", sa.String(length=500), nullable=True),
        sa.Column("filing_requirement", sa.String(length=500), nullable=True),
        sa.Column("court_direction", sa.Text(), nullable=True),
        sa.Column("next_action", sa.Text(), nullable=True),
        sa.Column("source_snippet", sa.Text(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_paragraph", sa.String(length=120), nullable=True),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="low"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("review_status", sa.String(length=32), nullable=False, server_default="review_required"),
        sa.Column("generated_task_id", sa.String(length=36), nullable=True),
        sa.Column("generated_deadline_id", sa.String(length=36), nullable=True),
        sa.Column("dedupe_key", sa.String(length=80), nullable=False),
        sa.Column("source_hash", sa.String(length=64), nullable=True),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("waived_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["attachment_id"], ["matter_attachments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["court_order_id"], ["matter_court_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["extraction_run_id"], ["matter_compliance_extraction_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_deadline_id"], ["matter_deadlines.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["generated_task_id"], ["matter_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("matter_id", "court_order_id", "dedupe_key", name="uq_matter_compliance_order_key"),
        sa.UniqueConstraint("matter_id", "attachment_id", "dedupe_key", name="uq_matter_compliance_attachment_key"),
    )
    for column in (
        "company_id",
        "matter_id",
        "court_order_id",
        "attachment_id",
        "extraction_run_id",
        "due_on",
        "confidence_label",
        "status",
        "review_status",
        "generated_task_id",
        "generated_deadline_id",
        "dedupe_key",
        "source_hash",
        "reviewed_by_membership_id",
    ):
        _create_index("matter_compliance_items", column)

    op.create_table(
        "matter_next_hearing_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("old_date", sa.Date(), nullable=True),
        sa.Column("new_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_ref_type", sa.String(length=40), nullable=True),
        sa.Column("source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("changed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("manual_lock", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["changed_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_id", "matter_id", "source", "changed_by_membership_id"):
        _create_index("matter_next_hearing_history", column)

    op.create_table(
        "matter_next_hearing_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("suggested_date", sa.Date(), nullable=False),
        sa.Column("existing_date", sa.Date(), nullable=True),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("source_ref_type", sa.String(length=40), nullable=True),
        sa.Column("source_ref_id", sa.String(length=64), nullable=True),
        sa.Column("confidence_label", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="pending"),
        sa.Column("decided_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["decided_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "matter_id",
            "suggested_date",
            "source",
            "source_ref_type",
            "source_ref_id",
            name="uq_matter_next_hearing_suggestion_source",
        ),
    )
    for column in ("company_id", "matter_id", "suggested_date", "source", "status", "decided_by_membership_id"):
        _create_index("matter_next_hearing_suggestions", column)

    for column in (
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("backlog_remaining_count", sa.Integer(), nullable=False, server_default="0"),
    ):
        op.add_column("tracked_case_poll_runs", column)

    for column in (
        sa.Column("billing_rate_id", sa.String(length=36), nullable=True),
        sa.Column("rate_source", sa.String(length=40), nullable=True),
    ):
        op.add_column("matter_time_entries", column)
    _create_index("matter_time_entries", "billing_rate_id")

    for column in (
        sa.Column("billing_profile_id", sa.String(length=36), nullable=True),
        sa.Column("client_billing_name", sa.String(length=255), nullable=True),
        sa.Column("client_billing_address", sa.Text(), nullable=True),
        sa.Column("client_gstin", sa.String(length=32), nullable=True),
        sa.Column("place_of_supply", sa.String(length=120), nullable=True),
        sa.Column("sac_hsn", sa.String(length=32), nullable=True),
        sa.Column("firm_legal_name", sa.String(length=255), nullable=True),
        sa.Column("firm_address", sa.Text(), nullable=True),
        sa.Column("firm_gstin", sa.String(length=32), nullable=True),
        sa.Column("firm_pan", sa.String(length=16), nullable=True),
        sa.Column("taxable_value_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cgst_amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sgst_amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("igst_amount_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tds_deducted_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payment_adjustment_minor", sa.Integer(), nullable=False, server_default="0"),
    ):
        op.add_column("matter_invoices", column)
    _create_index("matter_invoices", "billing_profile_id")
    op.execute("UPDATE matter_invoices SET taxable_value_minor = subtotal_amount_minor")

    for column in (
        sa.Column("category", sa.String(length=80), nullable=True),
        sa.Column("sac_hsn", sa.String(length=32), nullable=True),
    ):
        op.add_column("matter_invoice_line_items", column)

    op.create_table(
        "matter_invoice_exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("invoice_id", sa.String(length=36), nullable=False),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="pdf"),
        sa.Column("generated_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("template_version", sa.String(length=40), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["invoice_id"], ["matter_invoices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["matter_id"], ["matters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_id", "matter_id", "invoice_id", "generated_by_membership_id"):
        _create_index("matter_invoice_exports", column)

    op.create_table(
        "cause_list_exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("generated_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("format", sa.String(length=16), nullable=False, server_default="pdf"),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="completed"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["generated_by_membership_id"], ["company_memberships.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("company_id", "generated_by_membership_id", "date_from", "date_to"):
        _create_index("cause_list_exports", column)


def downgrade() -> None:
    op.drop_table("cause_list_exports")
    op.drop_table("matter_invoice_exports")

    for column in ("sac_hsn", "category"):
        op.drop_column("matter_invoice_line_items", column)

    _drop_index("matter_invoices", "billing_profile_id")
    for column in (
        "payment_adjustment_minor",
        "tds_deducted_minor",
        "igst_amount_minor",
        "sgst_amount_minor",
        "cgst_amount_minor",
        "taxable_value_minor",
        "firm_pan",
        "firm_gstin",
        "firm_address",
        "firm_legal_name",
        "sac_hsn",
        "place_of_supply",
        "client_gstin",
        "client_billing_address",
        "client_billing_name",
        "billing_profile_id",
    ):
        op.drop_column("matter_invoices", column)

    _drop_index("matter_time_entries", "billing_rate_id")
    for column in ("rate_source", "billing_rate_id"):
        op.drop_column("matter_time_entries", column)

    for column in (
        "backlog_remaining_count",
        "provider_call_count",
        "blocked_count",
        "skipped_count",
    ):
        op.drop_column("tracked_case_poll_runs", column)

    op.drop_table("matter_next_hearing_suggestions")
    op.drop_table("matter_next_hearing_history")
    op.drop_table("matter_compliance_items")
    op.drop_table("matter_compliance_extraction_runs")

    for column in (
        "billing_profile_id",
        "next_hearing_updated_by_membership_id",
        "cnr_number",
        "case_number",
    ):
        _drop_index("matters", column)
    for column in (
        "billing_profile_id",
        "next_hearing_manual_lock",
        "next_hearing_updated_at",
        "next_hearing_updated_by_membership_id",
        "next_hearing_source_ref_id",
        "next_hearing_source_ref_type",
        "next_hearing_source",
        "cnr_number",
        "case_number",
    ):
        op.drop_column("matters", column)

    op.drop_table("matter_billing_rates")
    op.drop_table("matter_billing_profiles")
    op.execute("UPDATE matters SET status = 'closed' WHERE status = 'disposed'")
