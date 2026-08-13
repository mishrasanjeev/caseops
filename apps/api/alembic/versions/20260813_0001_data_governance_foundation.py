"""Add fail-closed IPLF-028A records-governance foundations.

Revision ID: 20260813_0001
Revises: 20260812_0002
Create Date: 2026-08-13

The six tables are additive and intentionally unseeded.  They can record
versioned retention terms, legal-hold scope, and opaque dry-run manifests, but
the database itself excludes execute mode and non-dry-run authorization.  A
rollback may remove an empty rehearsal schema only; it must never erase
retention, hold, or operation evidence.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision = "20260813_0001"
down_revision = "20260812_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_TABLES = (
    "data_retention_policies",
    "data_retention_versions",
    "legal_holds",
    "legal_hold_items",
    "tenant_data_operations",
    "tenant_data_operation_items",
)

_RETENTION_VERSION_IMMUTABLE_COLUMNS = (
    "id",
    "company_id",
    "policy_id",
    "version",
    "data_class_selector_json",
    "purpose",
    "legal_policy_basis",
    "sensitivity",
    "retention_days",
    "indefinite_retention_approval_ref",
    "disposition",
    "hold_behavior",
    "source_license_limits",
    "region",
    "subprocessor",
    "policy_hash",
    "proposed_by_membership_id",
    "proposed_by_membership_company_id",
    "proposer_label_snapshot",
    "created_at",
)

_OPERATION_IMMUTABLE_COLUMNS = (
    "id",
    "company_id",
    "operation_type",
    "execution_mode",
    "approval_status",
    "request_scope_json",
    "request_scope_hash",
    "request_evidence_ref",
    "retention_policy_version_id",
    "manifest_json",
    "manifest_hash",
    "requested_by_membership_id",
    "requested_by_membership_company_id",
    "requester_label_snapshot",
    "dry_run_completed_at",
    "created_at",
)


def _postgres_immutable_predicate(
    columns: tuple[str, ...], *, json_columns: frozenset[str] = frozenset()
) -> str:
    """Build a null-safe immutable-column predicate for PostgreSQL triggers.

    PostgreSQL's ``json`` type deliberately has no equality operator.  The
    immutable evidence columns use ``json`` for cross-dialect support, so
    compare those values through ``jsonb`` inside the trigger rather than
    allowing an update to fail with an undefined-operator error.
    """
    return " OR ".join(
        (
            f'OLD."{column}"::jsonb IS DISTINCT FROM NEW."{column}"::jsonb'
            if column in json_columns
            else f'OLD."{column}" IS DISTINCT FROM NEW."{column}"'
        )
        for column in columns
    )


def _lock_tables_for_populated_downgrade_check(bind: sa.Connection) -> None:
    if bind.dialect.name != "postgresql":
        return
    bind.execute(sa.text("SET LOCAL lock_timeout = '30s'"))
    for table_name in _TABLES:
        bind.execute(sa.text(f'LOCK TABLE "{table_name}" IN ACCESS EXCLUSIVE MODE'))


def _assert_downgrade_is_evidence_free(bind: sa.Connection) -> None:
    _lock_tables_for_populated_downgrade_check(bind)
    populated: dict[str, int] = {}
    for table_name in _TABLES:
        count = int(bind.scalar(sa.text(f'SELECT count(*) FROM "{table_name}"')) or 0)
        if count:
            populated[table_name] = count
    if populated:
        raise RuntimeError(
            "Records-governance evidence exists; retain the additive schema and "
            "roll application code forward instead of deleting facts: "
            f"{populated}"
        )


def _create_retention_version_immutability_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        predicate = _postgres_immutable_predicate(
            _RETENTION_VERSION_IMMUTABLE_COLUMNS,
            json_columns=frozenset({"data_class_selector_json"}),
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION caseops_reject_retention_version_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION
                            'Retention policy versions are retained; retire instead of delete';
                    END IF;
                    IF OLD.status <> 'candidate' AND ({predicate}) THEN
                        RAISE EXCEPTION 'Published retention policy terms are immutable';
                    END IF;
                    IF NOT (
                        (OLD.status = 'candidate' AND
                         NEW.status IN ('candidate', 'approved', 'disabled')) OR
                        (OLD.status = 'approved' AND
                         NEW.status IN ('approved', 'active', 'retired', 'disabled')) OR
                        (OLD.status = 'active' AND
                         NEW.status IN ('active', 'retired', 'disabled')) OR
                        (OLD.status = 'retired' AND NEW.status = 'retired') OR
                        (OLD.status = 'disabled' AND NEW.status = 'disabled')
                    ) THEN
                        RAISE EXCEPTION 'Retention policy version state cannot move backwards';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_data_retention_versions_immutable
                BEFORE UPDATE OR DELETE ON data_retention_versions
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_retention_version_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE FUNCTION caseops_reject_data_retention_policy_delete()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION
                        'Retention policy identity is retained; retire instead of delete';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_data_retention_policies_no_delete
                BEFORE DELETE ON data_retention_policies
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_data_retention_policy_delete()
                """
            )
        )
        return
    if bind.dialect.name == "sqlite":
        predicate = " OR ".join(
            f'OLD."{column}" IS NOT NEW."{column}"'
            for column in _RETENTION_VERSION_IMMUTABLE_COLUMNS
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_data_retention_versions_immutable
                BEFORE UPDATE ON data_retention_versions
                FOR EACH ROW WHEN
                    (OLD.status <> 'candidate' AND ({predicate})) OR
                    NOT (
                        (OLD.status = 'candidate' AND
                         NEW.status IN ('candidate', 'approved', 'disabled')) OR
                        (OLD.status = 'approved' AND
                         NEW.status IN ('approved', 'active', 'retired', 'disabled')) OR
                        (OLD.status = 'active' AND
                         NEW.status IN ('active', 'retired', 'disabled')) OR
                        (OLD.status = 'retired' AND NEW.status = 'retired') OR
                        (OLD.status = 'disabled' AND NEW.status = 'disabled')
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'Retention policy version mutation rejected');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_data_retention_versions_no_delete
                BEFORE DELETE ON data_retention_versions
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Retention policy versions are retained');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_data_retention_policies_no_delete
                BEFORE DELETE ON data_retention_policies
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Retention policy identity is retained');
                END
                """
            )
        )


def _create_legal_hold_immutability_guard(bind: sa.Connection) -> None:
    immutable_columns = (
        "id",
        "company_id",
        "key",
        "title",
        "authority_reference",
        "reason_redacted",
        "created_by_membership_id",
        "created_by_membership_company_id",
        "creator_label_snapshot",
        "created_at",
    )
    if bind.dialect.name == "postgresql":
        predicate = " OR ".join(
            f'OLD."{column}" IS DISTINCT FROM NEW."{column}"'
            for column in immutable_columns
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION caseops_reject_legal_hold_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION 'Legal holds are retained; release instead of delete';
                    END IF;
                    IF {predicate} THEN
                        RAISE EXCEPTION 'Legal hold identity and authority are immutable';
                    END IF;
                    IF NOT (
                        (OLD.status = 'draft' AND
                         NEW.status IN ('draft', 'active', 'cancelled')) OR
                        (OLD.status = 'active' AND
                         NEW.status IN ('active', 'released')) OR
                        (OLD.status = 'released' AND NEW.status = 'released') OR
                        (OLD.status = 'cancelled' AND NEW.status = 'cancelled')
                    ) THEN
                        RAISE EXCEPTION 'Legal hold state cannot reopen or move backwards';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_legal_holds_immutable
                BEFORE UPDATE OR DELETE ON legal_holds
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_legal_hold_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE FUNCTION caseops_reject_legal_hold_item_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'Legal hold scope is immutable';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_legal_hold_items_immutable
                BEFORE UPDATE OR DELETE ON legal_hold_items
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_legal_hold_item_mutation()
                """
            )
        )
        return
    if bind.dialect.name == "sqlite":
        predicate = " OR ".join(
            f'OLD."{column}" IS NOT NEW."{column}"' for column in immutable_columns
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_legal_holds_immutable
                BEFORE UPDATE ON legal_holds
                FOR EACH ROW WHEN
                    ({predicate}) OR
                    NOT (
                        (OLD.status = 'draft' AND
                         NEW.status IN ('draft', 'active', 'cancelled')) OR
                        (OLD.status = 'active' AND
                         NEW.status IN ('active', 'released')) OR
                        (OLD.status = 'released' AND NEW.status = 'released') OR
                        (OLD.status = 'cancelled' AND NEW.status = 'cancelled')
                    )
                BEGIN
                    SELECT RAISE(ABORT, 'Legal hold mutation rejected');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_legal_holds_no_delete
                BEFORE DELETE ON legal_holds
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Legal holds are retained');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_legal_hold_items_no_update
                BEFORE UPDATE ON legal_hold_items
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Legal hold scope is immutable');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_legal_hold_items_no_delete
                BEFORE DELETE ON legal_hold_items
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Legal hold scope is retained');
                END
                """
            )
        )


def _create_operation_immutability_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        predicate = _postgres_immutable_predicate(
            _OPERATION_IMMUTABLE_COLUMNS,
            json_columns=frozenset({"request_scope_json", "manifest_json"}),
        )
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION caseops_reject_tenant_data_operation_mutation()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION
                            'Tenant data-operation manifests are retained';
                    END IF;
                    IF {predicate} THEN
                        RAISE EXCEPTION 'Tenant data-operation manifest is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_tenant_data_operations_immutable
                BEFORE UPDATE OR DELETE ON tenant_data_operations
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_tenant_data_operation_mutation()
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE FUNCTION caseops_reject_tenant_data_operation_item_mutation()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'Tenant data-operation items are immutable';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_tenant_data_operation_items_immutable
                BEFORE UPDATE OR DELETE ON tenant_data_operation_items
                FOR EACH ROW
                EXECUTE FUNCTION caseops_reject_tenant_data_operation_item_mutation()
                """
            )
        )
        return
    if bind.dialect.name == "sqlite":
        predicate = " OR ".join(
            f'OLD."{column}" IS NOT NEW."{column}"'
            for column in _OPERATION_IMMUTABLE_COLUMNS
        )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER trg_tenant_data_operations_immutable
                BEFORE UPDATE ON tenant_data_operations
                FOR EACH ROW WHEN {predicate}
                BEGIN
                    SELECT RAISE(ABORT, 'Tenant data-operation manifest is immutable');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_tenant_data_operations_no_delete
                BEFORE DELETE ON tenant_data_operations
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Tenant data-operation manifests are retained');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_tenant_data_operation_items_no_update
                BEFORE UPDATE ON tenant_data_operation_items
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Tenant data-operation items are immutable');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_tenant_data_operation_items_no_delete
                BEFORE DELETE ON tenant_data_operation_items
                FOR EACH ROW
                BEGIN
                    SELECT RAISE(ABORT, 'Tenant data-operation items are retained');
                END
                """
            )
        )


def _drop_guards(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        for trigger_name, table_name in (
            ("trg_tenant_data_operation_items_immutable", "tenant_data_operation_items"),
            ("trg_tenant_data_operations_immutable", "tenant_data_operations"),
            ("trg_legal_hold_items_immutable", "legal_hold_items"),
            ("trg_legal_holds_immutable", "legal_holds"),
            ("trg_data_retention_versions_immutable", "data_retention_versions"),
            ("trg_data_retention_policies_no_delete", "data_retention_policies"),
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name} ON {table_name}"))
        for function_name in (
            "caseops_reject_tenant_data_operation_item_mutation",
            "caseops_reject_tenant_data_operation_mutation",
            "caseops_reject_legal_hold_item_mutation",
            "caseops_reject_legal_hold_mutation",
            "caseops_reject_retention_version_mutation",
            "caseops_reject_data_retention_policy_delete",
        ):
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function_name}()"))
        return
    if bind.dialect.name == "sqlite":
        for trigger_name in (
            "trg_tenant_data_operation_items_no_delete",
            "trg_tenant_data_operation_items_no_update",
            "trg_tenant_data_operations_no_delete",
            "trg_tenant_data_operations_immutable",
            "trg_legal_hold_items_no_delete",
            "trg_legal_hold_items_no_update",
            "trg_legal_holds_no_delete",
            "trg_legal_holds_immutable",
            "trg_data_retention_versions_no_delete",
            "trg_data_retention_versions_immutable",
            "trg_data_retention_policies_no_delete",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger_name}"))


def upgrade() -> None:
    op.create_table(
        "data_retention_policies",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'active'"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'retired')",
            name="ck_data_retention_policy_status",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_data_retention_policy_id_company"),
        sa.UniqueConstraint("company_id", "key", name="uq_data_retention_policy_company_key"),
    )
    op.create_index(
        "ix_data_retention_policies_company_id",
        "data_retention_policies",
        ["company_id"],
    )

    op.create_table(
        "data_retention_versions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("policy_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'candidate'"),
        ),
        sa.Column("data_class_selector_json", sa.JSON(), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("legal_policy_basis", sa.String(length=512), nullable=False),
        sa.Column("sensitivity", sa.String(length=24), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=True),
        sa.Column("indefinite_retention_approval_ref", sa.String(length=512), nullable=True),
        sa.Column("disposition", sa.String(length=80), nullable=False),
        sa.Column("hold_behavior", sa.String(length=80), nullable=False),
        sa.Column("source_license_limits", sa.Text(), nullable=True),
        sa.Column("region", sa.String(length=80), nullable=True),
        sa.Column("subprocessor", sa.String(length=255), nullable=True),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("proposed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("proposed_by_membership_company_id", sa.String(length=36), nullable=True),
        sa.Column("proposer_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("reviewed_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_membership_company_id", sa.String(length=36), nullable=True),
        sa.Column("reviewer_label_snapshot", sa.String(length=255), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_data_retention_version_positive"),
        sa.CheckConstraint(
            "status IN ('candidate', 'approved', 'active', 'retired', 'disabled')",
            name="ck_data_retention_version_status",
        ),
        sa.CheckConstraint(
            "sensitivity IN ('internal', 'confidential', 'privileged')",
            name="ck_data_retention_version_sensitivity",
        ),
        sa.CheckConstraint(
            "retention_days IS NULL OR retention_days > 0",
            name="ck_data_retention_version_retention_days_positive",
        ),
        sa.CheckConstraint(
            "(retention_days IS NOT NULL AND "
            "indefinite_retention_approval_ref IS NULL) OR "
            "(retention_days IS NULL AND "
            "indefinite_retention_approval_ref IS NOT NULL)",
            name="ck_data_retention_version_explicit_indefinite_approval",
        ),
        sa.CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_data_retention_version_policy_hash_length",
        ),
        sa.CheckConstraint(
            "proposed_by_membership_id IS NULL OR reviewed_by_membership_id IS NULL "
            "OR proposed_by_membership_id <> reviewed_by_membership_id",
            name="ck_data_retention_version_reviewer_distinct",
        ),
        sa.CheckConstraint(
            "(proposed_by_membership_id IS NULL AND "
            "proposed_by_membership_company_id IS NULL) OR "
            "(proposed_by_membership_id IS NOT NULL AND "
            "proposed_by_membership_company_id = company_id)",
            name="ck_data_retention_version_proposer_company_complete",
        ),
        sa.CheckConstraint(
            "(reviewed_by_membership_id IS NULL AND "
            "reviewed_by_membership_company_id IS NULL) OR "
            "(reviewed_by_membership_id IS NOT NULL AND "
            "reviewed_by_membership_company_id = company_id)",
            name="ck_data_retention_version_reviewer_company_complete",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id", "company_id"],
            ["data_retention_policies.id", "data_retention_policies.company_id"],
            name="fk_data_retention_version_policy_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_membership_id", "proposed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_data_retention_version_proposer_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id", "reviewed_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_data_retention_version_reviewer_company",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_data_retention_version_id_company"),
        sa.UniqueConstraint(
            "policy_id",
            "company_id",
            "version",
            name="uq_data_retention_version_policy_company_number",
        ),
    )
    op.create_index(
        "ix_data_retention_versions_company_status",
        "data_retention_versions",
        ["company_id", "status", "created_at"],
    )
    op.create_index(
        "ix_data_retention_versions_policy_id",
        "data_retention_versions",
        ["policy_id"],
    )
    op.create_index(
        "ix_data_retention_versions_proposer_company",
        "data_retention_versions",
        ["proposed_by_membership_id", "proposed_by_membership_company_id"],
    )
    op.create_index(
        "ix_data_retention_versions_reviewer_company",
        "data_retention_versions",
        ["reviewed_by_membership_id", "reviewed_by_membership_company_id"],
    )

    op.create_table(
        "legal_holds",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("authority_reference", sa.String(length=512), nullable=False),
        sa.Column("reason_redacted", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'draft'"),
        ),
        sa.Column("created_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("created_by_membership_company_id", sa.String(length=36), nullable=True),
        sa.Column("creator_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("approved_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("approved_by_membership_company_id", sa.String(length=36), nullable=True),
        sa.Column("approver_label_snapshot", sa.String(length=255), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason_redacted", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'released', 'cancelled')",
            name="ck_legal_hold_status",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND activated_at IS NOT NULL AND "
            "created_by_membership_id IS NOT NULL AND "
            "created_by_membership_company_id = company_id AND "
            "approved_by_membership_id IS NOT NULL AND "
            "approved_by_membership_company_id = company_id) OR "
            "status <> 'active'",
            name="ck_legal_hold_activation_approval",
        ),
        sa.CheckConstraint(
            "(status = 'released' AND released_at IS NOT NULL) OR "
            "status <> 'released'",
            name="ck_legal_hold_release_state",
        ),
        sa.CheckConstraint(
            "created_by_membership_id IS NULL OR approved_by_membership_id IS NULL "
            "OR created_by_membership_id <> approved_by_membership_id",
            name="ck_legal_hold_approver_distinct",
        ),
        sa.CheckConstraint(
            "(created_by_membership_id IS NULL AND "
            "created_by_membership_company_id IS NULL) OR "
            "(created_by_membership_id IS NOT NULL AND "
            "created_by_membership_company_id = company_id)",
            name="ck_legal_hold_creator_company_complete",
        ),
        sa.CheckConstraint(
            "(approved_by_membership_id IS NULL AND "
            "approved_by_membership_company_id IS NULL) OR "
            "(approved_by_membership_id IS NOT NULL AND "
            "approved_by_membership_company_id = company_id)",
            name="ck_legal_hold_approver_company_complete",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "created_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_hold_creator_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_membership_id", "approved_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_legal_hold_approver_company",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_legal_hold_id_company"),
        sa.UniqueConstraint("company_id", "key", name="uq_legal_hold_company_key"),
    )
    op.create_index(
        "ix_legal_holds_company_status",
        "legal_holds",
        ["company_id", "status", "created_at"],
    )

    op.create_table(
        "legal_hold_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("legal_hold_id", sa.String(length=36), nullable=False),
        sa.Column("data_class_id", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_reference_hash", sa.String(length=64), nullable=False),
        sa.Column("target_label_redacted", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(target_reference_hash) = 64",
            name="ck_legal_hold_item_target_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["legal_hold_id", "company_id"],
            ["legal_holds.id", "legal_holds.company_id"],
            name="fk_legal_hold_item_hold_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_legal_hold_item_id_company"),
        sa.UniqueConstraint(
            "legal_hold_id",
            "company_id",
            "data_class_id",
            "target_type",
            "target_reference_hash",
            name="uq_legal_hold_item_target",
        ),
    )
    op.create_index(
        "ix_legal_hold_items_company_target",
        "legal_hold_items",
        ["company_id", "data_class_id", "target_type"],
    )
    op.create_index("ix_legal_hold_items_legal_hold_id", "legal_hold_items", ["legal_hold_id"])

    op.create_table(
        "tenant_data_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("operation_type", sa.String(length=40), nullable=False),
        sa.Column(
            "execution_mode",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'dry_run'"),
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'planned'"),
        ),
        sa.Column(
            "approval_status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'not_requested'"),
        ),
        sa.Column("request_scope_json", sa.JSON(), nullable=False),
        sa.Column("request_scope_hash", sa.String(length=64), nullable=False),
        sa.Column("request_evidence_ref", sa.String(length=512), nullable=False),
        sa.Column("retention_policy_version_id", sa.String(length=36), nullable=True),
        sa.Column("manifest_json", sa.JSON(), nullable=True),
        sa.Column("manifest_hash", sa.String(length=64), nullable=True),
        sa.Column("requested_by_membership_id", sa.String(length=36), nullable=True),
        sa.Column("requested_by_membership_company_id", sa.String(length=36), nullable=True),
        sa.Column("requester_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("dry_run_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("blocked_reason", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "operation_type IN ('tenant_export', 'retention_purge', "
            "'tenant_offboarding', 'restore_validation')",
            name="ck_tenant_data_operation_type",
        ),
        sa.CheckConstraint(
            "execution_mode = 'dry_run'",
            name="ck_tenant_data_operation_dry_run_only",
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'dry_run_complete', 'blocked', 'cancelled')",
            name="ck_tenant_data_operation_status",
        ),
        sa.CheckConstraint(
            "approval_status = 'not_requested'",
            name="ck_tenant_data_operation_execute_approval_closed",
        ),
        sa.CheckConstraint(
            "length(request_scope_hash) = 64",
            name="ck_tenant_data_operation_scope_hash_length",
        ),
        sa.CheckConstraint(
            "manifest_hash IS NULL OR length(manifest_hash) = 64",
            name="ck_tenant_data_operation_manifest_hash_length",
        ),
        sa.CheckConstraint(
            "(status = 'dry_run_complete' AND dry_run_completed_at IS NOT NULL "
            "AND manifest_hash IS NOT NULL) OR status <> 'dry_run_complete'",
            name="ck_tenant_data_operation_completion_manifest",
        ),
        sa.CheckConstraint(
            "(requested_by_membership_id IS NULL AND "
            "requested_by_membership_company_id IS NULL) OR "
            "(requested_by_membership_id IS NOT NULL AND "
            "requested_by_membership_company_id = company_id)",
            name="ck_tenant_data_operation_requester_company_complete",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "requested_by_membership_company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_tenant_data_operation_requester_company",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["retention_policy_version_id", "company_id"],
            ["data_retention_versions.id", "data_retention_versions.company_id"],
            name="fk_tenant_data_operation_policy_version_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "company_id", name="uq_tenant_data_operation_id_company"),
    )
    op.create_index(
        "ix_tenant_data_operations_company_status",
        "tenant_data_operations",
        ["company_id", "status", "created_at"],
    )
    op.create_index(
        "ix_tenant_data_operations_requester_company",
        "tenant_data_operations",
        ["requested_by_membership_id", "requested_by_membership_company_id"],
    )
    op.create_index(
        "ix_tenant_data_operations_retention_policy_version_id",
        "tenant_data_operations",
        ["retention_policy_version_id"],
    )

    op.create_table(
        "tenant_data_operation_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("operation_id", sa.String(length=36), nullable=False),
        sa.Column("data_class_id", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_reference_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "item_status",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "candidate_record_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "estimated_bytes",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("legal_hold_id", sa.String(length=36), nullable=True),
        sa.Column(
            "safe_to_execute",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("detail_redacted", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "item_status IN ('pending', 'eligible', 'held', 'blocked')",
            name="ck_tenant_data_operation_item_status",
        ),
        sa.CheckConstraint(
            "length(target_reference_hash) = 64",
            name="ck_tenant_data_operation_item_target_hash_length",
        ),
        sa.CheckConstraint(
            "candidate_record_count >= 0 AND estimated_bytes >= 0",
            name="ck_tenant_data_operation_item_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "safe_to_execute = false",
            name="ck_tenant_data_operation_item_never_execute",
        ),
        sa.CheckConstraint(
            "(item_status = 'held' AND legal_hold_id IS NOT NULL) OR "
            "item_status <> 'held'",
            name="ck_tenant_data_operation_item_hold_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["operation_id", "company_id"],
            ["tenant_data_operations.id", "tenant_data_operations.company_id"],
            name="fk_tenant_data_operation_item_operation_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["legal_hold_id", "company_id"],
            ["legal_holds.id", "legal_holds.company_id"],
            name="fk_tenant_data_operation_item_hold_company",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "company_id",
            name="uq_tenant_data_operation_item_id_company",
        ),
        sa.UniqueConstraint(
            "operation_id",
            "company_id",
            "data_class_id",
            "target_type",
            "target_reference_hash",
            name="uq_tenant_data_operation_item_target",
        ),
    )
    op.create_index(
        "ix_tenant_data_operation_items_company_operation",
        "tenant_data_operation_items",
        ["company_id", "operation_id", "item_status"],
    )
    op.create_index(
        "ix_tenant_data_operation_items_operation_id",
        "tenant_data_operation_items",
        ["operation_id"],
    )

    bind = op.get_bind()
    _create_retention_version_immutability_guard(bind)
    _create_legal_hold_immutability_guard(bind)
    _create_operation_immutability_guard(bind)


def downgrade() -> None:
    bind = op.get_bind()
    _assert_downgrade_is_evidence_free(bind)
    _drop_guards(bind)
    op.drop_index(
        "ix_tenant_data_operation_items_operation_id",
        table_name="tenant_data_operation_items",
    )
    op.drop_index(
        "ix_tenant_data_operation_items_company_operation",
        table_name="tenant_data_operation_items",
    )
    op.drop_table("tenant_data_operation_items")
    op.drop_index(
        "ix_tenant_data_operations_retention_policy_version_id",
        table_name="tenant_data_operations",
    )
    op.drop_index(
        "ix_tenant_data_operations_requester_company",
        table_name="tenant_data_operations",
    )
    op.drop_index(
        "ix_tenant_data_operations_company_status",
        table_name="tenant_data_operations",
    )
    op.drop_table("tenant_data_operations")
    op.drop_index("ix_legal_hold_items_legal_hold_id", table_name="legal_hold_items")
    op.drop_index("ix_legal_hold_items_company_target", table_name="legal_hold_items")
    op.drop_table("legal_hold_items")
    op.drop_index("ix_legal_holds_company_status", table_name="legal_holds")
    op.drop_table("legal_holds")
    op.drop_index(
        "ix_data_retention_versions_reviewer_company",
        table_name="data_retention_versions",
    )
    op.drop_index(
        "ix_data_retention_versions_proposer_company",
        table_name="data_retention_versions",
    )
    op.drop_index(
        "ix_data_retention_versions_policy_id",
        table_name="data_retention_versions",
    )
    op.drop_index(
        "ix_data_retention_versions_company_status",
        table_name="data_retention_versions",
    )
    op.drop_table("data_retention_versions")
    op.drop_index(
        "ix_data_retention_policies_company_id",
        table_name="data_retention_policies",
    )
    op.drop_table("data_retention_policies")
