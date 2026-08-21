"""Complete immutable daily-docket review evidence for UJ-59.

Revision ID: 20260821_0002
Revises: 20260821_0001

New reviews bind a two-signature policy, second-reviewer sampling and an
explicit delta from the preceding signed report into the immutable manifest.
Exception decisions, samples and signatures are append-only evidence.

DATA-GOVERNANCE-MAP: updated
The three child tables inherit the parent ``ip_docket_control_reviews``
``tenant_restricted_legal_content`` classification and retention owner. They
contain identifiers and evidence references, but no docket titles or provider
content. No runtime deletion path is introduced.

MIGRATION-LOCK-RISK: acknowledged. Additive columns use constant defaults;
new tables and indexes are empty. PostgreSQL lock acquisition is bounded.

MIGRATION-ROLLBACK: restore-forward. Downgrade refuses once a v2 review or any
child evidence exists, because rollback would erase reviewer decisions or
signatures.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260821_0002"
down_revision = "20260821_0001"
branch_labels = None
depends_on = None

REVIEW_TABLE = "ip_docket_control_reviews"
DECISION_TABLE = "ip_control_review_exception_decisions"
SAMPLE_TABLE = "ip_control_review_sample_evidence"
SIGNATURE_TABLE = "ip_control_review_signatures"
IMMUTABLE_FUNCTION = "caseops_reject_ip_control_review_evidence_mutation"
PARENT_TRIGGER = "trg_ip_control_review_manifest_immutable"


def _create_evidence_table(
    table_name: str,
    *columns: sa.Column,
    review_fk_name: str,
    constraints: tuple[sa.SchemaItem, ...],
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("company_id", sa.String(length=36), nullable=False),
        sa.Column("review_id", sa.String(length=36), nullable=False),
        *columns,
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["review_id", "company_id"],
            [f"{REVIEW_TABLE}.id", f"{REVIEW_TABLE}.company_id"],
            name=review_fk_name,
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        *constraints,
    )
    op.create_index(f"ix_{table_name}_company_id", table_name, ["company_id"])


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    if bind.dialect.name == "postgresql":
        op.create_unique_constraint(
            "uq_ip_control_review_id_company",
            REVIEW_TABLE,
            ["id", "company_id"],
        )
        op.create_unique_constraint(
            "uq_ip_control_review_id_company_manifest",
            REVIEW_TABLE,
            ["id", "company_id", "manifest_sha256"],
        )
    else:
        op.create_index(
            "uq_ip_control_review_id_company",
            REVIEW_TABLE,
            ["id", "company_id"],
            unique=True,
        )
        op.create_index(
            "uq_ip_control_review_id_company_manifest",
            REVIEW_TABLE,
            ["id", "company_id", "manifest_sha256"],
            unique=True,
        )
    op.add_column(
        REVIEW_TABLE,
        sa.Column(
            "review_policy_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        REVIEW_TABLE,
        sa.Column("required_signature_count", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        REVIEW_TABLE,
        sa.Column("required_sample_size", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        REVIEW_TABLE,
        sa.Column("predecessor_review_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        REVIEW_TABLE,
        sa.Column("delta_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_ip_control_review_predecessor",
        REVIEW_TABLE,
        ["predecessor_review_id"],
    )
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_ip_control_review_policy_bounds",
            REVIEW_TABLE,
            "required_signature_count IN (1, 2) AND required_sample_size BETWEEN 0 AND 20",
        )
        op.create_foreign_key(
            "fk_ip_control_review_predecessor_company",
            REVIEW_TABLE,
            REVIEW_TABLE,
            ["predecessor_review_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )

    _create_evidence_table(
        DECISION_TABLE,
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("exception_kind", sa.String(length=40), nullable=False),
        sa.Column("disposition", sa.String(length=16), nullable=False),
        sa.Column("annotation", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("decided_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        review_fk_name="fk_ip_control_exception_decision_review_company",
        constraints=(
            sa.ForeignKeyConstraint(
                ["decided_by_membership_id", "company_id"],
                ["company_memberships.id", "company_memberships.company_id"],
                name="fk_ip_control_exception_decision_actor_company",
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint(
                "disposition IN ('resolved', 'annotated')",
                name="ck_ip_control_exception_decision_disposition",
            ),
            sa.UniqueConstraint(
                "review_id",
                "docket_id",
                "exception_kind",
                name="uq_ip_control_exception_decision",
            ),
        ),
    )
    op.create_index(
        "ix_ip_control_exception_decision_actor",
        DECISION_TABLE,
        ["decided_by_membership_id"],
    )
    op.create_index(
        "ix_ip_control_exception_decision_review",
        DECISION_TABLE,
        ["review_id", "decided_at"],
    )

    _create_evidence_table(
        SAMPLE_TABLE,
        sa.Column("docket_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_membership_id", sa.String(length=36), nullable=False),
        sa.Column("source_evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("calculation_evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("coverage_evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), nullable=False),
        review_fk_name="fk_ip_control_sample_review_company",
        constraints=(
            sa.ForeignKeyConstraint(
                ["reviewer_membership_id", "company_id"],
                ["company_memberships.id", "company_memberships.company_id"],
                name="fk_ip_control_sample_reviewer_company",
                ondelete="RESTRICT",
            ),
            sa.UniqueConstraint(
                "review_id",
                "docket_id",
                "reviewer_membership_id",
                name="uq_ip_control_sample_reviewer_docket",
            ),
        ),
    )
    op.create_index(
        "ix_ip_control_sample_reviewer",
        SAMPLE_TABLE,
        ["reviewer_membership_id"],
    )
    op.create_index(
        "ix_ip_control_sample_review",
        SAMPLE_TABLE,
        ["review_id", "sampled_at"],
    )

    _create_evidence_table(
        SIGNATURE_TABLE,
        sa.Column("signer_membership_id", sa.String(length=36), nullable=False),
        sa.Column("signer_role", sa.String(length=16), nullable=False),
        sa.Column("signer_label_snapshot", sa.String(length=255), nullable=False),
        sa.Column("attestation", sa.Text(), nullable=False),
        sa.Column("manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=False),
        review_fk_name="fk_ip_control_signature_review_company",
        constraints=(
            sa.ForeignKeyConstraint(
                ["review_id", "company_id", "manifest_sha256"],
                [
                    f"{REVIEW_TABLE}.id",
                    f"{REVIEW_TABLE}.company_id",
                    f"{REVIEW_TABLE}.manifest_sha256",
                ],
                name="fk_ip_control_signature_manifest",
                ondelete="RESTRICT",
            ),
            sa.ForeignKeyConstraint(
                ["signer_membership_id", "company_id"],
                ["company_memberships.id", "company_memberships.company_id"],
                name="fk_ip_control_signature_signer_company",
                ondelete="RESTRICT",
            ),
            sa.CheckConstraint(
                "(signer_role = 'preparer' AND sequence = 1) OR "
                "(signer_role = 'reviewer' AND sequence = 2)",
                name="ck_ip_control_signature_role_sequence",
            ),
            sa.UniqueConstraint(
                "review_id", "signer_membership_id", name="uq_ip_control_signature_actor"
            ),
            sa.UniqueConstraint("review_id", "sequence", name="uq_ip_control_signature_sequence"),
            sa.UniqueConstraint("review_id", "signer_role", name="uq_ip_control_signature_role"),
        ),
    )
    op.create_index(
        "ix_ip_control_signature_signer",
        SIGNATURE_TABLE,
        ["signer_membership_id"],
    )
    op.create_index(
        "ix_ip_control_signature_manifest_sha256",
        SIGNATURE_TABLE,
        ["manifest_sha256"],
    )
    op.create_index(
        "ix_ip_control_signature_review",
        SIGNATURE_TABLE,
        ["review_id", "sequence"],
    )

    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                f"""
                CREATE FUNCTION {IMMUTABLE_FUNCTION}() RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'IP control-review evidence is append-only'
                        USING ERRCODE = 'restrict_violation';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        for table_name in (DECISION_TABLE, SAMPLE_TABLE, SIGNATURE_TABLE):
            op.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table_name}_immutable "
                    f"BEFORE UPDATE OR DELETE ON {table_name} "
                    f"FOR EACH ROW EXECUTE FUNCTION {IMMUTABLE_FUNCTION}()"
                )
            )
        op.execute(
            sa.text(
                f"""
                CREATE TRIGGER {PARENT_TRIGGER}
                BEFORE UPDATE ON {REVIEW_TABLE}
                FOR EACH ROW
                WHEN (
                    NEW.generated_at IS DISTINCT FROM OLD.generated_at OR
                    NEW.filters_json::text IS DISTINCT FROM OLD.filters_json::text OR
                    NEW.freshness_json::text IS DISTINCT FROM OLD.freshness_json::text OR
                    NEW.incompleteness_reasons_json::text
                        IS DISTINCT FROM OLD.incompleteness_reasons_json::text OR
                    NEW.mandatory_exception_ids_json::text
                        IS DISTINCT FROM OLD.mandatory_exception_ids_json::text OR
                    NEW.query_version IS DISTINCT FROM OLD.query_version OR
                    NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version OR
                    NEW.report_snapshot_json::text
                        IS DISTINCT FROM OLD.report_snapshot_json::text OR
                    NEW.manifest_sha256 IS DISTINCT FROM OLD.manifest_sha256 OR
                    NEW.review_policy_json::text IS DISTINCT FROM OLD.review_policy_json::text OR
                    NEW.required_signature_count
                        IS DISTINCT FROM OLD.required_signature_count OR
                    NEW.required_sample_size IS DISTINCT FROM OLD.required_sample_size OR
                    NEW.predecessor_review_id IS DISTINCT FROM OLD.predecessor_review_id OR
                    NEW.delta_json::text IS DISTINCT FROM OLD.delta_json::text OR
                    NEW.created_by_membership_id IS DISTINCT FROM OLD.created_by_membership_id OR
                    NEW.created_at IS DISTINCT FROM OLD.created_at
                )
                EXECUTE FUNCTION {IMMUTABLE_FUNCTION}()
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    child_count = sum(
        int(bind.scalar(sa.text(f"SELECT count(*) FROM {table_name}")) or 0)
        for table_name in (DECISION_TABLE, SAMPLE_TABLE, SIGNATURE_TABLE)
    )
    v2_count = int(
        bind.scalar(
            sa.text(
                f"SELECT count(*) FROM {REVIEW_TABLE} "
                "WHERE snapshot_schema_version >= 2 OR predecessor_review_id IS NOT NULL "
                "OR required_signature_count > 1 OR required_sample_size > 0"
            )
        )
        or 0
    )
    if child_count or v2_count:
        raise RuntimeError(
            "refusing to downgrade: immutable control-review evidence would be destroyed"
        )

    if bind.dialect.name == "postgresql":
        op.execute(sa.text(f"DROP TRIGGER IF EXISTS {PARENT_TRIGGER} ON {REVIEW_TABLE}"))
        for table_name in (DECISION_TABLE, SAMPLE_TABLE, SIGNATURE_TABLE):
            op.execute(
                sa.text(f"DROP TRIGGER IF EXISTS trg_{table_name}_immutable ON {table_name}")
            )
        op.execute(sa.text(f"DROP FUNCTION IF EXISTS {IMMUTABLE_FUNCTION}()"))

    for table_name in (SIGNATURE_TABLE, SAMPLE_TABLE, DECISION_TABLE):
        op.drop_table(table_name)

    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "fk_ip_control_review_predecessor_company",
            REVIEW_TABLE,
            type_="foreignkey",
        )
    op.drop_index("ix_ip_control_review_predecessor", table_name=REVIEW_TABLE)
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "ck_ip_control_review_policy_bounds",
            REVIEW_TABLE,
            type_="check",
        )
    op.drop_column(REVIEW_TABLE, "delta_json")
    op.drop_column(REVIEW_TABLE, "predecessor_review_id")
    op.drop_column(REVIEW_TABLE, "required_sample_size")
    op.drop_column(REVIEW_TABLE, "required_signature_count")
    op.drop_column(REVIEW_TABLE, "review_policy_json")
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "uq_ip_control_review_id_company_manifest",
            REVIEW_TABLE,
            type_="unique",
        )
        op.drop_constraint(
            "uq_ip_control_review_id_company",
            REVIEW_TABLE,
            type_="unique",
        )
    else:
        op.drop_index("uq_ip_control_review_id_company_manifest", table_name=REVIEW_TABLE)
        op.drop_index("uq_ip_control_review_id_company", table_name=REVIEW_TABLE)
