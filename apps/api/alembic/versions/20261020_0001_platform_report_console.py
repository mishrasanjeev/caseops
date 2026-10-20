"""Isolated report principals, session fences and hash-only delivery claims.

Revision ID: 20261020_0001
Revises: 20261019_0001
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged. New empty tables and a nullable users column;
the existing migration runner retains its bounded PostgreSQL lock budget.
MIGRATION-ROLLBACK: destructive for console-only security/audit records. Refuse
downgrade once those records exist; never erase retained security evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20261020_0001"
down_revision = "20261019_0001"
branch_labels = None
depends_on = None

_TABLES = (
    "platform_report_admins",
    "platform_console_sessions",
    "platform_console_tokens",
    "platform_console_deliveries",
    "platform_report_audit_events",
)


def _id():
    return sa.Column("id", sa.String(36), primary_key=True)


def _time(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _fk(name, target, nullable=False, unique=False):
    return sa.Column(name, sa.String(36), sa.ForeignKey(target), nullable=nullable, unique=unique)


def upgrade():
    op.add_column("users", _time("sessions_valid_after", nullable=True))
    op.create_table(
        "platform_report_admins",
        _id(),
        _fk("user_id", "users.id", unique=True),
        _fk("root_platform_admin_id", "platform_admin_memberships.id"),
        _fk("created_by_report_admin_id", "platform_report_admins.id", nullable=True),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("auth_epoch", sa.Integer, nullable=False),
        sa.Column("initializes_password", sa.Boolean, nullable=False),
        sa.Column("encrypted_totp_secret", sa.Text),
        sa.Column("mfa_status", sa.String(24), nullable=False),
        sa.Column("last_totp_counter", sa.BigInteger),
        sa.Column("recovery_code_hashes", sa.JSON, nullable=False),
        sa.Column("mfa_failures", sa.Integer, nullable=False),
        _time("mfa_locked_until", nullable=True),
        sa.Column("login_failures", sa.Integer, nullable=False),
        _time("login_locked_until", nullable=True),
        _time("created_at"),
        _time("updated_at"),
        sa.CheckConstraint("role IN ('manager', 'viewer')", name="ck_report_admin_role"),
        sa.CheckConstraint(
            "status IN ('pending', 'active', 'revoked')", name="ck_report_admin_status"
        ),
        sa.CheckConstraint(
            "(role = 'manager' AND created_by_report_admin_id IS NULL) OR "
            "(role = 'viewer' AND created_by_report_admin_id IS NOT NULL)",
            name="ck_report_admin_provenance",
        ),
    )
    op.create_index(
        "ix_platform_report_admins_root_platform_admin_id",
        "platform_report_admins",
        ["root_platform_admin_id"],
    )
    op.create_index(
        "ix_platform_report_admins_created_by_report_admin_id",
        "platform_report_admins",
        ["created_by_report_admin_id"],
    )
    op.create_index(
        "uq_report_admin_one_manager_per_root",
        "platform_report_admins",
        ["root_platform_admin_id"],
        unique=True,
        sqlite_where=sa.text("role = 'manager' AND status IN ('pending', 'active')"),
        postgresql_where=sa.text("role = 'manager' AND status IN ('pending', 'active')"),
    )
    op.create_table(
        "platform_console_sessions",
        _id(),
        _fk("report_admin_id", "platform_report_admins.id"),
        sa.Column("secret_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(64), nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        sa.Column("factor_hash", sa.String(64), nullable=False),
        sa.Column("auth_epoch", sa.Integer, nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        _time("issued_at"),
        _time("expires_at"),
        _time("revoked_at", nullable=True),
        sa.CheckConstraint(
            "purpose IN ('mfa_enrollment_required', 'mfa_challenge_required', 'authenticated')",
            name="ck_console_session_purpose",
        ),
    )
    op.create_index(
        "ix_console_sessions_admin_expiry",
        "platform_console_sessions",
        ["report_admin_id", "expires_at"],
    )
    op.create_table(
        "platform_console_tokens",
        _id(),
        _fk("report_admin_id", "platform_report_admins.id"),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(24), nullable=False),
        sa.Column("auth_epoch", sa.Integer, nullable=False),
        sa.Column("credential_hash", sa.String(64), nullable=False),
        _time("expires_at"),
        _time("consumed_at", nullable=True),
        _time("revoked_at", nullable=True),
        _time("created_at"),
        sa.CheckConstraint(
            "purpose IN ('invite', 'password_reset')", name="ck_console_token_purpose"
        ),
    )
    op.create_index(
        "ix_console_tokens_admin_purpose", "platform_console_tokens", ["report_admin_id", "purpose"]
    )
    op.create_table(
        "platform_console_deliveries",
        _id(),
        _fk("token_id", "platform_console_tokens.id", unique=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=False),
        _time("claim_expires_at"),
        sa.Column("provider_message_id", sa.String(255)),
        sa.Column("error_code", sa.String(64)),
        _time("created_at"),
        _time("completed_at", nullable=True),
        _time("started_at", nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'failed', 'outcome_unknown')",
            name="ck_console_delivery_status",
        ),
    )
    op.create_index(
        "ix_console_deliveries_status_expiry",
        "platform_console_deliveries",
        ["status", "claim_expires_at"],
    )
    op.create_table(
        "platform_report_audit_events",
        _id(),
        _fk("report_admin_id", "platform_report_admins.id", nullable=True),
        _fk("actor_user_id", "users.id", nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_id", sa.String(120)),
        sa.Column("result", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(500)),
        _time("created_at"),
    )
    for column in ("report_admin_id", "actor_user_id", "action"):
        op.create_index(
            f"ix_platform_report_audit_events_{column}", "platform_report_audit_events", [column]
        )


def downgrade():
    bind = op.get_bind()
    # Preserve security evidence and serialize the emptiness check with writers.
    if bind.dialect.name == "postgresql":
        for name in (*_TABLES, "users"):
            op.execute(sa.text(f'LOCK TABLE "{name}" IN ACCESS EXCLUSIVE MODE'))
    for name in _TABLES:
        table = sa.table(name, sa.column("id"))
        if bind.execute(sa.select(table.c.id).limit(1)).first() is not None:
            raise RuntimeError("Console security evidence prevents destructive downgrade.")
    users = sa.table("users", sa.column("sessions_valid_after"))
    if (
        bind.execute(
            sa.select(users.c.sessions_valid_after)
            .where(
                users.c.sessions_valid_after.is_not(None),
            )
            .limit(1)
        ).first()
        is not None
    ):
        raise RuntimeError("User session revocation evidence prevents destructive downgrade.")
    for name in reversed(_TABLES):
        op.drop_table(name)
    op.drop_column("users", "sessions_valid_after")
