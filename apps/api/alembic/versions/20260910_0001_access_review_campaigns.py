"""Independent record access-review evidence, never a parallel grant owner.

MIGRATION-LOCK-RISK: acknowledged - additive tables and bounded trigger DDL.
MIGRATION-ROLLBACK: populated review evidence refuses downgrade; roll forward.
Parent integrates shared model/data/event catalogs and linearizes predecessors.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260910_0001"
down_revision = "20260909_0005"
branch_labels = None
depends_on = None

C = "access_review_campaigns"
D = "access_review_decisions"
FROZEN = (
    "id",
    "company_id",
    "matter_id",
    "ip_docket_id",
    "title",
    "reason",
    "trigger",
    "creator_user_id",
    "snapshot_json",
    "snapshot_hash",
    "created_at",
)


def upgrade():
    pg = op.get_bind().dialect.name == "postgresql"
    if pg:
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        C,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("matter_id", sa.String(36)),
        sa.Column("ip_docket_id", sa.String(36)),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("trigger", sa.String(40), nullable=False),
        sa.Column("creator_user_id", sa.String(36), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("snapshot_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("id", "company_id", name="uq_access_review_company"),
        sa.ForeignKeyConstraint(
            ["matter_id", "company_id"],
            ["matters.id", "matters.company_id"],
            name="fk_review_matter_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["ip_docket_id", "company_id"],
            ["ip_docket_records.id", "ip_docket_records.company_id"],
            name="fk_review_ip_company",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "(matter_id IS NOT NULL AND ip_docket_id IS NULL) OR "
            "(matter_id IS NULL AND ip_docket_id IS NOT NULL)",
            name="ck_review_one_target",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'finalized') AND version >= 1", name="ck_review_state"
        ),
    )
    for name, columns in (
        ("ix_access_review_campaigns_company_id", ["company_id"]),
        ("ix_review_matter_company", ["matter_id", "company_id"]),
        ("ix_review_ip_company", ["ip_docket_id", "company_id"]),
        ("ix_review_page", ["company_id", "created_at", "id"]),
    ):
        op.create_index(name, C, columns)
    op.create_table(
        D,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("grant_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False),
        sa.Column("reviewer_user_id", sa.String(36), nullable=False),
        sa.Column("reviewer_membership_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["campaign_id", "company_id"],
            [C + ".id", C + ".company_id"],
            name="fk_review_decision_campaign",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewer_membership_id", "company_id"],
            ["company_memberships.id", "company_memberships.company_id"],
            name="fk_review_decision_reviewer",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("campaign_id", "grant_id", name="uq_review_decision_grant"),
        sa.CheckConstraint("decision IN ('keep', 'revoke')", name="ck_review_decision"),
    )
    for name, columns in (
        ("ix_access_review_decisions_company_id", ["company_id"]),
        ("ix_review_decision_campaign", ["campaign_id", "company_id"]),
        ("ix_review_decision_reviewer", ["reviewer_membership_id", "company_id"]),
    ):
        op.create_index(name, D, columns)
    if pg:
        frozen = " OR ".join(
            f'NEW."{key}"::text IS DISTINCT FROM OLD."{key}"::text' for key in FROZEN
        )
        op.execute(f"""CREATE FUNCTION access_review_evidence_guard()
          RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
          IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'access review evidence is immutable'; END IF;
          IF TG_TABLE_NAME = '{D}' THEN
            RAISE EXCEPTION 'access review evidence is immutable'; END IF;
          IF {frozen} OR OLD.status = 'finalized' OR NEW.version <> OLD.version + 1
          OR (NEW.status = 'open' AND NEW.finalized_at IS NOT NULL)
          OR (NEW.status = 'finalized' AND NEW.finalized_at IS NULL)
          THEN RAISE EXCEPTION 'access review evidence is immutable'; END IF;
          RETURN NEW; END $$""")
        for table in (C, D):
            op.execute(
                f"CREATE TRIGGER {table}_guard BEFORE UPDATE OR DELETE ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION access_review_evidence_guard()"
            )
        op.execute(f"""CREATE FUNCTION access_review_decision_insert_guard()
          RETURNS trigger LANGUAGE plpgsql AS $$ DECLARE campaign {C}%ROWTYPE; BEGIN
          SELECT * INTO campaign FROM {C}
            WHERE id = NEW.campaign_id AND company_id = NEW.company_id FOR UPDATE;
          IF NOT FOUND OR campaign.status <> 'open'
            OR campaign.creator_user_id = NEW.reviewer_user_id
            OR NOT EXISTS (SELECT 1 FROM company_memberships m
              WHERE m.id = NEW.reviewer_membership_id AND m.company_id = NEW.company_id
                AND m.user_id = NEW.reviewer_user_id)
            OR NOT EXISTS (SELECT 1 FROM
              jsonb_array_elements(campaign.snapshot_json::jsonb->'scope'->'grants') g
              WHERE g->>'id' = NEW.grant_id)
          THEN RAISE EXCEPTION 'access review evidence is immutable or outside scope'; END IF;
          RETURN NEW; END $$""")
        op.execute(f"CREATE TRIGGER {D}_insert_guard BEFORE INSERT ON {D} "
                   "FOR EACH ROW EXECUTE FUNCTION access_review_decision_insert_guard()")
    else:
        frozen = " OR ".join(f'NEW."{key}" IS NOT OLD."{key}"' for key in FROZEN)
        op.execute(
            f"CREATE TRIGGER {C}_update_guard BEFORE UPDATE ON {C} WHEN {frozen} "
            "OR OLD.status = 'finalized' OR NEW.version <> OLD.version + 1 "
            "OR (NEW.status = 'open' AND NEW.finalized_at IS NOT NULL) "
            "OR (NEW.status = 'finalized' AND NEW.finalized_at IS NULL) "
            "BEGIN SELECT RAISE(ABORT, 'access review evidence is immutable'); END"
        )
        op.execute(
            f"CREATE TRIGGER {D}_update_guard BEFORE UPDATE ON {D} "
            "BEGIN SELECT RAISE(ABORT, 'access review evidence is immutable'); END"
        )
        for table in (C, D):
            op.execute(
                f"CREATE TRIGGER {table}_delete_guard BEFORE DELETE ON {table} "
                "BEGIN SELECT RAISE(ABORT, 'access review evidence is immutable'); END"
            )
        op.execute(f"""CREATE TRIGGER {D}_insert_guard BEFORE INSERT ON {D}
          WHEN NOT EXISTS (SELECT 1 FROM {C} c JOIN company_memberships m
            ON m.id = NEW.reviewer_membership_id AND m.company_id = NEW.company_id
              AND m.user_id = NEW.reviewer_user_id,
            json_each(c.snapshot_json, '$.scope.grants') g
            WHERE c.id = NEW.campaign_id AND c.company_id = NEW.company_id
              AND c.status = 'open' AND c.creator_user_id <> NEW.reviewer_user_id
              AND json_extract(g.value, '$.id') = NEW.grant_id)
          BEGIN SELECT RAISE(ABORT, 'access review evidence is immutable or outside scope'); END""")


def downgrade():
    for table in (C, D):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Retained access review evidence prevents downgrade; roll forward.")
    op.drop_table(D)
    op.drop_table(C)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION access_review_evidence_guard()")
        op.execute("DROP FUNCTION access_review_decision_insert_guard()")
