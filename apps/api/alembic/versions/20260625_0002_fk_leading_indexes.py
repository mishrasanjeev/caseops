"""Add leading indexes for uncovered foreign keys.

Revision ID: 20260625_0002
Revises: 20260625_0001
Create Date: 2026-06-25
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision = "20260625_0002"
down_revision = "20260625_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FK_INDEXES: tuple[tuple[str, str], ...] = (
    ("matters", "court_id"),
    ("matters", "executive_summary_model_run_id"),
    ("account_setup_tokens", "created_by_membership_id"),
    ("audit_events", "actor_membership_id"),
    ("audit_events", "matter_id"),
    ("clients", "kyc_verified_by_membership_id"),
    ("clients", "created_by_membership_id"),
    ("drafts", "created_by_membership_id"),
    ("ethical_walls", "created_by_membership_id"),
    ("legal_update_source_records", "model_run_id"),
    ("matter_access_grants", "granted_by_membership_id"),
    ("matter_conflict_checks", "ran_by_membership_id"),
    ("matter_conflict_checks", "resolved_by_membership_id"),
    ("matter_deadlines", "created_by_membership_id"),
    ("platform_admin_memberships", "created_by_platform_admin_id"),
    ("portal_users", "invited_by_membership_id"),
    ("recommendations", "created_by_membership_id"),
    ("recommendations", "model_run_id"),
    ("statute_sections", "parent_section_id"),
    ("tenant_contract_playbooks", "created_by_membership_id"),
    ("billing_coupons", "created_by_platform_admin_id"),
    ("billing_enrollments", "sales_owner_platform_admin_id"),
    ("billing_overage_policies", "approved_by_platform_admin_id"),
    ("draft_versions", "generated_by_membership_id"),
    ("draft_versions", "model_run_id"),
    ("hearing_packs", "generated_by_membership_id"),
    ("hearing_packs", "reviewed_by_membership_id"),
    ("hearing_packs", "model_run_id"),
    ("hearing_reminders", "recipient_membership_id"),
    ("judge_authority_affinity", "sample_judgment_id"),
    ("judge_statute_focus", "sample_judgment_id"),
    ("matter_portal_grants", "granted_by_membership_id"),
    ("matter_statute_references", "added_by_membership_id"),
    ("recommendation_decisions", "actor_membership_id"),
    ("tenant_contract_playbook_rules", "created_by_membership_id"),
    ("tracked_case_updates", "model_run_id"),
    ("billing_admin_notes", "created_by_platform_admin_id"),
    ("billing_manual_invoices", "created_by_platform_admin_id"),
    ("draft_reviews", "version_id"),
    ("draft_reviews", "actor_membership_id"),
    ("email_calendar_candidates", "duplicate_of_candidate_id"),
    ("email_calendar_candidates", "created_by_membership_id"),
    ("email_calendar_candidates", "reviewed_by_membership_id"),
    ("billing_coupon_redemptions", "redeemed_by_membership_id"),
)

PREEXISTING_FK_INDEXES: tuple[tuple[str, str], ...] = (
    ("audit_events", "actor_membership_id"),
    ("audit_events", "matter_id"),
)

CREATED_FK_INDEXES: tuple[tuple[str, str], ...] = tuple(
    item for item in FK_INDEXES if item not in PREEXISTING_FK_INDEXES
)

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "FK_INDEXES",
    "PREEXISTING_FK_INDEXES",
    "CREATED_FK_INDEXES",
    "upgrade",
    "downgrade",
)


def _index_name(table: str, column: str) -> str:
    return f"ix_{table}_{column}"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _create_index(table: str, column: str) -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS "
        f"{_quote_identifier(_index_name(table, column))} "
        f"ON {_quote_identifier(table)} ({_quote_identifier(column)})"
    )


def _drop_index(table: str, column: str) -> None:
    op.execute(f"DROP INDEX IF EXISTS {_quote_identifier(_index_name(table, column))}")


def upgrade() -> None:
    for table, column in CREATED_FK_INDEXES:
        _create_index(table, column)


def downgrade() -> None:
    for table, column in reversed(CREATED_FK_INDEXES):
        _drop_index(table, column)
