"""IPLF-039C increment 3: replacement acceptance and emergency coverage.

CAL-OPS-08 requires reassignment to produce an atomic preview and to require an
**accepted** replacement or **approved emergency coverage**. Reassignment
previously transferred responsibility immediately, so a replacement could be
made owner of critical work without ever accepting it.

Additive. Existing rows default to ``replacement_decision='none'``, which means
"no transfer is pending" and preserves current ownership exactly.

Revision ID: 20260815_0002
Revises: 20260815_0001

DATA-GOVERNANCE-MAP: updated
The new columns extend the existing ``ip_deadline_coverages``
``tenant_restricted_legal_content`` class and add no new class.
``pending_replacement_membership_id`` and
``emergency_escalation_membership_id`` are registered as
``tenant_or_access_identifier``; ``replacement_decision``,
``replacement_decided_at``, ``replacement_decision_reason`` and
``emergency_until`` are ``domain_attribute``. The reason field is free text
supplied by a member about a colleague's coverage, so it inherits the table's
existing tenant scoping and fail-closed disposition unchanged.
Both new membership references are also paired with ``company_id`` so a
replacement or emergency escalation target cannot cross a tenant boundary.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0002"
down_revision = "20260815_0001"
branch_labels = None
depends_on = None

TABLE = "ip_deadline_coverages"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # SQLite cannot ALTER constraints outside batch mode, so every column and
    # constraint change is applied in one copy-and-move batch.
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column("pending_replacement_membership_id", sa.String(length=36), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "replacement_decision",
                sa.String(length=16),
                nullable=False,
                server_default="none",
            )
        )
        batch.add_column(
            sa.Column("replacement_decided_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("replacement_decision_reason", sa.String(length=2000), nullable=True)
        )
        batch.add_column(sa.Column("emergency_until", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column(
                "emergency_escalation_membership_id", sa.String(length=36), nullable=True
            )
        )
        batch.create_foreign_key(
            "fk_ip_coverage_pending_replacement",
            "company_memberships",
            ["pending_replacement_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_foreign_key(
            "fk_ip_coverage_emergency_escalation",
            "company_memberships",
            ["emergency_escalation_membership_id"],
            ["id"],
            ondelete="SET NULL",
        )
        # Keep the single-column FKs above for their SET NULL action. The
        # tenant companions are deferred MATCH SIMPLE constraints: PostgreSQL
        # can first null only the nullable membership ID, never company_id,
        # and the final composite state then passes because one key is NULL.
        batch.create_foreign_key(
            "fk_ip_coverage_pending_replacement_company",
            "company_memberships",
            ["pending_replacement_membership_id", "company_id"],
            ["id", "company_id"],
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        )
        batch.create_foreign_key(
            "fk_ip_coverage_emergency_escalation_company",
            "company_memberships",
            ["emergency_escalation_membership_id", "company_id"],
            ["id", "company_id"],
            match="SIMPLE",
            deferrable=True,
            initially="DEFERRED",
        )
        batch.create_check_constraint(
            "ck_ip_coverage_replacement_decision",
            "replacement_decision IN ('none', 'pending', 'accepted', 'rejected')",
        )
        # A pending transfer must name who it is waiting on.
        batch.create_check_constraint(
            "ck_ip_coverage_pending_has_subject",
            "replacement_decision <> 'pending' OR pending_replacement_membership_id IS NOT NULL",
        )
        # Emergency cover is time-boxed by definition; it must carry an expiry
        # and someone to escalate to when it lapses.
        batch.create_check_constraint(
            "ck_ip_coverage_emergency_is_time_boxed",
            "emergency_until IS NULL OR emergency_escalation_membership_id IS NOT NULL",
        )

    op.create_index(
        "ix_ip_deadline_coverages_pending_replacement_membership_id",
        TABLE,
        ["pending_replacement_membership_id"],
    )
    op.create_index(
        "ix_ip_deadline_coverages_emergency_escalation_membership_id",
        TABLE,
        ["emergency_escalation_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_ip_deadline_coverages_emergency_escalation_membership_id", table_name=TABLE
    )
    op.drop_index(
        "ix_ip_deadline_coverages_pending_replacement_membership_id", table_name=TABLE
    )
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_ip_coverage_emergency_is_time_boxed", type_="check")
        batch.drop_constraint("ck_ip_coverage_pending_has_subject", type_="check")
        batch.drop_constraint("ck_ip_coverage_replacement_decision", type_="check")
        batch.drop_constraint(
            "fk_ip_coverage_emergency_escalation_company", type_="foreignkey"
        )
        batch.drop_constraint(
            "fk_ip_coverage_pending_replacement_company", type_="foreignkey"
        )
        batch.drop_constraint("fk_ip_coverage_emergency_escalation", type_="foreignkey")
        batch.drop_constraint("fk_ip_coverage_pending_replacement", type_="foreignkey")
        batch.drop_column("emergency_escalation_membership_id")
        batch.drop_column("emergency_until")
        batch.drop_column("replacement_decision_reason")
        batch.drop_column("replacement_decided_at")
        batch.drop_column("replacement_decision")
        batch.drop_column("pending_replacement_membership_id")
