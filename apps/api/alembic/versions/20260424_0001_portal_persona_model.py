"""Phase C-1 (2026-04-24) — Portal persona model + magic-link auth.

Closes MOD-TS-014 (Portal Persona Model + Shared Scaffold).

User-confirmed decisions (D1-D4 in
``docs/PHASE_C_KICKOFF_2026-04-24.md``):

- D1: ``portal_users`` is a NEW table, separate from
  ``company_memberships``. No role inheritance, no shared auth.
- D2: Magic-link auth. Tokens are hashed at rest, single-use,
  bound to the originating email, expire in 30 minutes.
- D3: Single domain caseops.ai, /portal/*. Cookies are HttpOnly,
  SameSite=Lax, distinct cookie name from the internal session.
- D4: Free V1 portal seats; per-workspace caps enforced in service
  code, not the schema.

Three tables land:

1. ``portal_users`` — one row per (company, email) pair.
2. ``portal_magic_links`` — short-lived single-use sign-in tokens
   storing only the SHA-256 hash of the token, never the plaintext.
3. ``matter_portal_grants`` — explicit per-matter scope. Without a
   live grant, a portal user sees nothing on a matter even if it
   belongs to their company.
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260424_0001"
down_revision = "20260423_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "portal_users",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "sessions_valid_after",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "invited_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_signed_in_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "company_id", "email", name="uq_portal_user_company_email"
        ),
    )

    op.create_table(
        "portal_magic_links",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "portal_user_id",
            sa.String(length=36),
            sa.ForeignKey("portal_users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # 64-char hex of SHA-256(token). The plaintext token is never
        # written to the DB so a hot-DB-dump cannot replay sessions.
        sa.Column(
            "token_hash",
            sa.String(length=64),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("requested_ip", sa.String(length=64), nullable=True),
        sa.Column("requested_user_agent", sa.String(length=255), nullable=True),
    )

    op.create_table(
        "matter_portal_grants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "portal_user_id",
            sa.String(length=36),
            sa.ForeignKey("portal_users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "matter_id",
            sa.String(length=36),
            sa.ForeignKey("matters.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # Mirrors ``portal_users.role`` so a single matter row can be
        # filtered by role without joining back. Enforced by the
        # service layer to match the parent PortalUser's role.
        sa.Column("role", sa.String(length=32), nullable=False),
        # JSON of granted capabilities, e.g.
        # {"can_upload": true, "can_invoice": false, "can_reply": true}.
        # Defaults are role-driven in the service.
        sa.Column(
            "scope_json",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "granted_by_membership_id",
            sa.String(length=36),
            sa.ForeignKey("company_memberships.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "portal_user_id",
            "matter_id",
            name="uq_matter_portal_grant_user_matter",
        ),
    )


def downgrade() -> None:
    op.drop_table("matter_portal_grants")
    op.drop_table("portal_magic_links")
    op.drop_table("portal_users")
