"""J20/M22 hashed native handoff, session families and rotating replay ledger.

DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: additive empty tables only; no existing-row rewrite.
MIGRATION-ROLLBACK: revoke native grants before downgrade; credential history
is security evidence and is retained by a roll-forward/restore-only boundary.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261024_0001"
down_revision = "20261022_0001"
branch_labels = None
depends_on = None


def _identity_fields():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "membership_id",
            sa.String(36),
            sa.ForeignKey("company_memberships.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(10), nullable=False),
        sa.Column("source_issued_at", sa.Float(), nullable=False),
        sa.Column("mfa_verified_at", sa.DateTime(timezone=True)),
        sa.Column("mfa_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("platform IN ('android', 'ios')"),
    ]


def upgrade():
    op.create_table(
        "native_authorization_codes",
        *_identity_fields(),
        sa.Column("code_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("code_challenge", sa.String(43), nullable=False),
        sa.Column("redirect_uri", sa.String(512), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "native_device_sessions",
        *_identity_fields(),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("revocation_reason", sa.String(30)),
    )
    for table in ("native_authorization_codes", "native_device_sessions"):
        op.create_index(f"ix_{table}_membership_id", table, ["membership_id"])
        op.create_index(f"ix_{table}_expires_at", table, ["expires_at"])
    op.create_table(
        "native_refresh_tokens",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("native_device_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_native_refresh_tokens_session_id", "native_refresh_tokens", ["session_id"])


def downgrade():
    raise RuntimeError(
        "Native replay history is retained security evidence; roll-forward or restore."
    )
