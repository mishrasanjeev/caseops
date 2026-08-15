"""IPLF-039C increment 7: saved daily-docket queues (CAL-OPS-09).

A queue is a named, reusable set of daily-docket filters. Scoping is enforced
at the database level: every queue is either shared with a team or owned by a
member, never neither.

Revision ID: 20260815_0003
Revises: 20260815_0002

DATA-GOVERNANCE-MAP: updated
``ip_docket_queues`` is registered as ``tenant_restricted_legal_content``. A
saved queue stores filter criteria and a name chosen by a member, which can
describe a matter or client focus, and its team scoping makes it a shared view
into that team's workload. It is tenant-scoped through ``company_id`` with the
fail-closed ``registry_fail_closed`` handler; the ``owner_membership_id`` and
``created_by_membership_id`` foreign keys are ``ON DELETE SET NULL`` so an
offboarded member's queue survives attribution loss rather than disappearing.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0003"
down_revision = "20260815_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    op.create_table(
        "ip_docket_queues",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("filters_json", sa.JSON(), nullable=False),
        sa.Column(
            "team_id",
            sa.String(length=36),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "owner_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("company_id", "name", name="uq_ip_docket_queue_company_name"),
        # A queue that belongs to nobody cannot be governed or cleaned up.
        sa.CheckConstraint(
            "team_id IS NOT NULL OR owner_membership_id IS NOT NULL",
            name="ck_ip_docket_queue_has_scope",
        ),
    )
    op.create_index("ix_ip_docket_queues_company_id", "ip_docket_queues", ["company_id"])
    op.create_index("ix_ip_docket_queues_team_id", "ip_docket_queues", ["team_id"])
    op.create_index(
        "ix_ip_docket_queues_owner_membership_id", "ip_docket_queues", ["owner_membership_id"]
    )
    op.create_index(
        "ix_ip_docket_queues_created_by_membership_id",
        "ip_docket_queues",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_ip_docket_queues_company_team", "ip_docket_queues", ["company_id", "team_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ip_docket_queues_company_team", table_name="ip_docket_queues")
    op.drop_index("ix_ip_docket_queues_created_by_membership_id", table_name="ip_docket_queues")
    op.drop_index("ix_ip_docket_queues_owner_membership_id", table_name="ip_docket_queues")
    op.drop_index("ix_ip_docket_queues_team_id", table_name="ip_docket_queues")
    op.drop_index("ix_ip_docket_queues_company_id", table_name="ip_docket_queues")
    op.drop_table("ip_docket_queues")
