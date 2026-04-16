"""Initial CaseOps schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260416_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("company_type", sa.String(length=40), nullable=False),
        sa.Column("tenant_key", sa.String(length=80), nullable=False),
        sa.Column("primary_contact_email", sa.String(length=320), nullable=True),
        sa.Column("billing_contact_name", sa.String(length=255), nullable=True),
        sa.Column("billing_contact_email", sa.String(length=320), nullable=True),
        sa.Column("headquarters", sa.String(length=255), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("practice_summary", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
        sa.UniqueConstraint("tenant_key"),
    )
    op.create_index(op.f("ix_companies_slug"), "companies", ["slug"], unique=True)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "company_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "user_id", name="uq_company_membership"),
    )
    op.create_index(
        op.f("ix_company_memberships_company_id"),
        "company_memberships",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_company_memberships_user_id"),
        "company_memberships",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "matters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("matter_code", sa.String(length=80), nullable=False),
        sa.Column("client_name", sa.String(length=255), nullable=True),
        sa.Column("opposing_party", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("practice_area", sa.String(length=120), nullable=False),
        sa.Column("forum_level", sa.String(length=40), nullable=False),
        sa.Column("court_name", sa.String(length=255), nullable=True),
        sa.Column("judge_name", sa.String(length=255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("next_hearing_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "matter_code", name="uq_company_matter_code"),
    )
    op.create_index(op.f("ix_matters_company_id"), "matters", ["company_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_matters_company_id"), table_name="matters")
    op.drop_table("matters")
    op.drop_index(op.f("ix_company_memberships_user_id"), table_name="company_memberships")
    op.drop_index(op.f("ix_company_memberships_company_id"), table_name="company_memberships")
    op.drop_table("company_memberships")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_index(op.f("ix_companies_slug"), table_name="companies")
    op.drop_table("companies")
