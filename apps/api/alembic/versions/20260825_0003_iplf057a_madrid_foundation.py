"""Add the canonical Madrid registration and designation aggregate.

Revision ID: 20260825_0003
Revises: 20260825_0002
Create Date: 2026-08-25

IPLF-057A adds one type-specific legal aggregate. Existing dockets own access
and lifecycle, ip_relationships owns basic-mark/designation links, and existing
events, deadlines, costs, documents, and provider operations remain canonical.

MIGRATION-LOCK-RISK: acknowledged: one additive empty table plus indexes and
constraints; PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: restore-forward after any Madrid row exists. An empty,
pre-activation schema may downgrade.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260825_0003"
down_revision = "20260825_0002"
branch_labels = None
depends_on = None


def _set_lock_timeout() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")


def upgrade() -> None:
    _set_lock_timeout()
    op.create_table(
        "trademark_international_registrations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("record_kind", sa.String(length=40), nullable=False),
        sa.Column("direction", sa.String(length=16), nullable=False),
        sa.Column("parent_registration_id", sa.String(length=36), nullable=True),
        sa.Column("basic_application_id", sa.String(length=36), nullable=True),
        sa.Column("international_application_number", sa.String(length=120), nullable=True),
        sa.Column("ir_number", sa.String(length=120), nullable=True),
        sa.Column("wipo_reference", sa.String(length=255), nullable=False),
        sa.Column("holder_name", sa.String(length=500), nullable=False),
        sa.Column("mark_name", sa.String(length=500), nullable=False),
        sa.Column("office_of_origin", sa.String(length=120), nullable=True),
        sa.Column("designated_member_code", sa.String(length=20), nullable=True),
        sa.Column("designated_office", sa.String(length=120), nullable=True),
        sa.Column("jurisdiction", sa.String(length=40), nullable=True),
        sa.Column("designation_kind", sa.String(length=20), nullable=True),
        sa.Column("classes_json", sa.JSON(), nullable=False),
        sa.Column("goods_services_json", sa.JSON(), nullable=False),
        sa.Column("priority_claims_json", sa.JSON(), nullable=False),
        sa.Column("form_kind", sa.String(length=40), nullable=True),
        sa.Column("wipo_status", sa.String(length=120), nullable=True),
        sa.Column("national_status", sa.String(length=120), nullable=True),
        sa.Column("local_agent_name", sa.String(length=500), nullable=True),
        sa.Column("source_url", sa.String(length=800), nullable=False),
        sa.Column("source_reference", sa.String(length=500), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("application_date", sa.Date(), nullable=True),
        sa.Column("international_registration_date", sa.Date(), nullable=True),
        sa.Column("designation_effective_date", sa.Date(), nullable=True),
        sa.Column("notification_date", sa.Date(), nullable=True),
        sa.Column("publication_date", sa.Date(), nullable=True),
        sa.Column("statement_date", sa.Date(), nullable=True),
        sa.Column("dependency_end_date", sa.Date(), nullable=True),
        sa.Column("renewal_due_date", sa.Date(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("updated_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "record_kind IN ('international_registration', 'international_designation')",
            name="ck_tm_international_record_kind",
        ),
        sa.CheckConstraint(
            "direction IN ('outbound', 'inbound')",
            name="ck_tm_international_direction",
        ),
        sa.CheckConstraint(
            "designation_kind IS NULL OR designation_kind IN ('original', 'subsequent')",
            name="ck_tm_international_designation_kind",
        ),
        sa.CheckConstraint(
            "(record_kind = 'international_registration' AND parent_registration_id IS NULL "
            "AND designated_member_code IS NULL AND jurisdiction IS NULL "
            "AND designation_kind IS NULL AND designation_effective_date IS NULL "
            "AND national_status IS NULL) OR "
            "(record_kind = 'international_designation' AND parent_registration_id IS NOT NULL "
            "AND designated_member_code IS NOT NULL AND jurisdiction IS NOT NULL "
            "AND designation_kind IS NOT NULL AND designation_effective_date IS NOT NULL)",
            name="ck_tm_international_kind_fields",
        ),
        sa.CheckConstraint(
            "record_kind = 'international_registration' OR basic_application_id IS NULL",
            name="ck_tm_international_basic_application_owner",
        ),
        sa.CheckConstraint(
            "parent_registration_id IS NULL OR parent_registration_id <> id",
            name="ck_tm_international_parent_not_self",
        ),
        sa.CheckConstraint("version > 0", name="ck_tm_international_version_positive"),
        sa.ForeignKeyConstraint(
            ["basic_application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_tm_international_basic_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_tm_international_creator_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_tm_international_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_registration_id", "company_id"],
            [
                "trademark_international_registrations.id",
                "trademark_international_registrations.company_id",
            ],
            name="fk_tm_international_parent_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_tm_international_updater_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "company_id", "docket_id", name="uq_tm_international_company_docket"
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_tm_international_id_company"),
    )
    op.create_index(
        "ix_tm_international_company_parent",
        "trademark_international_registrations",
        ["company_id", "parent_registration_id"],
    )
    op.create_index(
        "ix_tm_international_company_status",
        "trademark_international_registrations",
        ["company_id", "record_kind", "wipo_status", "national_status"],
    )
    op.create_index(
        "ix_trademark_international_registrations_basic_application_id",
        "trademark_international_registrations",
        ["basic_application_id"],
    )
    op.create_index(
        "ix_trademark_international_registrations_created_by_membership_id",
        "trademark_international_registrations",
        ["created_by_membership_id"],
    )
    op.create_index(
        "ix_trademark_international_registrations_docket_id",
        "trademark_international_registrations",
        ["docket_id"],
    )
    op.create_index(
        "ix_trademark_international_registrations_parent_registration_id",
        "trademark_international_registrations",
        ["parent_registration_id"],
    )
    op.create_index(
        "ix_trademark_international_registrations_updated_by_membership_id",
        "trademark_international_registrations",
        ["updated_by_membership_id"],
    )
    op.create_index(
        "uq_tm_international_company_ir_number",
        "trademark_international_registrations",
        ["company_id", "ir_number"],
        unique=True,
        postgresql_where=sa.text(
            "record_kind = 'international_registration' AND ir_number IS NOT NULL"
        ),
        sqlite_where=sa.text(
            "record_kind = 'international_registration' AND ir_number IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_tm_international_designation_member",
        "trademark_international_registrations",
        [
            "company_id",
            "parent_registration_id",
            "designated_member_code",
            "designation_effective_date",
        ],
        unique=True,
        postgresql_where=sa.text("record_kind = 'international_designation'"),
        sqlite_where=sa.text("record_kind = 'international_designation'"),
    )


def downgrade() -> None:
    _set_lock_timeout()
    bind = op.get_bind()
    if bind.execute(
        sa.text("SELECT 1 FROM trademark_international_registrations LIMIT 1")
    ).first():
        raise RuntimeError(
            "Restore-forward required: Madrid records exist and cannot be safely discarded."
        )
    op.drop_table("trademark_international_registrations")
