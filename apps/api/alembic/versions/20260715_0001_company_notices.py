"""Add standalone tenant notice management.

Revision ID: 20260715_0001
Revises: 20260708_0001
Create Date: 2026-07-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260715_0001"
down_revision = "20260708_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = (
    "revision",
    "down_revision",
    "branch_labels",
    "depends_on",
    "upgrade",
    "downgrade",
)


def upgrade() -> None:
    with op.batch_alter_table("company_memberships") as batch_op:
        batch_op.create_unique_constraint(
            "uq_company_memberships_id_company_id",
            ["id", "company_id"],
        )

    # Matter lifecycle epoch + disposal provenance.  These columns make stale
    # async work and disposal-cancelled child records distinguishable after a
    # later reopen.
    op.add_column(
        "matters",
        sa.Column(
            "lifecycle_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "matter_conflict_checks",
        sa.Column(
            "matter_lifecycle_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    for table_name in ("matter_tasks", "matter_hearings", "matter_deadlines"):
        op.add_column(
            table_name,
            sa.Column(
                "cancelled_by_matter_disposal",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    matters = sa.table(
        "matters",
        sa.column("id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("next_hearing_on", sa.Date()),
        sa.column("next_hearing_source", sa.String()),
        sa.column("next_hearing_source_ref_type", sa.String()),
        sa.column("next_hearing_source_ref_id", sa.String()),
        sa.column("next_hearing_manual_lock", sa.Boolean()),
    )
    op.execute(
        matters.update()
        .where(matters.c.status == "closed")
        .values(status="disposed")
    )
    op.execute(
        matters.update().values(
            is_active=sa.case(
                (matters.c.status == "disposed", sa.false()),
                else_=sa.true(),
            )
        )
    )
    # Upgrade legacy terminal rows atomically. Merely renaming ``closed`` to
    # ``disposed`` leaves their open tasks/deadlines/hearings ready to reappear
    # if the Matter is later reopened to Intake. The runtime transition repeats
    # this reconciliation defensively for any inconsistent row created outside
    # the migration path.
    disposed_matter_ids = sa.select(matters.c.id).where(
        matters.c.status == "disposed"
    )
    matter_tasks = sa.table(
        "matter_tasks",
        sa.column("id", sa.String()),
        sa.column("matter_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
        sa.column("cancelled_by_matter_disposal", sa.Boolean()),
    )
    op.execute(
        matter_tasks.update()
        .where(matter_tasks.c.matter_id.in_(disposed_matter_ids))
        .where(matter_tasks.c.status.notin_(("completed", "cancelled")))
        .values(
            status="cancelled",
            completed_at=sa.func.current_timestamp(),
            cancelled_by_matter_disposal=sa.true(),
        )
    )
    matter_deadlines = sa.table(
        "matter_deadlines",
        sa.column("id", sa.String()),
        sa.column("matter_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("completed_at", sa.DateTime(timezone=True)),
        sa.column("cancelled_by_matter_disposal", sa.Boolean()),
    )
    op.execute(
        matter_deadlines.update()
        .where(matter_deadlines.c.matter_id.in_(disposed_matter_ids))
        .where(matter_deadlines.c.status.notin_(("done", "cancelled")))
        .values(
            status="cancelled",
            completed_at=sa.func.current_timestamp(),
            cancelled_by_matter_disposal=sa.true(),
        )
    )
    matter_hearings = sa.table(
        "matter_hearings",
        sa.column("id", sa.String()),
        sa.column("matter_id", sa.String()),
        sa.column("status", sa.String()),
        sa.column("cancelled_by_matter_disposal", sa.Boolean()),
    )
    op.execute(
        matter_hearings.update()
        .where(matter_hearings.c.matter_id.in_(disposed_matter_ids))
        .where(matter_hearings.c.status.in_(("scheduled", "adjourned")))
        .values(
            status="cancelled",
            cancelled_by_matter_disposal=sa.true(),
        )
    )
    calendar_event_syncs = sa.table(
        "calendar_event_syncs",
        sa.column("source_type", sa.String()),
        sa.column("source_id", sa.String()),
        sa.column("provider_event_id", sa.String()),
        sa.column("sync_status", sa.String()),
        sa.column("next_attempt_at", sa.DateTime(timezone=True)),
        sa.column("dead_letter_reason", sa.String()),
        sa.column("last_error", sa.Text()),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    # A legacy terminal Matter can already have a provider event for an open
    # child. Cancelling only the child leaves that external calendar artifact
    # alive. Queue a durable provider deletion (or mark an unsent row deleted)
    # during the same upgrade that neutralizes the child.
    for source_type, child_table in (
        ("matter_task", matter_tasks),
        ("matter_deadline", matter_deadlines),
        ("matter_hearing", matter_hearings),
    ):
        disposal_source_ids = sa.select(child_table.c.id).where(
            child_table.c.matter_id.in_(disposed_matter_ids),
            child_table.c.cancelled_by_matter_disposal == sa.true(),
        )
        has_provider_event = calendar_event_syncs.c.provider_event_id.is_not(None)
        op.execute(
            calendar_event_syncs.update()
            .where(calendar_event_syncs.c.source_type == source_type)
            .where(calendar_event_syncs.c.source_id.in_(disposal_source_ids))
            .where(calendar_event_syncs.c.sync_status != "deleted")
            .values(
                sync_status=sa.case(
                    (has_provider_event, "delete_pending"),
                    else_="deleted",
                ),
                next_attempt_at=sa.case(
                    (has_provider_event, sa.func.current_timestamp()),
                    else_=None,
                ),
                dead_letter_reason=sa.case(
                    (has_provider_event, "matter_disposed_delete"),
                    else_="matter_disposed",
                ),
                last_error=None,
                updated_at=sa.func.current_timestamp(),
            )
        )
    op.execute(
        matters.update()
        .where(matters.c.status == "disposed")
        .values(
            next_hearing_on=None,
            next_hearing_source="unknown",
            next_hearing_source_ref_type=None,
            next_hearing_source_ref_id=None,
            next_hearing_manual_lock=sa.false(),
        )
    )
    with op.batch_alter_table("matters") as batch_op:
        batch_op.create_unique_constraint(
            "uq_matters_id_company_id",
            ["id", "company_id"],
        )
        batch_op.create_check_constraint(
            "ck_matters_status_active_consistent",
            "(status IN ('disposed', 'closed') AND is_active = false) OR "
            "(status NOT IN ('disposed', 'closed') AND is_active = true)",
        )
        batch_op.create_check_constraint(
            "ck_matters_lifecycle_version_nonnegative",
            "lifecycle_version >= 0",
        )

    op.create_table(
        "company_notices",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("owner_membership_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column(
            "direction",
            sa.String(length=16),
            nullable=False,
            server_default="received",
        ),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("notice_type", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=80), nullable=False, server_default="Open"),
        sa.Column("authority", sa.String(length=255), nullable=True),
        sa.Column("received_from", sa.String(length=255), nullable=True),
        sa.Column("department", sa.String(length=160), nullable=True),
        sa.Column("mode", sa.String(length=80), nullable=True),
        sa.Column("internal_spoc", sa.String(length=160), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("internal_remarks", sa.Text(), nullable=True),
        sa.Column("counsel_engaged", sa.String(length=255), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=True),
        sa.Column("sent_on", sa.Date(), nullable=True),
        sa.Column("reply_due_on", sa.Date(), nullable=True),
        sa.Column(
            "reply_required",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "reply_sent",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("reply_sent_on", sa.Date(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="INR"),
        sa.Column("amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("dispute_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("recovered_amount_minor", sa.BigInteger(), nullable=True),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("storage_key", sa.String(length=500), nullable=True),
        sa.Column("content_type", sa.String(length=255), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("sha256_hex", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "direction IN ('received', 'sent')",
            name="ck_company_notices_direction",
        ),
        sa.CheckConstraint(
            "amount_minor IS NULL OR amount_minor >= 0",
            name="ck_company_notices_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "dispute_amount_minor IS NULL OR dispute_amount_minor >= 0",
            name="ck_company_notices_dispute_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "recovered_amount_minor IS NULL OR recovered_amount_minor >= 0",
            name="ck_company_notices_recovered_amount_nonnegative",
        ),
        sa.CheckConstraint(
            "length(currency) = 3",
            name="ck_company_notices_currency_length",
        ),
        sa.CheckConstraint(
            "reply_sent_on IS NULL OR (reply_sent = true AND reply_required = true)",
            name="ck_company_notices_reply_sent_date_state",
        ),
        sa.CheckConstraint(
            "(direction = 'received' AND sent_on IS NULL) OR "
            "(direction = 'sent' AND received_on IS NULL "
            "AND received_from IS NULL AND reply_due_on IS NULL "
            "AND reply_required = false AND reply_sent = false "
            "AND reply_sent_on IS NULL)",
            name="ck_company_notices_direction_fields_consistent",
        ),
        sa.CheckConstraint(
            "reply_sent = false OR reply_required = true",
            name="ck_company_notices_reply_sent_requires_required",
        ),
        sa.CheckConstraint(
            "reply_due_on IS NULL OR reply_required = true",
            name="ck_company_notices_reply_due_requires_required",
        ),
        sa.CheckConstraint(
            "(storage_key IS NULL AND original_filename IS NULL "
            "AND content_type IS NULL AND size_bytes IS NULL "
            "AND sha256_hex IS NULL) OR "
            "(storage_key IS NOT NULL AND original_filename IS NOT NULL "
            "AND size_bytes IS NOT NULL AND size_bytes >= 0 "
            "AND sha256_hex IS NOT NULL)",
            name="ck_company_notices_file_metadata_state",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_membership_id"],
            ["company_memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id"],
            ["company_memberships.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["owner_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_company_notices_owner_membership_company",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_company_notices_creator_membership_company",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "company_id",
            name="uq_company_notices_id_company_id",
        ),
        sa.UniqueConstraint("storage_key", name="uq_company_notices_storage_key"),
    )
    op.create_index(
        "ix_company_notices_company_id",
        "company_notices",
        ["company_id"],
    )
    op.create_index(
        "ix_company_notices_owner_membership_id",
        "company_notices",
        ["owner_membership_id"],
    )
    op.create_index(
        "ix_company_notices_created_by_membership_id",
        "company_notices",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_company_notices_direction",
        "company_notices",
        ["direction"],
    )
    op.create_index("ix_company_notices_status", "company_notices", ["status"])
    op.create_index(
        "ix_company_notices_received_on",
        "company_notices",
        ["received_on"],
    )
    op.create_index("ix_company_notices_sent_on", "company_notices", ["sent_on"])
    op.create_index(
        "ix_company_notices_reply_due_on",
        "company_notices",
        ["reply_due_on"],
    )
    op.create_index(
        "ix_company_notices_created_at",
        "company_notices",
        ["created_at"],
    )

    op.create_table(
        "company_notice_matter_links",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("notice_id", sa.String(length=36), nullable=False),
        sa.Column("matter_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["notice_id", "company_id"],
            ["company_notices.id", "company_notices.company_id"],
            name="fk_company_notice_links_notice_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_company_notice_links_matter_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "notice_id",
            "matter_id",
            name="uq_company_notice_matter_link",
        ),
    )
    op.create_index(
        "ix_company_notice_matter_links_company_id",
        "company_notice_matter_links",
        ["company_id"],
    )
    op.create_index(
        "ix_company_notice_matter_links_notice_id",
        "company_notice_matter_links",
        ["notice_id"],
    )
    op.create_index(
        "ix_company_notice_matter_links_matter_id",
        "company_notice_matter_links",
        ["matter_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_notice_matter_links_matter_id",
        table_name="company_notice_matter_links",
    )
    op.drop_index(
        "ix_company_notice_matter_links_notice_id",
        table_name="company_notice_matter_links",
    )
    op.drop_index(
        "ix_company_notice_matter_links_company_id",
        table_name="company_notice_matter_links",
    )
    op.drop_table("company_notice_matter_links")

    op.drop_index("ix_company_notices_created_at", table_name="company_notices")
    op.drop_index("ix_company_notices_reply_due_on", table_name="company_notices")
    op.drop_index("ix_company_notices_sent_on", table_name="company_notices")
    op.drop_index("ix_company_notices_received_on", table_name="company_notices")
    op.drop_index("ix_company_notices_status", table_name="company_notices")
    op.drop_index("ix_company_notices_direction", table_name="company_notices")
    op.drop_index(
        "ix_company_notices_created_by_membership_id",
        table_name="company_notices",
    )
    op.drop_index(
        "ix_company_notices_owner_membership_id",
        table_name="company_notices",
    )
    op.drop_index("ix_company_notices_company_id", table_name="company_notices")
    op.drop_table("company_notices")

    with op.batch_alter_table("matters") as batch_op:
        batch_op.drop_constraint(
            "ck_matters_lifecycle_version_nonnegative",
            type_="check",
        )
        batch_op.drop_constraint(
            "ck_matters_status_active_consistent",
            type_="check",
        )
        batch_op.drop_constraint(
            "uq_matters_id_company_id",
            type_="unique",
        )
    for table_name in ("matter_deadlines", "matter_hearings", "matter_tasks"):
        op.drop_column(table_name, "cancelled_by_matter_disposal")
    op.drop_column("matter_conflict_checks", "matter_lifecycle_version")
    op.drop_column("matters", "lifecycle_version")
    with op.batch_alter_table("company_memberships") as batch_op:
        batch_op.drop_constraint(
            "uq_company_memberships_id_company_id",
            type_="unique",
        )
