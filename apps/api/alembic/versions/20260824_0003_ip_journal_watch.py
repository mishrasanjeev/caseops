"""Add journal ingestion, watch profiles, hits, and canonical handoff evidence.

Revision ID: 20260824_0003
Revises: 20260824_0002
Create Date: 2026-08-24

IPLF-052 owns journal/watch source and review evidence only. Tasks, deadlines,
Matters, opposition proceedings, notifications, and provider controls remain
with their existing canonical owners and are referenced by handoff rows.

MIGRATION-LOCK-RISK: acknowledged: additive tables only; PostgreSQL lock
timeout is five seconds.
MIGRATION-ROLLBACK: downgrade refuses after journal/watch evidence exists.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260824_0003"
down_revision = "20260824_0002"
branch_labels = None
depends_on = None

# DATA-GOVERNANCE-MAP: updated


def _create_publication_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text("""
            CREATE OR REPLACE FUNCTION caseops_ip_journal_publication_immutable()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'IP journal publications are append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        )
        op.execute(
            sa.text("""
            CREATE TRIGGER trg_ip_journal_publications_immutable
            BEFORE UPDATE OR DELETE ON ip_journal_publications
            FOR EACH ROW EXECUTE FUNCTION caseops_ip_journal_publication_immutable()
        """)
        )
    elif bind.dialect.name == "sqlite":
        op.execute(
            sa.text("""
            CREATE TRIGGER trg_ip_journal_publications_immutable_update
            BEFORE UPDATE ON ip_journal_publications
            BEGIN
                SELECT RAISE(ABORT, 'IP journal publications are append-only');
            END
        """)
        )
        op.execute(
            sa.text("""
            CREATE TRIGGER trg_ip_journal_publications_immutable_delete
            BEFORE DELETE ON ip_journal_publications
            BEGIN
                SELECT RAISE(ABORT, 'IP journal publications are append-only');
            END
        """)
        )


