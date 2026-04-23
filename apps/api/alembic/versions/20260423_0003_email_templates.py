"""Phase B M11 slice 2 — AutoMail email templates.

Closes US-036 (AutoMail templates) + FT-047 (email send action picks
template, recipients, attachment) + FT-048 (delivery webhook updates
communication status). MOD-TS-010 reconciliation.

The actual send / webhook plumbing lives on the existing
``communications`` table — this migration only adds the templates
catalogue. A "Compose & send" action picks a template, fills the
declared variables, renders subject + body, calls SendGrid, and
writes the result onto a new ``communications`` row with
``status=queued`` (then transitions through ``sent`` →
``delivered`` / ``opened`` / ``bounced`` via the webhook).

Why one templates table per company (not a single shared catalogue):

- Templates carry firm voice / branding. A shared catalogue would
  make every workspace look identical at the email level, which
  defeats the point of a customer-facing template.
- The variable list is per-template, not per-tenant; the schema
  carries it as a JSON blob so admins can declare new variables
  without a migration per template kind.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260423_0003"
down_revision = "20260423_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("description", sa.String(length=400), nullable=True),
        sa.Column("subject_template", sa.String(length=400), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        # Variables list: [{"name": "client_name", "label": "Client name",
        # "required": true}]. Stored as JSON so a template can declare
        # variables without a per-template migration.
        sa.Column("variables_json", sa.JSON(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(),
            nullable=False, server_default=sa.true(),
        ),
        sa.Column(
            "created_by_membership_id", sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        # Name uniqueness per tenant — same template name in two
        # workspaces is fine and expected.
        sa.UniqueConstraint(
            "company_id", "name",
            name="uq_email_templates_company_name",
        ),
    )


def downgrade() -> None:
    op.drop_table("email_templates")
