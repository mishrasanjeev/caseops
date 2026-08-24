"""Add IP registry evidence, reconciliation, and court-reference links.

Revision ID: 20260824_0002
Revises: 20260824_0001
Create Date: 2026-08-24

IPLF-051 adds only IP-office register evidence that the existing court-shaped
TrackedCase owner cannot represent. Court updates remain canonical in the
tracked-case tables and are linked by reference. Registry snapshots are
append-only and corrections create a superseding row.

MIGRATION-LOCK-RISK: acknowledged: additive tables plus one composite unique
constraint on tracked_cases; PostgreSQL lock timeout is five seconds.
MIGRATION-ROLLBACK: downgrade is refused once registry evidence exists because
dropping immutable legal-source history would be destructive.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260824_0002"
down_revision = "20260824_0001"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def _create_snapshot_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                """
                CREATE OR REPLACE FUNCTION caseops_ip_registry_snapshot_immutable()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'IP registry snapshots are append-only';
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_registry_snapshots_immutable
                BEFORE UPDATE OR DELETE ON ip_registry_snapshots
                FOR EACH ROW EXECUTE FUNCTION caseops_ip_registry_snapshot_immutable()
                """
            )
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_registry_snapshots_immutable_update
                BEFORE UPDATE ON ip_registry_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'IP registry snapshots are append-only');
                END
                """
            )
        )
        op.execute(
            sa.text(
                """
                CREATE TRIGGER trg_ip_registry_snapshots_immutable_delete
                BEFORE DELETE ON ip_registry_snapshots
                BEGIN
                    SELECT RAISE(ABORT, 'IP registry snapshots are append-only');
                END
                """
            )
        )


