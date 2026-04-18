"""teams + team_memberships + matters.team_id + companies.team_scoping_enabled

Revision ID: 20260418_0011
Revises: 20260418_0010
Create Date: 2026-04-18 23:20:00

Sprint 8c BG-026. Four changes in one migration so a tenant can't
land in a half-state:

- ``teams`` (id, company_id, name, slug, description, kind, is_active)
  with ``(company_id, slug)`` unique.
- ``team_memberships`` (id, team_id, membership_id, is_lead) with
  ``(team_id, membership_id)`` unique.
- ``matters.team_id`` nullable FK to ``teams.id`` for optional primary
  team ownership. Indexed for visibility-filter joins.
- ``companies.team_scoping_enabled`` bool default false. When true,
  non-owners only see matters whose team they're a member of (or
  team-less matters). Default keeps behaviour identical to pre-
  Sprint 8c for existing tenants.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0011"
down_revision = "20260418_0010"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "teams",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=24), nullable=False, server_default="team"),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("company_id", "slug", name="uq_team_company_slug"),
    )
    op.create_index("ix_teams_company_id", "teams", ["company_id"])

    op.create_table(
        "team_memberships",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "team_id",
            sa.String(length=36),
            sa.ForeignKey("teams.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "is_lead", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("team_id", "membership_id", name="uq_team_membership"),
    )
    op.create_index(
        "ix_team_memberships_team_id", "team_memberships", ["team_id"]
    )
    op.create_index(
        "ix_team_memberships_membership_id",
        "team_memberships",
        ["membership_id"],
    )

    # `add_column` with a ForeignKey needs batch_alter_table on SQLite,
    # which rebuilds the table under the hood. PostgreSQL supports
    # ADD COLUMN ... REFERENCES directly; batch is a no-op on PG.
    with op.batch_alter_table("matters") as batch_op:
        batch_op.add_column(sa.Column("team_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_matters_team_id_teams",
            "teams",
            ["team_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_matters_team_id", ["team_id"])

    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(
            sa.Column(
                "team_scoping_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )

    # Backfill existing rows with the server_default so SQLite's batch
    # rebuild doesn't leave NULL values behind.
    op.execute(
        "UPDATE companies SET team_scoping_enabled = 0 "
        "WHERE team_scoping_enabled IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_column("team_scoping_enabled")
    with op.batch_alter_table("matters") as batch_op:
        batch_op.drop_index("ix_matters_team_id")
        batch_op.drop_column("team_id")
    op.drop_index(
        "ix_team_memberships_membership_id", table_name="team_memberships"
    )
    op.drop_index("ix_team_memberships_team_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_index("ix_teams_company_id", table_name="teams")
    op.drop_table("teams")
