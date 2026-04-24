"""Phase C-3 (2026-04-24) — Outside-counsel portal scaffolding.

Closes the schema half of MOD-TS-016 (Outside Counsel Portal).

User-confirmed decisions:

- Cross-counsel visibility flag lives on `Matter` (per-matter, all-or-
  nothing). Per-grant flag was rejected as over-granular for v1.
- OC time entries stay separate from `MatterInvoiceLineItem` until an
  internal user explicitly attaches them — matches the
  "needs_review, never auto-approved" pattern PRD §J18 spelled out.

Three column adds + one boolean flag:

1. `matter_attachments.submitted_by_portal_user_id` (nullable FK).
   When NULL, the upload came from an internal CompanyMembership;
   when set, the upload came from a PortalUser via /api/portal/oc/*.
2. `matter_invoices.submitted_by_portal_user_id` (nullable FK). Same
   semantics. Submissions land in `status='needs_review'` (a new
   value on the existing `InvoiceStatus` StrEnum — no DB-level enum
   change needed because the column is `String(24)`).
3. `matter_time_entries.submitted_by_portal_user_id` (nullable FK).
4. `matters.oc_cross_visibility_enabled` (bool, default False). When
   False (the default), an OC portal user only sees their OWN
   submissions. When True, every OC on the matter sees every other
   OC's submissions.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260424_0002"
down_revision = "20260424_0001"
branch_labels = None
depends_on = None


def _add_portal_user_fk(table: str) -> None:
    """Wrap the add-column-with-FK in batch mode so the SQLite path
    (used by the local test harness) doesn't fail with "No support for
    ALTER of constraints in SQLite dialect." Postgres prod doesn't
    need batch but it's a no-op cost. Constraint names are explicit
    because batch mode requires named constraints."""
    fk_name = f"fk_{table}_submitted_by_portal_user_id"
    ix_name = f"ix_{table}_submitted_by_portal_user_id"
    with op.batch_alter_table(table) as batch:
        batch.add_column(
            sa.Column(
                "submitted_by_portal_user_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "portal_users.id",
                    ondelete="SET NULL",
                    name=fk_name,
                ),
                nullable=True,
            )
        )
        batch.create_index(ix_name, ["submitted_by_portal_user_id"])


def _drop_portal_user_fk(table: str) -> None:
    ix_name = f"ix_{table}_submitted_by_portal_user_id"
    with op.batch_alter_table(table) as batch:
        batch.drop_index(ix_name)
        batch.drop_column("submitted_by_portal_user_id")


def upgrade() -> None:
    _add_portal_user_fk("matter_attachments")
    _add_portal_user_fk("matter_invoices")
    _add_portal_user_fk("matter_time_entries")
    with op.batch_alter_table("matters") as batch:
        batch.add_column(
            sa.Column(
                "oc_cross_visibility_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("matters") as batch:
        batch.drop_column("oc_cross_visibility_enabled")
    _drop_portal_user_fk("matter_time_entries")
    _drop_portal_user_fk("matter_invoices")
    _drop_portal_user_fk("matter_attachments")
