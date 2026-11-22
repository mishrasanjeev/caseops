"""Verified, consented phone destinations for SMS and WhatsApp reminders.

Revision ID: 20261122_0003
Revises: 20261122_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. One new empty table with three nonunique
indexes on its own columns references the existing tenant membership key. No
existing rows are scanned or rewritten.
MIGRATION-ROLLBACK: restore-forward. Downgrade refuses before DDL because the
rows hold consent and opt-out evidence for personal phone numbers.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261122_0003"
down_revision = "20261122_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    op.create_table(
        "notification_phone_contacts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("membership_id", sa.String(36), nullable=False),
        sa.Column("phone_number", sa.String(20), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_code_hash", sa.String(64), nullable=True),
        sa.Column("verification_channel", sa.String(16), nullable=True),
        sa.Column("verification_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "verification_attempts", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("verification_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sms_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sms_opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whatsapp_consent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("whatsapp_opted_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_text_version", sa.String(16), nullable=True),
        sa.Column("opt_out_source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "company_id",
            "membership_id",
            name="uq_notification_phone_contact_membership",
        ),
        sa.ForeignKeyConstraint(
            ["company_id", "membership_id"],
            ["company_memberships.company_id", "company_memberships.id"],
            name="fk_notification_phone_contact_membership",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "verification_attempts >= 0",
            name="ck_notification_phone_contact_attempts",
        ),
    )
    op.create_index(
        "ix_notification_phone_contacts_company_id",
        "notification_phone_contacts",
        ["company_id"],
    )
    op.create_index(
        "ix_notification_phone_contacts_membership_id",
        "notification_phone_contacts",
        ["membership_id"],
    )
    op.create_index(
        "ix_notification_phone_contacts_phone",
        "notification_phone_contacts",
        ["phone_number"],
    )


def downgrade() -> None:
    raise RuntimeError(
        "Phone consent and opt-out evidence is retained; restore-forward only."
    )