def _drop_snapshot_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_ip_registry_snapshots_immutable ON ip_registry_snapshots"
        )
        op.execute("DROP FUNCTION IF EXISTS caseops_ip_registry_snapshot_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ip_registry_snapshots_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_ip_registry_snapshots_immutable_delete")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    with op.batch_alter_table("tracked_cases") as batch:
        batch.create_unique_constraint(
            "uq_tracked_case_id_company",
            ["id", "company_id"],
        )

    op.create_table(
        "ip_registry_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("proceeding_id", sa.String(36), nullable=True),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("identifier_kind", sa.String(40), nullable=False),
        sa.Column("raw_identifier", sa.String(160), nullable=False),
        sa.Column("normalized_identifier", sa.String(160), nullable=False),
        sa.Column("source_url", sa.String(800), nullable=False),
        sa.Column("match_status", sa.String(24), nullable=False, server_default="candidate"),
        sa.Column("match_confidence", sa.Numeric(5, 4), nullable=False, server_default="0"),
        sa.Column("match_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("accepted_state_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("terms_version", sa.String(80), nullable=True),
        sa.Column("capability_version", sa.String(80), nullable=False),
        sa.Column(
            "freshness_status",
            sa.String(24),
            nullable=False,
            server_default="never_succeeded",
        ),
        sa.Column("last_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_successful_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_snapshot_id", sa.String(36), nullable=True),
        sa.Column("last_normalized_hash", sa.String(64), nullable=True),
        sa.Column("last_error_redacted", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_registry_link_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_registry_link_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_registry_link_proceeding_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_registry_link_creator_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(application_id IS NOT NULL AND proceeding_id IS NULL) OR "
            "(application_id IS NULL AND proceeding_id IS NOT NULL)",
            name="ck_ip_registry_link_single_target",
        ),
        sa.CheckConstraint(
            "match_status IN ('candidate', 'confirmed', 'mismatch', 'retired')",
            name="ck_ip_registry_link_match_status",
        ),
        sa.CheckConstraint(
            "freshness_status IN ('never_succeeded', 'current', 'stale', 'failed', 'blocked')",
            name="ck_ip_registry_link_freshness_status",
        ),
        sa.CheckConstraint(
            "match_confidence >= 0 AND match_confidence <= 1",
            name="ck_ip_registry_link_confidence",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_registry_link_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "docket_id",
            "provider_key",
            "office",
            "jurisdiction",
            "identifier_kind",
            "normalized_identifier",
            name="uq_ip_registry_link_identity",
        ),
    )
    op.create_index("ix_ip_registry_links_docket_id", "ip_registry_links", ["docket_id"])
    op.create_index("ix_ip_registry_links_application_id", "ip_registry_links", ["application_id"])
    op.create_index("ix_ip_registry_links_proceeding_id", "ip_registry_links", ["proceeding_id"])
    op.create_index("ix_ip_registry_links_provider_key", "ip_registry_links", ["provider_key"])
    op.create_index(
        "ix_ip_registry_links_normalized_identifier", "ip_registry_links", ["normalized_identifier"]
    )
    op.create_index(
        "ix_ip_registry_links_last_snapshot_id", "ip_registry_links", ["last_snapshot_id"]
    )
    op.create_index(
        "ix_ip_registry_links_company_freshness",
        "ip_registry_links",
        ["company_id", "freshness_status"],
    )

    op.create_table(
        "ip_registry_sync_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("link_id", sa.String(36), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("operation_kind", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("response_class", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("external_call", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("replay_of_attempt_id", sa.String(36), nullable=True),
        sa.Column("cost_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(8), nullable=False, server_default="INR"),
        sa.Column("error_redacted", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("requested_by_membership_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["link_id", "company_id"],
            ["ip_registry_links.id", "ip_registry_links.company_id"],
            name="fk_ip_registry_attempt_link_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_registry_attempt_requester_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replay_of_attempt_id", "company_id"],
            ["ip_registry_sync_attempts.id", "ip_registry_sync_attempts.company_id"],
            name="fk_ip_registry_attempt_replay_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'no_change', 'failed', 'blocked')",
            name="ck_ip_registry_attempt_status",
        ),
        sa.CheckConstraint(
            "response_class IN ('success', 'no_change', 'authentication', 'rate_limit', "
            "'parse_error', 'provider_outage', 'configuration', 'policy', 'unknown')",
            name="ck_ip_registry_attempt_response_class",
        ),
        sa.CheckConstraint("attempts > 0", name="ck_ip_registry_attempt_count"),
        sa.CheckConstraint("cost_minor >= 0", name="ck_ip_registry_attempt_cost"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_registry_attempt_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "link_id",
            "idempotency_key",
            name="uq_ip_registry_attempt_idempotency",
        ),
        sa.UniqueConstraint(
            "company_id",
            "correlation_id",
            name="uq_ip_registry_attempt_correlation",
        ),
    )
    op.create_index(
        "ix_ip_registry_sync_attempts_link_id", "ip_registry_sync_attempts", ["link_id"]
    )
    op.create_index(
        "ix_ip_registry_sync_attempts_provider_key", "ip_registry_sync_attempts", ["provider_key"]
    )
    op.create_index(
        "ix_ip_registry_sync_attempts_replay_of_attempt_id",
        "ip_registry_sync_attempts",
        ["replay_of_attempt_id"],
    )
    op.create_index(
        "ix_ip_registry_attempts_company_status",
        "ip_registry_sync_attempts",
        ["company_id", "status", "created_at"],
    )

    op.create_table(
        "ip_registry_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("link_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), nullable=False),
        sa.Column("source_url", sa.String(800), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attribution_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("terms_version", sa.String(80), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=False),
        sa.Column("normalized_sha256", sa.String(64), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("normalized_json", sa.JSON(), nullable=False),
        sa.Column("supersedes_snapshot_id", sa.String(36), nullable=True),
        sa.Column("correction_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["link_id", "company_id"],
            ["ip_registry_links.id", "ip_registry_links.company_id"],
            name="fk_ip_registry_snapshot_link_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id", "company_id"],
            ["ip_registry_sync_attempts.id", "ip_registry_sync_attempts.company_id"],
            name="fk_ip_registry_snapshot_attempt_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_ip_registry_snapshot_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "length(raw_sha256) = 64 AND length(normalized_sha256) = 64",
            name="ck_ip_registry_snapshot_hashes",
        ),
        sa.CheckConstraint(
            "supersedes_snapshot_id IS NULL OR supersedes_snapshot_id <> id",
            name="ck_ip_registry_snapshot_supersedes_not_self",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_registry_snapshot_id_company"),
        sa.UniqueConstraint("attempt_id", name="uq_ip_registry_snapshot_attempt"),
        sa.UniqueConstraint(
            "company_id",
            "supersedes_snapshot_id",
            name="uq_ip_registry_snapshot_single_successor",
        ),
        sa.UniqueConstraint(
            "company_id",
            "link_id",
            "normalized_sha256",
            "supersedes_snapshot_id",
            name="uq_ip_registry_snapshot_content_lineage",
        ),
    )
    op.create_index("ix_ip_registry_snapshots_link_id", "ip_registry_snapshots", ["link_id"])
    op.create_index("ix_ip_registry_snapshots_attempt_id", "ip_registry_snapshots", ["attempt_id"])
    op.create_index("ix_ip_registry_snapshots_raw_sha256", "ip_registry_snapshots", ["raw_sha256"])
    op.create_index(
        "ix_ip_registry_snapshots_normalized_sha256", "ip_registry_snapshots", ["normalized_sha256"]
    )
    op.create_index(
        "ix_ip_registry_snapshots_supersedes_snapshot_id",
        "ip_registry_snapshots",
        ["supersedes_snapshot_id"],
    )
    op.create_index(
        "ix_ip_registry_snapshots_company_link_created",
        "ip_registry_snapshots",
        ["company_id", "link_id", "created_at"],
    )
    _create_snapshot_guard(bind)

    op.create_table(
        "ip_registry_diffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("field_path", sa.String(500), nullable=False),
        sa.Column("change_kind", sa.String(16), nullable=False),
        sa.Column("before_value_json", sa.JSON(), nullable=True),
        sa.Column("after_value_json", sa.JSON(), nullable=True),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("risk_reasons_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("resolution_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("resolution_reason", sa.String(1000), nullable=True),
        sa.Column("mapped_field_path", sa.String(500), nullable=True),
        sa.Column("resolved_by_membership_id", sa.String(36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("emitted_event_id", sa.String(36), nullable=True),
        sa.Column(
            "deadline_recalculation_state",
            sa.String(24),
            nullable=False,
            server_default="not_applicable",
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["snapshot_id", "company_id"],
            ["ip_registry_snapshots.id", "ip_registry_snapshots.company_id"],
            name="fk_ip_registry_diff_snapshot_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_registry_diff_resolver_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["emitted_event_id", "company_id"],
            ["ip_docket_events.id", "ip_docket_events.company_id"],
            name="fk_ip_registry_diff_event_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "change_kind IN ('added', 'changed', 'removed')",
            name="ck_ip_registry_diff_change_kind",
        ),
        sa.CheckConstraint("risk_level IN ('low', 'high')", name="ck_ip_registry_diff_risk"),
        sa.CheckConstraint(
            "resolution_status IN ('pending', 'accepted', 'rejected', 'mapped', 'deferred')",
            name="ck_ip_registry_diff_resolution",
        ),
        sa.CheckConstraint(
            "deadline_recalculation_state IN ('not_applicable', 'required', 'proposed', 'blocked')",
            name="ck_ip_registry_diff_deadline_state",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_registry_diff_version"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_registry_diff_id_company"),
        sa.UniqueConstraint("snapshot_id", "field_path", name="uq_ip_registry_diff_field"),
    )
    op.create_index("ix_ip_registry_diffs_snapshot_id", "ip_registry_diffs", ["snapshot_id"])
    op.create_index(
        "ix_ip_registry_diffs_emitted_event_id", "ip_registry_diffs", ["emitted_event_id"]
    )
    op.create_index(
        "ix_ip_registry_diffs_company_resolution",
        "ip_registry_diffs",
        ["company_id", "resolution_status", "risk_level"],
    )

    op.create_table(
        "ip_tracked_case_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("proceeding_id", sa.String(36), nullable=False),
        sa.Column("tracked_case_id", sa.String(36), nullable=False),
        sa.Column("link_status", sa.String(24), nullable=False, server_default="active"),
        sa.Column("purpose", sa.String(120), nullable=False),
        sa.Column("evidence_reference", sa.String(800), nullable=False),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_tracked_case_link_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            name="fk_ip_tracked_case_link_proceeding_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tracked_case_id", "company_id"],
            ["tracked_cases.id", "tracked_cases.company_id"],
            name="fk_ip_tracked_case_link_case_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_tracked_case_link_creator_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "link_status IN ('active', 'mismatch', 'retired')",
            name="ck_ip_tracked_case_link_status",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_tracked_case_link_id_company"),
        sa.UniqueConstraint(
            "company_id",
            "docket_id",
            "proceeding_id",
            "tracked_case_id",
            name="uq_ip_tracked_case_reference",
        ),
    )
    op.create_index("ix_ip_tracked_case_links_docket_id", "ip_tracked_case_links", ["docket_id"])
    op.create_index(
        "ix_ip_tracked_case_links_proceeding_id", "ip_tracked_case_links", ["proceeding_id"]
    )
    op.create_index(
        "ix_ip_tracked_case_links_tracked_case_id", "ip_tracked_case_links", ["tracked_case_id"]
    )
    op.create_index(
        "ix_ip_tracked_case_links_company_docket",
        "ip_tracked_case_links",
        ["company_id", "docket_id", "link_status"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    evidence_count = bind.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM ip_registry_snapshots) + "
            "(SELECT count(*) FROM ip_registry_diffs) + "
            "(SELECT count(*) FROM ip_tracked_case_links)"
        )
    ).scalar_one()
    if evidence_count:
        raise RuntimeError(
            "refusing to downgrade: immutable IP registry or court-reference evidence exists"
        )
    op.drop_table("ip_tracked_case_links")
    op.drop_table("ip_registry_diffs")
    _drop_snapshot_guard(bind)
    op.drop_table("ip_registry_snapshots")
    op.drop_table("ip_registry_sync_attempts")
    op.drop_table("ip_registry_links")
    with op.batch_alter_table("tracked_cases") as batch:
        batch.drop_constraint("uq_tracked_case_id_company", type_="unique")
