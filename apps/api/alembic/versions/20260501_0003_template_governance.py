"""tenant_ai_policies.disabled_template_types_json - PG-005 Sprint 11.

Adds an admin-controlled list of drafting templates the tenant has
hidden from its workspace. Default empty list = every template
visible. Admins flip via PATCH /api/admin/tenant-ai-policy.

Revision ID: 20260501_0003
Revises: 20260501_0002
Create Date: 2026-05-01
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260501_0003"
down_revision = "20260501_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.add_column(
            sa.Column(
                "disabled_template_types_json",
                sa.Text(),
                nullable=False,
                server_default="[]",
            ),
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_ai_policies") as batch:
        batch.drop_column("disabled_template_types_json")
