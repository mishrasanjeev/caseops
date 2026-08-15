"""IPLF-039C increment 11: external calendar drift detection (UJ-62-EXC-03).

A projected calendar event can be edited or deleted in the provider, out of
band. Nothing detected that, so a lawyer's calendar could quietly disagree with
the obligation date CaseOps holds.

Additive. Existing rows default to ``unchecked``, which is truthful: they have
not been checked.

Revision ID: 20260815_0004
Revises: 20260815_0003

DATA-GOVERNANCE-MAP: updated
The new columns extend the existing ``calendar_event_syncs``
``tenant_operational_record`` class and add no new class. ``drift_status`` is
registered as ``configuration_or_state_metadata``, ``drift_checked_at`` as
``temporal_or_version_metadata``, and ``drift_detail`` as ``domain_attribute``.
``drift_detail`` is deliberately content-free: it states that a projected copy
moved or vanished, never the record title nor the date it moved to, so the
column adds no privileged content to an operational row.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0004"
down_revision = "20260815_0003"
branch_labels = None
depends_on = None

TABLE = "calendar_event_syncs"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    # SQLite cannot ALTER constraints outside batch mode.
    with op.batch_alter_table(TABLE) as batch:
        batch.add_column(
            sa.Column(
                "drift_status",
                sa.String(length=16),
                nullable=False,
                server_default="unchecked",
            )
        )
        batch.add_column(
            sa.Column("drift_checked_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("drift_detail", sa.String(length=200), nullable=True))
        # `unknown` is a first-class outcome: an unreadable provider must not be
        # recorded as a match.
        batch.create_check_constraint(
            "ck_calendar_event_sync_drift_status",
            "drift_status IN ('unchecked', 'matches', 'moved', 'missing', 'unknown')",
        )

    op.create_index(
        "ix_calendar_event_syncs_company_drift", TABLE, ["company_id", "drift_status"]
    )


def downgrade() -> None:
    op.drop_index("ix_calendar_event_syncs_company_drift", table_name=TABLE)
    with op.batch_alter_table(TABLE) as batch:
        batch.drop_constraint("ck_calendar_event_sync_drift_status", type_="check")
        batch.drop_column("drift_detail")
        batch.drop_column("drift_checked_at")
        batch.drop_column("drift_status")
