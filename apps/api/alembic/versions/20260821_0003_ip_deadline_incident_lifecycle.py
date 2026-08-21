"""Complete restricted deadline-incident evidence and lifecycle for UJ-58.

Revision ID: 20260821_0003
Revises: 20260821_0002
Create Date: 2026-08-21
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260821_0003"
down_revision = "20260821_0002"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated

INCIDENT_TABLE = "ip_deadline_incidents"
IMPACT_TABLE = "ip_deadline_incident_impacts"
ACTION_TABLE = "ip_deadline_incident_actions"
NOTICE_TABLE = "ip_deadline_incident_notification_decisions"
KILL_SWITCH_TABLE = "ip_incident_kill_switches"


def _evidence_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(length=36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("incident_id", sa.String(length=36), nullable=False),
    )


def _incident_fk(name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["incident_id", "company_id"],
        [f"{INCIDENT_TABLE}.id", f"{INCIDENT_TABLE}.company_id"],
        name=name,
        ondelete="RESTRICT",
    )


def _membership_fk(column: str, name: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column, "company_id"],
        ["company_memberships.id", "company_memberships.company_id"],
        name=name,
        ondelete="RESTRICT",
    )


def upgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table(INCIDENT_TABLE) as batch:
        batch.add_column(
            sa.Column(
                "evidence_snapshot_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(
            sa.Column(
                "preservation_manifest_sha256",
                sa.String(length=64),
                nullable=False,
                server_default="0000000000000000000000000000000000000000000000000000000000000000",
            )
        )
        batch.add_column(
            sa.Column(
                "defect_scope",
                sa.String(length=24),
                nullable=False,
                server_default="record_specific",
            )
        )
        batch.add_column(sa.Column("defect_fingerprint_sha256", sa.String(length=64)))
        batch.add_column(sa.Column("impact_scan_completed_at", sa.DateTime(timezone=True)))
        batch.add_column(
            sa.Column("impact_scan_completed_by_membership_id", sa.String(length=36))
        )
        batch.add_column(sa.Column("root_cause", sa.Text()))
        batch.add_column(sa.Column("preventive_action", sa.Text()))
        batch.add_column(sa.Column("prevention_verified_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolution_evidence_reference", sa.String(length=500)))
        batch.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True)))
        batch.add_column(sa.Column("resolved_by_membership_id", sa.String(length=36)))
        batch.add_column(
            sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch.add_column(sa.Column("created_by_membership_id", sa.String(length=36)))

    op.execute(
        sa.text(
            f"""
            UPDATE {INCIDENT_TABLE}
               SET resolved_at = COALESCE(verified_at, created_at),
                   resolved_by_membership_id = verified_by_membership_id,
                   resolution_evidence_reference = 'legacy:verified',
                   root_cause = 'Legacy verification record; root-cause detail unavailable.',
                   preventive_action = 'Legacy verification record; prevention detail unavailable.',
                   prevention_verified_at = COALESCE(verified_at, created_at)
             WHERE status = 'verified'
            """
        )
    )

    with op.batch_alter_table(INCIDENT_TABLE) as batch:
        batch.drop_constraint("fk_ip_deadline_incident_docket_company", type_="foreignkey")
        batch.create_foreign_key(
            "fk_ip_deadline_incident_docket_company",
            "ip_docket_records",
            ["docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_unique_constraint(
            "uq_ip_deadline_incident_id_company", ["id", "company_id"]
        )
        batch.create_check_constraint(
            "ck_ip_deadline_incident_status",
            "status IN ('open', 'contained', 'impact_assessed', 'disproved', 'verified')",
        )
        batch.create_check_constraint(
            "ck_ip_deadline_incident_defect_scope",
            "defect_scope IN ('record_specific', 'shared_rule', 'shared_source', 'platform_wide')",
        )
        batch.create_check_constraint(
            "ck_ip_deadline_incident_terminal_evidence",
            "status NOT IN ('disproved', 'verified') OR "
            "(resolved_by_membership_id IS NOT NULL AND resolved_at IS NOT NULL "
            "AND resolution_evidence_reference IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_ip_deadline_incident_creator_company",
            "company_memberships",
            ["created_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_deadline_incident_impact_actor_company",
            "company_memberships",
            ["impact_scan_completed_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_deadline_incident_resolver_company",
            "company_memberships",
            ["resolved_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_ip_deadline_incident_verifier_company",
            "company_memberships",
            ["verified_by_membership_id", "company_id"],
            ["id", "company_id"],
            ondelete="RESTRICT",
        )

    op.create_index(
        "ix_ip_deadline_incident_creator", INCIDENT_TABLE, ["created_by_membership_id"]
    )
    op.create_index(
        "ix_ip_deadline_incident_impact_completed_actor",
        INCIDENT_TABLE,
        ["impact_scan_completed_by_membership_id"],
    )
    op.create_index(
        "ix_ip_deadline_incident_resolver", INCIDENT_TABLE, ["resolved_by_membership_id"]
    )
    op.create_index(
        "ix_ip_deadline_incident_verifier", INCIDENT_TABLE, ["verified_by_membership_id"]
    )

    op.create_table(
        IMPACT_TABLE,
        *_evidence_columns(),
        sa.Column("record_type", sa.String(length=40), nullable=False),
        sa.Column("record_reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("relationship", sa.String(length=120), nullable=False),
        sa.Column("assessment", sa.String(length=20), nullable=False),
        sa.Column("scan_method", sa.String(length=80), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("assessed_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        _incident_fk("fk_ip_deadline_incident_impact_incident_company"),
        _membership_fk(
            "assessed_by_membership_id", "fk_ip_deadline_incident_impact_actor_company"
        ),
        sa.CheckConstraint(
            "assessment IN ('affected', 'not_affected', 'pending')",
            name="ck_ip_deadline_incident_impact_assessment",
        ),
        sa.UniqueConstraint(
            "incident_id",
            "record_type",
            "record_reference_sha256",
            name="uq_ip_deadline_incident_impact_record",
        ),
    )
    op.create_index("ix_ip_deadline_incident_impacts_company_id", IMPACT_TABLE, ["company_id"])
    op.create_index(
        "ix_ip_deadline_incident_impact_incident", IMPACT_TABLE, ["incident_id", "assessed_at"]
    )
    op.create_index(
        "ix_ip_deadline_incident_impact_actor", IMPACT_TABLE, ["assessed_by_membership_id"]
    )

    op.create_table(
        ACTION_TABLE,
        *_evidence_columns(),
        sa.Column("action_type", sa.String(length=40), nullable=False),
        sa.Column("action_status", sa.String(length=20), nullable=False),
        sa.Column("action_reference", sa.String(length=500), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("recorded_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        _incident_fk("fk_ip_deadline_incident_action_incident_company"),
        _membership_fk(
            "recorded_by_membership_id", "fk_ip_deadline_incident_action_actor_company"
        ),
        sa.CheckConstraint(
            "action_status IN ('planned', 'completed', 'not_available')",
            name="ck_ip_deadline_incident_action_status",
        ),
    )
    op.create_index("ix_ip_deadline_incident_actions_company_id", ACTION_TABLE, ["company_id"])
    op.create_index(
        "ix_ip_deadline_incident_action_incident", ACTION_TABLE, ["incident_id", "recorded_at"]
    )
    op.create_index(
        "ix_ip_deadline_incident_action_actor", ACTION_TABLE, ["recorded_by_membership_id"]
    )

    op.create_table(
        NOTICE_TABLE,
        *_evidence_columns(),
        sa.Column("recipient_type", sa.String(length=24), nullable=False),
        sa.Column("recipient_reference_sha256", sa.String(length=64), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("decision_version", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("approval_evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("communication_reference", sa.String(length=500)),
        sa.Column("decided_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        _incident_fk("fk_ip_deadline_incident_notice_incident_company"),
        _membership_fk(
            "decided_by_membership_id", "fk_ip_deadline_incident_notice_actor_company"
        ),
        sa.CheckConstraint(
            "recipient_type IN ('client', 'insurer', 'regulator', 'court', 'external_counsel')",
            name="ck_ip_deadline_incident_notice_recipient_type",
        ),
        sa.CheckConstraint(
            "decision IN ('pending', 'notify', 'do_not_notify', 'not_applicable')",
            name="ck_ip_deadline_incident_notice_decision",
        ),
        sa.UniqueConstraint(
            "incident_id",
            "recipient_type",
            "recipient_reference_sha256",
            "decision_version",
            name="uq_ip_deadline_incident_notice_version",
        ),
    )
    op.create_index("ix_ip_deadline_incident_notices_company_id", NOTICE_TABLE, ["company_id"])
    op.create_index(
        "ix_ip_deadline_incident_notice_incident", NOTICE_TABLE, ["incident_id", "decided_at"]
    )
    op.create_index(
        "ix_ip_deadline_incident_notice_actor", NOTICE_TABLE, ["decided_by_membership_id"]
    )

    op.create_table(
        KILL_SWITCH_TABLE,
        *_evidence_columns(),
        sa.Column("feature_id", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="active"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("activation_evidence_reference", sa.String(length=500), nullable=False),
        sa.Column("activated_by_membership_id", sa.String(length=36), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_reason", sa.Text()),
        sa.Column("release_evidence_reference", sa.String(length=500)),
        sa.Column("released_by_membership_id", sa.String(length=36)),
        sa.Column("released_at", sa.DateTime(timezone=True)),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _incident_fk("fk_ip_incident_kill_switch_incident_company"),
        _membership_fk(
            "activated_by_membership_id", "fk_ip_incident_kill_switch_activator_company"
        ),
        _membership_fk(
            "released_by_membership_id", "fk_ip_incident_kill_switch_releaser_company"
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released')", name="ck_ip_incident_kill_switch_status"
        ),
        sa.UniqueConstraint(
            "incident_id", "feature_id", name="uq_ip_incident_kill_switch_incident_feature"
        ),
    )
    op.create_index("ix_ip_incident_kill_switches_company_id", KILL_SWITCH_TABLE, ["company_id"])
    op.create_index("ix_ip_incident_kill_switch_incident", KILL_SWITCH_TABLE, ["incident_id"])
    op.create_index(
        "ix_ip_incident_kill_switch_activator",
        KILL_SWITCH_TABLE,
        ["activated_by_membership_id"],
    )
    op.create_index(
        "ix_ip_incident_kill_switch_releaser",
        KILL_SWITCH_TABLE,
        ["released_by_membership_id"],
    )
    op.create_index(
        "uq_ip_incident_kill_switch_active_feature",
        KILL_SWITCH_TABLE,
        ["company_id", "feature_id"],
        unique=True,
        sqlite_where=sa.text("status = 'active'"),
        postgresql_where=sa.text("status = 'active'"),
    )

    if bind.dialect.name == "postgresql":
        for table in (IMPACT_TABLE, ACTION_TABLE, NOTICE_TABLE):
            op.execute(
                sa.text(
                    f"""
                    CREATE OR REPLACE FUNCTION prevent_{table}_mutation()
                    RETURNS trigger AS $$
                    BEGIN
                        RAISE EXCEPTION '{table} is append-only';
                    END;
                    $$ LANGUAGE plpgsql;
                    CREATE TRIGGER trg_{table}_append_only
                    BEFORE UPDATE OR DELETE ON {table}
                    FOR EACH ROW EXECUTE FUNCTION prevent_{table}_mutation();
                    """
                )
            )
        op.execute(
            sa.text(
                f"""
                CREATE OR REPLACE FUNCTION protect_ip_deadline_incident_evidence()
                RETURNS trigger AS $$
                BEGIN
                    IF TG_OP = 'DELETE' THEN
                        RAISE EXCEPTION '{INCIDENT_TABLE} evidence is retained';
                    END IF;
                    IF NEW.company_id IS DISTINCT FROM OLD.company_id OR
                       NEW.docket_id IS DISTINCT FROM OLD.docket_id OR
                       NEW.matter_deadline_id IS DISTINCT FROM OLD.matter_deadline_id OR
                       NEW.severity IS DISTINCT FROM OLD.severity OR
                       NEW.summary IS DISTINCT FROM OLD.summary OR
                       NEW.impact_json IS DISTINCT FROM OLD.impact_json OR
                       NEW.evidence_snapshot_json IS DISTINCT FROM OLD.evidence_snapshot_json OR
                       NEW.preservation_manifest_sha256 IS DISTINCT FROM
                           OLD.preservation_manifest_sha256 OR
                       NEW.defect_scope IS DISTINCT FROM OLD.defect_scope OR
                       NEW.defect_fingerprint_sha256 IS DISTINCT FROM
                           OLD.defect_fingerprint_sha256 OR
                       NEW.created_by_membership_id IS DISTINCT FROM OLD.created_by_membership_id OR
                       NEW.created_at IS DISTINCT FROM OLD.created_at THEN
                        RAISE EXCEPTION '{INCIDENT_TABLE} discovery evidence is immutable';
                    END IF;
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql;
                CREATE TRIGGER trg_ip_deadline_incident_evidence
                BEFORE UPDATE OR DELETE ON {INCIDENT_TABLE}
                FOR EACH ROW EXECUTE FUNCTION protect_ip_deadline_incident_evidence();
                """
            )
        )


def downgrade() -> None:
    bind = op.get_bind()
    evidence_count = sum(
        int(bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar_one())
        for table in (IMPACT_TABLE, ACTION_TABLE, NOTICE_TABLE, KILL_SWITCH_TABLE)
    )
    if evidence_count:
        raise RuntimeError("Refusing to discard persisted UJ-58 incident evidence.")

    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_ip_deadline_incident_evidence "
            "ON ip_deadline_incidents"
        )
        op.execute("DROP FUNCTION IF EXISTS protect_ip_deadline_incident_evidence()")
        for table in (IMPACT_TABLE, ACTION_TABLE, NOTICE_TABLE):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS prevent_{table}_mutation()")

    for table in (KILL_SWITCH_TABLE, NOTICE_TABLE, ACTION_TABLE, IMPACT_TABLE):
        op.drop_table(table)

    for name in (
        "ix_ip_deadline_incident_verifier",
        "ix_ip_deadline_incident_resolver",
        "ix_ip_deadline_incident_impact_completed_actor",
        "ix_ip_deadline_incident_creator",
    ):
        op.drop_index(name, table_name=INCIDENT_TABLE)

    with op.batch_alter_table(INCIDENT_TABLE) as batch:
        for name in (
            "fk_ip_deadline_incident_verifier_company",
            "fk_ip_deadline_incident_resolver_company",
            "fk_ip_deadline_incident_impact_actor_company",
            "fk_ip_deadline_incident_creator_company",
        ):
            batch.drop_constraint(name, type_="foreignkey")
        for name in (
            "ck_ip_deadline_incident_terminal_evidence",
            "ck_ip_deadline_incident_defect_scope",
            "ck_ip_deadline_incident_status",
        ):
            batch.drop_constraint(name, type_="check")
        batch.drop_constraint("uq_ip_deadline_incident_id_company", type_="unique")
        batch.drop_constraint("fk_ip_deadline_incident_docket_company", type_="foreignkey")
        batch.create_foreign_key(
            "fk_ip_deadline_incident_docket_company",
            "ip_docket_records",
            ["docket_id", "company_id"],
            ["id", "company_id"],
            ondelete="CASCADE",
        )
        for column in (
            "created_by_membership_id",
            "version",
            "resolved_by_membership_id",
            "resolved_at",
            "resolution_evidence_reference",
            "prevention_verified_at",
            "preventive_action",
            "root_cause",
            "impact_scan_completed_by_membership_id",
            "impact_scan_completed_at",
            "defect_fingerprint_sha256",
            "defect_scope",
            "preservation_manifest_sha256",
            "evidence_snapshot_json",
        ):
            batch.drop_column(column)
