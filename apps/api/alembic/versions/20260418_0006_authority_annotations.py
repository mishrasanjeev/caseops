"""per-tenant authority annotations

Revision ID: 20260418_0006
Revises: 20260418_0005
Create Date: 2026-04-18 15:00:00

Adds a per-tenant overlay on the shared ``authority_documents`` table.
A firm can attach internal notes and flags to a public judgment without
mutating the shared corpus. Per PRD §13.2 and the decision recorded
in §4.2, the authority corpus stays global; this table is the only
place where tenant-private context attaches to a judgment.

Design:

- ``company_id`` is the tenant boundary — every query MUST filter on it.
- ``authority_document_id`` is the shared authority we are annotating.
- ``(company_id, authority_document_id, kind, title)`` is unique so
  that a "bail-tracking" flag cannot accidentally be created twice on
  the same judgment by the same firm.
- ``kind`` classifies the annotation (note, flag, tag) so the UI can
  render appropriately.
- ``is_archived`` supports soft-hide without delete; the history stays
  queryable for audit.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "20260418_0006"
down_revision = "20260418_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authority_annotations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "authority_document_id",
            sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "company_id",
            "authority_document_id",
            "kind",
            "title",
            name="uq_authority_annotation_scope",
        ),
    )
    op.create_index(
        "ix_authority_annotations_tenant_doc",
        "authority_annotations",
        ["company_id", "authority_document_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_authority_annotations_tenant_doc", table_name="authority_annotations"
    )
    op.drop_table("authority_annotations")
