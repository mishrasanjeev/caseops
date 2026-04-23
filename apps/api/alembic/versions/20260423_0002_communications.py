"""Phase B / J12 / M11 — communications log foundation.

Closes US-035 (client communication history) + FT-046 (communication
log create + read). Slice 1 supports MANUAL logging only — recording
that "I called the client at 3pm" or "client emailed me back". The
follow-up slice will wire SendGrid send + template picker + delivery
webhook on top of this same row.

Why one ``communications`` table and not separate per-channel tables:

- The lawyer's mental model is "what's the history with this client /
  on this matter" — channel is a property, not the primary axis.
- A future "merge with thread" UI (group an outbound email + the
  client's reply + the lawyer's voice-call note) is a query against
  one table, not a UNION of three.
- Channel-specific metadata that doesn't fit the common shape lands
  in a JSON ``metadata`` column rather than schema sprawl.

Fields:

- ``direction`` — ``outbound`` (we sent) vs ``inbound`` (they sent).
- ``channel`` — ``email`` / ``sms`` / ``phone`` / ``meeting`` / ``note``.
- ``status`` — covers both manual ("logged") and the future SendGrid
  pipeline ("queued" → "sent" → "delivered" / "opened" / "bounced").
- ``matter_id`` and ``client_id`` are both nullable individually but
  at least one MUST be set (enforced at the service layer; SQLite
  used by the test suite does not consistently support CHECK
  constraints across versions).
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260423_0002"
down_revision = "20260423_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "communications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id", sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "matter_id", sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=True, index=True,
        ),
        sa.Column(
            "client_id", sa.String(length=36),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True, index=True,
        ),
        sa.Column("direction", sa.String(length=12), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("subject", sa.String(length=400), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("recipient_name", sa.String(length=255), nullable=True),
        sa.Column("recipient_email", sa.String(length=320), nullable=True),
        sa.Column("recipient_phone", sa.String(length=64), nullable=True),
        sa.Column(
            "status", sa.String(length=24), nullable=False,
            server_default="logged",
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_message_id", sa.String(length=120), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
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
    )
    # Composite index for the most common access pattern: "show me
    # the communications for matter X newest first."
    op.create_index(
        "ix_communications_matter_id_occurred_at",
        "communications",
        ["matter_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_communications_matter_id_occurred_at", "communications")
    op.drop_table("communications")
