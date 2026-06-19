"""ADP-17 judgment monitoring in-app alert center.

Revision ID: 20260524_0003
Revises: 20260524_0002
Create Date: 2026-05-24
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260524_0003"
down_revision = "20260524_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
__all__ = ("revision", "down_revision", "branch_labels", "depends_on", "upgrade", "downgrade")


def upgrade() -> None:
    op.create_table(
        "judgment_alert_rules",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("query_terms_json", sa.JSON(), nullable=True),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("forum_level", sa.String(length=40), nullable=True),
        sa.Column("judge_name", sa.String(length=255), nullable=True),
        sa.Column("practice_area", sa.String(length=120), nullable=True),
        sa.Column("statute_terms_json", sa.JSON(), nullable=True),
        sa.Column("document_types_json", sa.JSON(), nullable=True),
        sa.Column("since_date", sa.Date(), nullable=True),
        sa.Column("until_date", sa.Date(), nullable=True),
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
    )
    op.create_index(
        "ix_judgment_alert_rules_company_id",
        "judgment_alert_rules",
        ["company_id"],
    )
    op.create_index(
        "ix_judgment_alert_rules_created_by_membership_id",
        "judgment_alert_rules",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_judgment_alert_rules_court_name",
        "judgment_alert_rules",
        ["court_name"],
    )
    op.create_index(
        "ix_judgment_alert_rules_forum_level",
        "judgment_alert_rules",
        ["forum_level"],
    )
    op.create_index(
        "ix_judgment_alert_rules_is_archived",
        "judgment_alert_rules",
        ["is_archived"],
    )

    op.create_table(
        "judgment_alerts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "rule_id",
            sa.String(length=36),
            sa.ForeignKey("judgment_alert_rules.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "authority_document_id",
            sa.String(length=36),
            sa.ForeignKey("authority_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("match_reason", sa.String(length=500), nullable=False),
        sa.Column("snippet", sa.String(length=280), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.UniqueConstraint(
            "rule_id",
            "authority_document_id",
            name="uq_judgment_alert_rule_authority",
        ),
    )
    op.create_index(
        "ix_judgment_alerts_company_id",
        "judgment_alerts",
        ["company_id"],
    )
    op.create_index(
        "ix_judgment_alerts_rule_id",
        "judgment_alerts",
        ["rule_id"],
    )
    op.create_index(
        "ix_judgment_alerts_authority_document_id",
        "judgment_alerts",
        ["authority_document_id"],
    )
    op.create_index(
        "ix_judgment_alerts_is_read",
        "judgment_alerts",
        ["is_read"],
    )


def downgrade() -> None:
    op.drop_index("ix_judgment_alerts_is_read", table_name="judgment_alerts")
    op.drop_index("ix_judgment_alerts_authority_document_id", table_name="judgment_alerts")
    op.drop_index("ix_judgment_alerts_rule_id", table_name="judgment_alerts")
    op.drop_index("ix_judgment_alerts_company_id", table_name="judgment_alerts")
    op.drop_table("judgment_alerts")

    op.drop_index("ix_judgment_alert_rules_is_archived", table_name="judgment_alert_rules")
    op.drop_index("ix_judgment_alert_rules_forum_level", table_name="judgment_alert_rules")
    op.drop_index("ix_judgment_alert_rules_court_name", table_name="judgment_alert_rules")
    op.drop_index(
        "ix_judgment_alert_rules_created_by_membership_id",
        table_name="judgment_alert_rules",
    )
    op.drop_index("ix_judgment_alert_rules_company_id", table_name="judgment_alert_rules")
    op.drop_table("judgment_alert_rules")