def _drop_publication_guard(bind: sa.Connection) -> None:
    if bind.dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS trg_ip_journal_publications_immutable "
            "ON ip_journal_publications"
        )
        op.execute("DROP FUNCTION IF EXISTS caseops_ip_journal_publication_immutable()")
    elif bind.dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_ip_journal_publications_immutable_update")
        op.execute("DROP TRIGGER IF EXISTS trg_ip_journal_publications_immutable_delete")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("SET LOCAL lock_timeout = '5s'"))

    op.create_table(
        "ip_journal_publications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("application_id", sa.String(36), nullable=True),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("journal_number", sa.String(80), nullable=False),
        sa.Column("journal_date", sa.Date(), nullable=False),
        sa.Column("publication_kind", sa.String(24), nullable=False),
        sa.Column("application_number", sa.String(160), nullable=False),
        sa.Column("mark_text", sa.String(500), nullable=True),
        sa.Column("device_reference", sa.String(800), nullable=True),
        sa.Column("proprietor_name", sa.String(500), nullable=True),
        sa.Column("office", sa.String(80), nullable=False),
        sa.Column("jurisdiction", sa.String(40), nullable=False),
        sa.Column("class_numbers_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("goods_services_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "publication_scope_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("source_url", sa.String(800), nullable=False),
        sa.Column("source_page", sa.String(80), nullable=True),
        sa.Column("source_status", sa.String(24), nullable=False),
        sa.Column("source_retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("attribution_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("raw_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("supersedes_publication_id", sa.String(36), nullable=True),
        sa.Column("correction_reason", sa.String(1000), nullable=True),
        sa.Column("ingestion_delay_hours", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["application_id", "company_id"],
            ["trademark_applications.id", "trademark_applications.company_id"],
            name="fk_ip_journal_publication_application_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_publication_id", "company_id"],
            ["ip_journal_publications.id", "ip_journal_publications.company_id"],
            name="fk_ip_journal_publication_supersedes_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "publication_kind IN ('advertisement', 'correction', 'readvertisement')",
            name="ck_ip_journal_publication_kind",
        ),
        sa.CheckConstraint(
            "source_status IN ('available', 'unavailable', 'stale')",
            name="ck_ip_journal_publication_source_status",
        ),
        sa.CheckConstraint(
            "supersedes_publication_id IS NULL OR publication_kind <> 'advertisement'",
            name="ck_ip_journal_publication_supersession_kind",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_journal_publication_id_company"),
        sa.UniqueConstraint(
            "company_id", "source_fingerprint", name="uq_ip_journal_publication_fingerprint"
        ),
    )
    op.create_index(
        "ix_ip_journal_publications_company_date",
        "ip_journal_publications",
        ["company_id", "journal_date", "created_at"],
    )
    op.create_index(
        "ix_ip_journal_publications_company_application",
        "ip_journal_publications",
        ["company_id", "application_number"],
    )
    op.create_index(
        "ix_ip_journal_publications_application_id", "ip_journal_publications", ["application_id"]
    )
    op.create_index(
        "ix_ip_journal_publications_supersedes_publication_id",
        "ip_journal_publications",
        ["supersedes_publication_id"],
    )
    _create_publication_guard(bind)

    op.create_table(
        "ip_journal_ingestion_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=False),
        sa.Column("idempotency_key", sa.String(120), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("external_call", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("cost_minor", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("publications_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("publications_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hits_created", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_hits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "publication_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("hit_ids_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("stale_source_alert", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_redacted", sa.String(1000), nullable=True),
        sa.Column("requested_by_membership_id", sa.String(36), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["requested_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_journal_ingestion_actor_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'succeeded', 'failed', 'paused_cost_quota')",
            name="ck_ip_journal_ingestion_status",
        ),
        sa.CheckConstraint(
            "length(request_sha256) = 64",
            name="ck_ip_journal_ingestion_request_sha256",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_journal_ingestion_id_company"),
        sa.UniqueConstraint(
            "company_id", "idempotency_key", name="uq_ip_journal_ingestion_idempotency"
        ),
    )
    op.create_index(
        "ix_ip_journal_ingestion_company_created",
        "ip_journal_ingestion_runs",
        ["company_id", "created_at"],
    )

    op.create_table(
        "ip_watch_profiles",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("provider_key", sa.String(80), nullable=False, server_default="manual-journal"),
        sa.Column("word_terms_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("phonetic_terms_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "device_references_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("class_numbers_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "proprietor_terms_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("jurisdictions_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("frequency", sa.String(24), nullable=False),
        sa.Column(
            "recipient_membership_ids_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("max_cost_minor_per_period", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spent_cost_minor_in_period", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_currency", sa.String(3), nullable=False, server_default="INR"),
        sa.Column("poll_status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("pause_reason", sa.String(500), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("criteria_version", sa.String(80), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_ip_watch_profile_docket_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_watch_profile_creator_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "frequency IN ('publication', 'daily', 'weekly', 'monthly')",
            name="ck_ip_watch_profile_frequency",
        ),
        sa.CheckConstraint(
            "poll_status IN ('active', 'paused', 'paused_cost_quota', 'disabled')",
            name="ck_ip_watch_profile_poll_status",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_watch_profile_version"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_watch_profile_id_company"),
    )
    op.create_index("ix_ip_watch_profiles_docket_id", "ip_watch_profiles", ["docket_id"])
    op.create_index(
        "ix_ip_watch_profiles_company_poll",
        "ip_watch_profiles",
        ["company_id", "poll_status", "next_poll_at"],
    )

    op.create_table(
        "ip_watch_hits",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("publication_id", sa.String(36), nullable=False),
        sa.Column("duplicate_of_hit_id", sa.String(36), nullable=True),
        sa.Column("compared_mark_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("candidate_mark_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("classes_goods_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "similarity_evidence_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("ai_advisory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("advisory_notice", sa.String(500), nullable=False),
        sa.Column("source_url", sa.String(800), nullable=False),
        sa.Column("source_status", sa.String(24), nullable=False),
        sa.Column(
            "source_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("hit_date", sa.Date(), nullable=False),
        sa.Column("stale_source_alert", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "deadline_confirmation_state",
            sa.String(32),
            nullable=False,
            server_default="pending_confirmation",
        ),
        sa.Column("disposition", sa.String(32), nullable=False, server_default="new"),
        sa.Column("disposition_reason", sa.String(2000), nullable=True),
        sa.Column("reviewed_by_membership_id", sa.String(36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "reviewer_decision_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["profile_id", "company_id"],
            ["ip_watch_profiles.id", "ip_watch_profiles.company_id"],
            name="fk_ip_watch_hit_profile_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["publication_id", "company_id"],
            ["ip_journal_publications.id", "ip_journal_publications.company_id"],
            name="fk_ip_watch_hit_publication_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["duplicate_of_hit_id", "company_id"],
            ["ip_watch_hits.id", "ip_watch_hits.company_id"],
            name="fk_ip_watch_hit_duplicate_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_watch_hit_reviewer_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "disposition IN ('new', 'reviewing', 'relevant', 'not_relevant', 'monitor', "
            "'client_instruction', 'enforcement_opened', 'closed')",
            name="ck_ip_watch_hit_disposition",
        ),
        sa.CheckConstraint("version > 0", name="ck_ip_watch_hit_version"),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_watch_hit_id_company"),
        sa.UniqueConstraint("company_id", "profile_id", "publication_id", name="uq_ip_watch_hit"),
    )
    op.create_index("ix_ip_watch_hits_profile_id", "ip_watch_hits", ["profile_id"])
    op.create_index("ix_ip_watch_hits_publication_id", "ip_watch_hits", ["publication_id"])
    op.create_index(
        "ix_ip_watch_hits_duplicate_of_hit_id", "ip_watch_hits", ["duplicate_of_hit_id"]
    )
    op.create_index(
        "ix_ip_watch_hits_reviewed_by_membership_id", "ip_watch_hits", ["reviewed_by_membership_id"]
    )
    op.create_index(
        "ix_ip_watch_hits_company_disposition",
        "ip_watch_hits",
        ["company_id", "disposition", "hit_date"],
    )

    op.create_table(
        "ip_watch_handoffs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("hit_id", sa.String(36), nullable=False),
        sa.Column("handoff_kind", sa.String(40), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("target_type", sa.String(80), nullable=True),
        sa.Column("target_id", sa.String(36), nullable=True),
        sa.Column(
            "source_snapshot_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column(
            "reviewer_decision_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")
        ),
        sa.Column("request_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("error_redacted", sa.String(1000), nullable=True),
        sa.Column("created_by_membership_id", sa.String(36), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hit_id", "company_id"],
            ["ip_watch_hits.id", "ip_watch_hits.company_id"],
            name="fk_ip_watch_handoff_hit_company",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_ip_watch_handoff_actor_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "handoff_kind IN ('opposition', 'enforcement_matter', 'task', 'deadline', "
            "'client_report_item')",
            name="ck_ip_watch_handoff_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_ip_watch_handoff_status",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_ip_watch_handoff_id_company"),
        sa.UniqueConstraint(
            "company_id", "hit_id", "handoff_kind", name="uq_ip_watch_handoff_kind"
        ),
    )
    op.create_index("ix_ip_watch_handoffs_hit_id", "ip_watch_handoffs", ["hit_id"])


def downgrade() -> None:
    # MIGRATION-ROLLBACK: restore-forward: this destructive downgrade is permitted only
    # before any real journal/watch rows exist; shipped or data-bearing rollback uses a
    # forward repair or verified backup restore.
    bind = op.get_bind()
    evidence_count = bind.execute(
        sa.text(
            "SELECT (SELECT count(*) FROM ip_journal_publications) + "
            "(SELECT count(*) FROM ip_journal_ingestion_runs) + "
            "(SELECT count(*) FROM ip_watch_profiles) + "
            "(SELECT count(*) FROM ip_watch_hits) + "
            "(SELECT count(*) FROM ip_watch_handoffs)"
        )
    ).scalar_one()
    if evidence_count:
        raise RuntimeError("refusing to downgrade: immutable journal/watch evidence exists")
    op.drop_table("ip_watch_handoffs")
    op.drop_table("ip_watch_hits")
    op.drop_table("ip_watch_profiles")
    op.drop_table("ip_journal_ingestion_runs")
    _drop_publication_guard(bind)
    op.drop_table("ip_journal_publications")
