"""Retain immutable patent document manifests and sourced prosecution.

Revision ID: 20260909_0004
Revises: 20260909_0003
DATA-GOVERNANCE-MAP: docs/ip-implementation/DATA_GOVERNANCE_MAP.yaml
MIGRATION-LOCK-RISK: acknowledged: one constant-default integer on the patent
application table, then new empty tables and indexes; no corpus backfill.
MIGRATION-ROLLBACK: restore-forward when evidence exists; refusal precedes DDL.
"""

import hashlib

import sqlalchemy as sa

from alembic import op

revision = "20260909_0004"
down_revision = "20260909_0003"
branch_labels = None
depends_on = None

EVIDENCE = "ip_patent_evidence_versions"
DOCUMENTS = "ip_patent_evidence_documents"
EVENTS = "ip_patent_prosecution_events"
PROCEEDINGS = "ip_patent_proceeding_details"
PROCEEDING_EVENTS = "ip_patent_proceeding_events"
TABLES = (EVIDENCE, DOCUMENTS, EVENTS, PROCEEDINGS, PROCEEDING_EVENTS)


def _s(name, length=36, nullable=False):
    return sa.Column(name, sa.String(length), nullable=nullable)


def _fk(name, columns, target, targets):
    return sa.ForeignKeyConstraint(
        columns, [f"{target}.{value}" for value in targets], name=name, ondelete="RESTRICT"
    )


def _common(prefix):
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        _s("company_id"),
        _s("application_id"),
        _s("anchor_version_id"),
        sa.Column("anchor_version", sa.Integer(), nullable=False),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        _s("source_document_id"),
        _s("source_document_version_id"),
        _s("source_sha256", 64),
        _s("created_by_membership_id"),
        _s("reason", 1000),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        _fk(
            f"fk_patent_{prefix}_application",
            ["application_id", "company_id"],
            "ip_patent_applications",
            ["id", "company_id"],
        ),
        _fk(
            f"fk_patent_{prefix}_anchor",
            ["anchor_version_id", "company_id", "application_id"],
            "ip_patent_application_versions",
            ["id", "company_id", "application_id"],
        ),
        _fk(
            f"fk_patent_{prefix}_source",
            ["source_document_version_id", "company_id", "source_document_id"],
            "ip_document_versions",
            ["id", "company_id", "document_id"],
        ),
        _fk(
            f"fk_patent_{prefix}_actor",
            ["created_by_membership_id", "company_id"],
            "company_memberships",
            ["id", "company_id"],
        ),
        sa.UniqueConstraint(
            "company_id", "application_id", "sequence", name=f"uq_patent_{prefix}_sequence"
        ),
    ]


def _support_indexes(bind):
    inspector = sa.inspect(bind)
    for table in TABLES:
        candidates = [inspector.get_pk_constraint(table)["constrained_columns"]]
        candidates += [item["column_names"] for item in inspector.get_unique_constraints(table)]
        candidates += [item["column_names"] for item in inspector.get_indexes(table)]
        for fk in sorted(
            inspector.get_foreign_keys(table), key=lambda item: tuple(item["constrained_columns"])
        ):
            columns = fk["constrained_columns"]
            if any(set(candidate[: len(columns)]) == set(columns) for candidate in candidates):
                continue
            signature = f"{table}:{','.join(columns)}"
            digest = hashlib.sha1(signature.encode()).hexdigest()[:8]  # noqa: S324
            name = f"ix_fk_{table[:32]}_{'_'.join(columns)[:15]}_{digest}"
            op.create_index(name, table, columns)
            candidates.append(columns)


