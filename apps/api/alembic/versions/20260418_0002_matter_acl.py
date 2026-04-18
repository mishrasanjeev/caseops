"""matter access grants + ethical walls (§5.6)

Revision ID: 20260418_0002
Revises: 20260418_0001
Create Date: 2026-04-18 08:00:00

Matter-level access control on top of the existing tenant boundary.

- `matters.restricted_access` (bool, default false) — when false the
  matter is visible to every company member (the current behaviour).
  When true only explicit `matter_access_grants` rows open access.
- `matter_access_grants` — (matter_id, membership_id, access_level).
  A unique constraint prevents duplicate grants per (matter, user).
- `ethical_walls` — (matter_id, excluded_membership_id, reason). A
  wall blocks the named membership from ever seeing the matter, even
  if they would otherwise be granted. Owners of the matter bypass
  walls so they can't lock themselves out.

All three objects are introduced together so the enforcement helper
(`services/matter_access.can_access`) can compose the full rule set
in one query.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0002"
down_revision = "20260418_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "matters",
        sa.Column(
            "restricted_access",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )

    op.create_table(
        "matter_access_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("access_level", sa.String(length=24), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "granted_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "matter_id",
            "membership_id",
            name="uq_matter_access_grants_matter_membership",
        ),
    )

    op.create_table(
        "ethical_walls",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "excluded_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "matter_id",
            "excluded_membership_id",
            name="uq_ethical_walls_matter_excluded",
        ),
    )


def downgrade() -> None:
    op.drop_table("ethical_walls")
    op.drop_table("matter_access_grants")
    op.drop_column("matters", "restricted_access")
