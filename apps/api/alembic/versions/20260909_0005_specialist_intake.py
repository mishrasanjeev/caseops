"""Restricted specialist intake, version history and source observations.

Revision ID: 20260909_0005
Revises: 20260908_0001 (parent integration must linearize reserved revisions)
DATA-GOVERNANCE-MAP: pending parent integration; see other-ip-domains evidence.
MIGRATION-LOCK-RISK: additive tables and canonical obligation scope index; no backfill.
MIGRATION-ROLLBACK: refuses to destroy retained specialist evidence.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0005"
down_revision = "20260909_0004"
branch_labels = None
depends_on = None

WORKFLOW_TABLES = (
    "ip_specialist_workflows",
    "ip_specialist_workflow_versions",
    "ip_specialist_workflow_sources",
    "ip_specialist_obligation_links",
    "ip_specialist_obligation_events",
)
IMMUTABLE_TABLES = (
    "ip_specialist_versions",
    "ip_specialist_observations",
    "ip_specialist_workflow_versions",
    "ip_specialist_workflow_sources",
    "ip_specialist_obligation_links",
    "ip_specialist_obligation_events",
)


def _workflow_tables():
    op.create_index(
        "uq_ip_related_obligation_scope",
        "ip_related_right_obligations",
        ["id", "company_id", "docket_id"],
        unique=True,
    )
    op.create_table(
        "ip_specialist_workflows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("proceeding_id", sa.String(36)),
        sa.Column("title_interest_id", sa.String(36)),
        sa.ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proceeding_id", "company_id"],
            ["ip_proceedings.id", "ip_proceedings.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["title_interest_id", "company_id"],
            ["ip_title_interests.id", "ip_title_interests.company_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_specialist_workflow_company"),
        sa.CheckConstraint("version > 0", name="ck_specialist_workflow_version"),
        sa.CheckConstraint(
            "kind IN ('source_set','design_application','copyright_registration',"
            "'rights_claim','licence','proceeding','layout_application')",
            name="ck_specialist_workflow_kind",
        ),
    )
    for name, columns in (
        ("record", ["record_id", "company_id", "id"]),
        ("proceeding", ["proceeding_id", "company_id"]),
        ("interest", ["title_interest_id", "company_id"]),
    ):
        op.create_index(f"ix_specialist_workflow_{name}", "ip_specialist_workflows", columns)
    op.create_table(
        "ip_specialist_workflow_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("facts_sha256", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["workflow_id", "company_id"],
            ["ip_specialist_workflows.id", "ip_specialist_workflows.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "workflow_id", "company_id", "version", name="uq_specialist_workflow_revision"
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_specialist_workflow_version_company"),
        sa.CheckConstraint("version > 0", name="ck_specialist_workflow_revision"),
        sa.CheckConstraint("length(facts_sha256) = 64", name="ck_specialist_workflow_hash"),
    )
    op.create_index(
        "ix_specialist_workflow_version_actor",
        "ip_specialist_workflow_versions",
        ["actor_id", "company_id"],
    )
    op.create_table(
        "ip_specialist_workflow_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.String(500), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id", "company_id"],
            ["ip_specialist_workflow_versions.id", "ip_specialist_workflow_versions.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_specialist_workflow_source_ordinal"),
        sa.CheckConstraint(
            "ordinal >= 0 AND ordinal < 52", name="ck_specialist_workflow_source_bound"
        ),
        sa.CheckConstraint(
            "length(content_sha256) = 64", name="ck_specialist_workflow_source_hash"
        ),
    )
    op.create_index(
        "ix_specialist_workflow_source_revision",
        "ip_specialist_workflow_sources",
        ["revision_id", "company_id"],
    )
    op.create_index(
        "ix_specialist_workflow_source_document",
        "ip_specialist_workflow_sources",
        ["document_version_id", "company_id", "document_id"],
    )
    op.create_table(
        "ip_specialist_obligation_links",
        sa.Column("obligation_id", sa.String(36), primary_key=True),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("workflow_id", sa.String(36), nullable=False),
        sa.Column("task_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.String(500), nullable=False),
        sa.Column("cost_item_id", sa.String(36)),
        sa.ForeignKeyConstraint(
            ["workflow_id", "company_id"],
            ["ip_specialist_workflows.id", "ip_specialist_workflows.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["obligation_id", "company_id", "docket_id"],
            [
                "ip_related_right_obligations.id",
                "ip_related_right_obligations.company_id",
                "ip_related_right_obligations.docket_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["task_id", "company_id"],
            ["matter_tasks.id", "matter_tasks.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "obligation_id", "company_id", "docket_id", name="uq_specialist_obligation_scope"
        ),
    )
    for name, columns in (
        ("workflow", ["workflow_id", "company_id"]),
        ("task", ["task_id", "company_id"]),
        ("source", ["document_version_id", "company_id", "document_id"]),
        ("cost", ["cost_item_id", "company_id", "docket_id"]),
    ):
        op.create_index(
            f"ix_specialist_obligation_{name}", "ip_specialist_obligation_links", columns
        )
    op.create_table(
        "ip_specialist_obligation_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("obligation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("document_version_id", sa.String(36), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.String(500), nullable=False),
        sa.Column("cost_item_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["obligation_id", "company_id", "docket_id"],
            [
                "ip_specialist_obligation_links.obligation_id",
                "ip_specialist_obligation_links.company_id",
                "ip_specialist_obligation_links.docket_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["document_version_id", "company_id", "document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cost_item_id", "company_id", "docket_id"],
            ["ip_cost_items.id", "ip_cost_items.company_id", "ip_cost_items.docket_id"],
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "action IN ('complete','cancel','notice_recorded')",
            name="ck_specialist_obligation_action",
        ),
    )
    for name, columns in (
        ("parent", ["obligation_id", "company_id", "docket_id", "id"]),
        ("actor", ["actor_id", "company_id"]),
        ("source", ["document_version_id", "company_id", "document_id"]),
        ("cost", ["cost_item_id", "company_id", "docket_id"]),
    ):
        op.create_index(
            f"ix_specialist_obligation_event_{name}", "ip_specialist_obligation_events", columns
        )


def upgrade():
    op.create_table(
        "ip_specialist_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("docket_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("client_id", sa.String(36), nullable=False),
        sa.Column("domain", sa.String(40), nullable=False),
        sa.Column("contract_version", sa.String(64), nullable=False),
        sa.Column("observation_sequence", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id", "company_id"],
            ["ip_assets.id", "ip_assets.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id", "company_id"], ["clients.id", "clients.company_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint("id", "company_id", name="uq_specialist_record_company"),
        sa.UniqueConstraint("docket_id", "company_id", name="uq_specialist_docket_company"),
        sa.UniqueConstraint("asset_id", "company_id", name="uq_specialist_asset_company"),
        sa.CheckConstraint(
            "domain IN ('design','copyright','domain_name','licensing','enforcement',"
            "'geographical_indication','plant_variety','semiconductor_layout',"
            "'trade_secret','customs_enforcement')",
            name="ck_specialist_domain",
        ),
        sa.CheckConstraint("observation_sequence >= 0", name="ck_specialist_sequence"),
    )
    op.create_index(
        "ix_specialist_domain_cursor", "ip_specialist_records", ["company_id", "domain", "id"]
    )
    op.create_index("ix_specialist_client", "ip_specialist_records", ["client_id", "company_id"])
    op.create_table(
        "ip_specialist_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("facts_json", sa.JSON(), nullable=False),
        sa.Column("facts_sha256", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(500), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("record_id", "company_id", "version", name="uq_specialist_version"),
        sa.CheckConstraint("version > 0", name="ck_specialist_version_positive"),
        sa.CheckConstraint("length(facts_sha256) = 64", name="ck_specialist_facts_hash"),
    )
    op.create_index(
        "ix_specialist_version_actor", "ip_specialist_versions", ["actor_id", "company_id"]
    )
    op.create_table(
        "ip_specialist_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("company_id", sa.String(36), nullable=False),
        sa.Column("record_id", sa.String(36), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(80), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("account", sa.Text(), nullable=False),
        sa.Column("source_version_id", sa.String(36), nullable=False),
        sa.Column("source_document_id", sa.String(36), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("locator", sa.String(500), nullable=False),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id", "company_id"],
            ["ip_specialist_records.id", "ip_specialist_records.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id", "company_id", "source_document_id"],
            [
                "ip_document_versions.id",
                "ip_document_versions.company_id",
                "ip_document_versions.document_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id", "company_id", "record_id"],
            [
                "ip_specialist_observations.id",
                "ip_specialist_observations.company_id",
                "ip_specialist_observations.record_id",
            ],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "id", "company_id", "record_id", name="uq_specialist_observation_identity"
        ),
        sa.UniqueConstraint(
            "record_id", "company_id", "sequence", name="uq_specialist_observation_sequence"
        ),
        sa.UniqueConstraint(
            "supersedes_id", "company_id", name="uq_specialist_observation_successor"
        ),
        sa.CheckConstraint("sequence > 0", name="ck_specialist_observation_sequence"),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id <> id", name="ck_specialist_not_self"
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_specialist_source_hash"),
    )
    op.create_index(
        "ix_specialist_observation_actor", "ip_specialist_observations", ["actor_id", "company_id"]
    )
    op.create_index(
        "ix_specialist_observation_prior",
        "ip_specialist_observations",
        ["supersedes_id", "company_id", "record_id"],
    )
    op.create_index(
        "ix_specialist_observation_source",
        "ip_specialist_observations",
        ["source_version_id", "company_id", "source_document_id"],
    )
    _workflow_tables()
    # Guard immutable evidence at the database boundary as well as the API.
    bind = op.get_bind()
    for table in IMMUTABLE_TABLES:
        if bind.dialect.name == "postgresql":
            op.execute(
                sa.text(
                    f"CREATE FUNCTION {table}_immutable() RETURNS trigger LANGUAGE plpgsql "
                    "AS $$ BEGIN RAISE EXCEPTION 'Specialist evidence is immutable'; END $$"
                )
            )
            op.execute(
                sa.text(
                    f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                    f"FOR EACH ROW EXECUTE FUNCTION {table}_immutable()"
                )
            )
        elif bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    sa.text(
                        f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'Specialist evidence is immutable'); END"
                    )
                )


def downgrade():
    bind = op.get_bind()
    for table in ("ip_specialist_records", *IMMUTABLE_TABLES, "ip_specialist_workflows"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Retained specialist evidence prevents destructive downgrade.")
    for table in (
        *reversed(WORKFLOW_TABLES),
        "ip_specialist_observations",
        "ip_specialist_versions",
        "ip_specialist_records",
    ):
        op.drop_table(table)
        if bind.dialect.name == "postgresql" and table in IMMUTABLE_TABLES:
            op.execute(sa.text(f"DROP FUNCTION {table}_immutable()"))
    op.drop_index("uq_ip_related_obligation_scope", table_name="ip_related_right_obligations")