def upgrade():
    bind = op.get_bind()
    op.add_column(
        "ip_patent_applications",
        sa.Column("work_sequence", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        EVIDENCE,
        *_common("evidence"),
        _s("root_id"),
        _s("predecessor_id", nullable=True),
        sa.Column("edition", sa.Integer(), nullable=False),
        _s("title", 255),
        _s("document_kind", 32),
        _s("manifest_sha256", 64),
        sa.Column("document_count", sa.Integer(), nullable=False),
        _fk(
            "fk_patent_evidence_predecessor",
            ["predecessor_id", "company_id", "application_id"],
            EVIDENCE,
            ["id", "company_id", "application_id"],
        ),
        _fk(
            "fk_patent_evidence_root",
            ["root_id", "company_id", "application_id"],
            EVIDENCE,
            ["id", "company_id", "application_id"],
        ),
        sa.UniqueConstraint("id", "company_id", "application_id", name="uq_patent_evidence_owner"),
        sa.UniqueConstraint(
            "company_id", "application_id", "root_id", "edition", name="uq_patent_evidence_edition"
        ),
        sa.UniqueConstraint("company_id", "predecessor_id", name="uq_patent_evidence_successor"),
        sa.CheckConstraint(
            "sequence > 0 AND edition > 0 AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_evidence_versions",
        ),
        sa.CheckConstraint(
            "predecessor_id IS NULL OR predecessor_id <> id", name="ck_patent_evidence_no_self"
        ),
        sa.CheckConstraint(
            "(predecessor_id IS NULL AND root_id = id AND edition = 1) OR "
            "(predecessor_id IS NOT NULL AND root_id <> id AND edition > 1)",
            name="ck_patent_evidence_lineage",
        ),
        sa.CheckConstraint(
            "length(source_sha256) = 64 AND length(manifest_sha256) = 64",
            name="ck_patent_evidence_hashes",
        ),
        sa.CheckConstraint(
            "document_count >= 1 AND document_count <= 20", name="ck_patent_evidence_document_count"
        ),
        sa.CheckConstraint(
            "document_kind IN ('claims','specification','drawings','abstract','sequence_listing',"
            "'translation','amendment','response','filing_package')",
            name="ck_patent_evidence_kind",
        ),
    )
    op.create_index(
        "ix_patent_evidence_history",
        EVIDENCE,
        ["company_id", "application_id", "root_id", "sequence"],
    )
    op.create_table(
        DOCUMENTS,
        sa.Column("id", sa.String(36), primary_key=True),
        _s("company_id"),
        _s("application_id"),
        _s("evidence_id"),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        _s("document_kind", 32),
        _s("document_id"),
        _s("document_version_id"),
        _s("content_sha256", 64),
        _fk(
            "fk_patent_manifest_evidence",
            ["evidence_id", "company_id", "application_id"],
            EVIDENCE,
            ["id", "company_id", "application_id"],
        ),
        _fk(
            "fk_patent_manifest_document",
            ["document_version_id", "company_id", "document_id"],
            "ip_document_versions",
            ["id", "company_id", "document_id"],
        ),
        sa.UniqueConstraint(
            "company_id", "evidence_id", "ordinal", name="uq_patent_manifest_ordinal"
        ),
        sa.UniqueConstraint(
            "company_id", "evidence_id", "document_version_id", name="uq_patent_manifest_version"
        ),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 20", name="ck_patent_manifest_ordinal"),
        sa.CheckConstraint("length(content_sha256) = 64", name="ck_patent_manifest_hash"),
        sa.CheckConstraint(
            "document_kind IN ('claims','specification','drawings','abstract','sequence_listing',"
            "'translation','amendment','response')",
            name="ck_patent_manifest_kind",
        ),
    )
    op.create_table(
        EVENTS,
        *_common("prosecution"),
        _s("event_kind", 32),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        _s("evidence_id", nullable=True),
        _s("before_phase", 32),
        _s("after_phase", 32),
        sa.Column("impact_json", sa.JSON(), nullable=False),
        _s("exceptional_transition_reason", 1000, nullable=True),
        _fk(
            "fk_patent_prosecution_evidence",
            ["evidence_id", "company_id", "application_id"],
            EVIDENCE,
            ["id", "company_id", "application_id"],
        ),
        sa.CheckConstraint(
            "sequence > 0 AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_prosecution_versions",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_patent_prosecution_hash"),
        sa.CheckConstraint(
            "event_kind IN ('filing_preparation','filing','publication','examination_request',"
            "'office_action','response','hearing','amendment','grant','restoration')",
            name="ck_patent_prosecution_kind",
        ),
    )
    op.create_index(
        "ix_patent_prosecution_date", EVENTS, ["company_id", "application_id", "effective_on"]
    )
    op.create_table(
        PROCEEDINGS,
        sa.Column("id", sa.String(36), primary_key=True),
        _s("company_id"),
        _s("application_id"),
        _s("docket_id"),
        _s("title", 255),
        _s("counterparty", 255),
        sa.Column("lifecycle_version", sa.Integer(), nullable=False),
        _fk(
            "fk_patent_proceeding_owner",
            ["id", "company_id", "docket_id"],
            "ip_proceedings",
            ["id", "company_id", "docket_id"],
        ),
        _fk(
            "fk_patent_proceeding_application",
            ["application_id", "company_id"],
            "ip_patent_applications",
            ["id", "company_id"],
        ),
        sa.UniqueConstraint(
            "id", "company_id", "application_id", name="uq_patent_proceeding_owner"
        ),
        sa.CheckConstraint("lifecycle_version >= 0", name="ck_patent_proceeding_lifecycle"),
    )
    op.create_table(
        PROCEEDING_EVENTS,
        *_common("opposition"),
        _s("proceeding_id"),
        sa.Column("revision", sa.Integer(), nullable=False),
        _s("before_stage", 32, nullable=True),
        _s("after_stage", 32),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("effective_on", sa.Date(), nullable=False),
        _s("proceeding_number", 160, nullable=True),
        _s("evidence_id", nullable=True),
        _s("outcome", 1000, nullable=True),
        _s("exceptional_transition_reason", 1000, nullable=True),
        sa.Column("impact_json", sa.JSON(), nullable=True),
        _fk(
            "fk_patent_opposition_proceeding",
            ["proceeding_id", "company_id", "application_id"],
            PROCEEDINGS,
            ["id", "company_id", "application_id"],
        ),
        _fk(
            "fk_patent_opposition_evidence",
            ["evidence_id", "company_id", "application_id"],
            EVIDENCE,
            ["id", "company_id", "application_id"],
        ),
        sa.UniqueConstraint(
            "company_id", "proceeding_id", "revision", name="uq_patent_opposition_revision"
        ),
        sa.CheckConstraint(
            "revision > 0 AND revision <= 100 AND sequence > 0 "
            "AND anchor_version > 0 AND lifecycle_version >= 0",
            name="ck_patent_opposition_versions",
        ),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_patent_opposition_hash"),
        sa.CheckConstraint(
            "after_stage IN ('notice_recorded','response_preparation','response_filed',"
            "'hearing_recorded','decided','withdrawn')",
            name="ck_patent_opposition_stage",
        ),
        sa.CheckConstraint(
            "(revision = 1 AND before_stage IS NULL AND after_stage = 'notice_recorded') "
            "OR (revision > 1 AND before_stage IS NOT NULL)",
            name="ck_patent_opposition_initial",
        ),
        sa.CheckConstraint(
            "(after_stage IN ('decided','withdrawn') AND outcome IS NOT NULL) "
            "OR (after_stage NOT IN ('decided','withdrawn') AND outcome IS NULL)",
            name="ck_patent_opposition_outcome",
        ),
    )
    _support_indexes(bind)
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(f"""
            CREATE FUNCTION reject_patent_manifest_extra_document() RETURNS trigger AS $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM {EVIDENCE} e WHERE e.id = NEW.evidence_id
                    AND e.company_id = NEW.company_id AND e.application_id = NEW.application_id
                    AND NEW.ordinal < e.document_count) THEN
                    RAISE EXCEPTION 'Patent manifest is sealed' USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END; $$ LANGUAGE plpgsql""")
        )
        bind.execute(
            sa.text(
                f"CREATE TRIGGER trg_patent_manifest_sealed BEFORE INSERT ON {DOCUMENTS} "
                "FOR EACH ROW EXECUTE FUNCTION reject_patent_manifest_extra_document()"
            )
        )
        bind.execute(
            sa.text("""CREATE FUNCTION reject_patent_work_evidence_mutation() RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Patent work evidence is append-only' USING ERRCODE = '23514';
            END;
            $$ LANGUAGE plpgsql""")
        )
        for table in TABLES:
            bind.execute(
                sa.text(
                    f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                    "FOR EACH ROW EXECUTE FUNCTION reject_patent_work_evidence_mutation()"
                )
            )
    elif bind.dialect.name == "sqlite":
        bind.execute(
            sa.text(f"""CREATE TRIGGER trg_patent_manifest_sealed BEFORE INSERT ON {DOCUMENTS}
            WHEN NOT EXISTS (SELECT 1 FROM {EVIDENCE} e WHERE e.id = NEW.evidence_id
                AND e.company_id = NEW.company_id AND e.application_id = NEW.application_id
                AND NEW.ordinal < e.document_count)
            BEGIN SELECT RAISE(ABORT, 'Patent manifest is sealed'); END""")
        )
        for table in TABLES:
            for operation in ("UPDATE", "DELETE"):
                bind.execute(
                    sa.text(
                        f"CREATE TRIGGER trg_{table}_immutable_{operation.lower()} "
                        f"BEFORE {operation} ON {table} "
                        "BEGIN SELECT RAISE(ABORT, 'Patent work evidence is append-only'); END"
                    )
                )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(
            sa.text(
                f"LOCK TABLE ip_patent_applications, {', '.join(TABLES)} IN ACCESS EXCLUSIVE MODE"
            )
        )
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Patent work evidence exists; restore forward instead of deleting it."
            )
    for table in reversed(TABLES):
        op.drop_table(table)
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text("DROP FUNCTION reject_patent_work_evidence_mutation()"))
        bind.execute(sa.text("DROP FUNCTION reject_patent_manifest_extra_document()"))
    op.drop_column("ip_patent_applications", "work_sequence")
