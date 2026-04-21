"""Sprint Q10 — matter_attachment_annotations table.

Per-matter overlay on uploaded attachments. Renders in the PDF
viewer at /app/matters/{id}/documents/{attachment_id}/view. Scoped
by company_id + matter_id so every query is tenant-safe.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260421_0001"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "matter_attachment_annotations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "matter_attachment_id",
            sa.String(length=36),
            sa.ForeignKey("matter_attachments.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("page", sa.Integer(), nullable=False),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("quoted_text", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=24), nullable=True),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
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
    )
    op.create_index(
        "ix_matter_attachment_annotations_company_id",
        "matter_attachment_annotations",
        ["company_id"],
    )
    op.create_index(
        "ix_matter_attachment_annotations_matter_id",
        "matter_attachment_annotations",
        ["matter_id"],
    )
    op.create_index(
        "ix_matter_attachment_annotations_matter_attachment_id",
        "matter_attachment_annotations",
        ["matter_attachment_id"],
    )
    op.create_index(
        "ix_matter_attachment_annotations_created_by_membership_id",
        "matter_attachment_annotations",
        ["created_by_membership_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_matter_attachment_annotations_created_by_membership_id",
        table_name="matter_attachment_annotations",
    )
    op.drop_index(
        "ix_matter_attachment_annotations_matter_attachment_id",
        table_name="matter_attachment_annotations",
    )
    op.drop_index(
        "ix_matter_attachment_annotations_matter_id",
        table_name="matter_attachment_annotations",
    )
    op.drop_index(
        "ix_matter_attachment_annotations_company_id",
        table_name="matter_attachment_annotations",
    )
    op.drop_table("matter_attachment_annotations")
