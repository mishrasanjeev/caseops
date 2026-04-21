"""Sprint S1 + S2 — clients and matter-client assignments (MOD-TS-009).

New ``clients`` table + ``matter_client_assignments`` link table.

- ``clients`` is tenant-scoped by ``company_id`` with a soft
  ``(company_id, name, client_type)`` uniqueness constraint so the
  same firm can represent multiple types-of-client with the same
  name (e.g., an individual vs. that individual's corporation).
- ``matter_client_assignments`` is N-N between ``matters`` and
  ``clients`` with a ``role`` free-text field
  (petitioner / respondent / opposing / witness etc.) and an
  ``is_primary`` flag so the matter cockpit can pick a headline
  client even when several are linked.

Legacy ``Matter.client_name`` stays untouched for back-compat.
Callers that read the client should prefer the linked assignments and
fall back to ``client_name`` only when no link is set.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260421_0003"
down_revision = "20260421_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "client_type",
            sa.String(length=24),
            nullable=False,
            server_default="individual",
        ),
        sa.Column("primary_contact_name", sa.String(length=255), nullable=True),
        sa.Column("primary_contact_email", sa.String(length=320), nullable=True),
        sa.Column("primary_contact_phone", sa.String(length=40), nullable=True),
        sa.Column("city", sa.String(length=255), nullable=True),
        sa.Column("state", sa.String(length=120), nullable=True),
        sa.Column(
            "country", sa.String(length=120), nullable=True, server_default="India",
        ),
        sa.Column("pan", sa.String(length=20), nullable=True),
        sa.Column("gstin", sa.String(length=20), nullable=True),
        sa.Column("internal_notes", sa.Text(), nullable=True),
        sa.Column(
            "kyc_status",
            sa.String(length=24),
            nullable=False,
            server_default="not_started",
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "company_id", "name", "client_type",
            name="uq_clients_tenant_name_type",
        ),
    )
    op.create_index("ix_clients_company_id", "clients", ["company_id"])

    op.create_table(
        "matter_client_assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.String(length=36),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=60), nullable=True),
        sa.Column(
            "is_primary",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "matter_id", "client_id",
            name="uq_matter_client_assignment",
        ),
    )
    op.create_index(
        "ix_matter_client_assignments_matter_id",
        "matter_client_assignments",
        ["matter_id"],
    )
    op.create_index(
        "ix_matter_client_assignments_client_id",
        "matter_client_assignments",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_client_assignments_client_id",
        table_name="matter_client_assignments",
    )
    op.drop_index(
        "ix_matter_client_assignments_matter_id",
        table_name="matter_client_assignments",
    )
    op.drop_table("matter_client_assignments")
    op.drop_index("ix_clients_company_id", table_name="clients")
    op.drop_table("clients")
