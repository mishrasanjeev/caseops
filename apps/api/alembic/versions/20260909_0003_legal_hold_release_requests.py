"""Retain authenticated legal-hold release proposals.

Revision ID: 20260909_0003
Revises: 20260909_0002
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged - bounded additive trigger DDL, no data backfill.
MIGRATION-ROLLBACK: populated proposals refuse downgrade; roll forward.
Data-map integration: ip-foundations-ops-closure-2026-09-09.md; not yet admitted
for export or purge. No new client-content or execution authority.
"""

import sqlalchemy as sa

from alembic import op

revision = "20260909_0003"
down_revision = "20260909_0002"
branch_labels = None
depends_on = None
TABLE = "legal_hold_release_requests"


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "company_id",
            sa.String(36),
            sa.ForeignKey("companies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("legal_hold_id", sa.String(36), nullable=False),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("requester_user_id", sa.String(36), nullable=False),
        sa.Column("requester_membership_id", sa.String(36), nullable=False),
        sa.Column("requester_label_snapshot", sa.String(255), nullable=False),
        sa.Column("reason_reference", sa.String(512), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["legal_hold_id", "company_id"],
            ["legal_holds.id", "legal_holds.company_id"],
            name="fk_hold_release_request_hold_company",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["dry_run_id", "company_id"],
            ["tenant_data_operations.id", "tenant_data_operations.company_id"],
            name="fk_hold_release_request_dry_run_company",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("company_id", "idempotency_key", name="uq_hold_release_request_key"),
        sa.CheckConstraint("expires_at > created_at", name="ck_hold_release_request_expiry"),
        sa.CheckConstraint("length(request_hash) = 64", name="ck_hold_release_request_hash"),
    )
    for suffix, columns in (
        ("company_id", ["company_id"]),
        ("hold_company", ["legal_hold_id", "company_id"]),
        ("dry_run_company", ["dry_run_id", "company_id"]),
    ):
        name = (
            "ix_legal_hold_release_requests_company_id"
            if suffix == "company_id"
            else f"ix_hold_release_request_{suffix}"
        )
        op.create_index(name, TABLE, columns)
    op.create_index(
        "ix_legal_holds_register_page", "legal_holds", ["company_id", "created_at", "id"]
    )
    op.create_index(
        "ix_hold_release_request_page", TABLE, ["company_id", "legal_hold_id", "created_at", "id"]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION caseops_retain_hold_release_request() RETURNS trigger AS $$
        BEGIN RAISE EXCEPTION 'Legal hold release proposals are immutable'; END;
        $$ LANGUAGE plpgsql""")
        op.execute(
            "CREATE TRIGGER trg_hold_release_request_immutable "
            f"BEFORE UPDATE OR DELETE ON {TABLE} FOR EACH ROW "
            "EXECUTE FUNCTION caseops_retain_hold_release_request()"
        )
        # The writer and this trigger share Company -> LegalHold lock order.
        # A draft scope change also invalidates an approver's previous version.
        op.execute("""CREATE FUNCTION caseops_guard_hold_scope_insert() RETURNS trigger AS $$
        DECLARE parent_status text;
        BEGIN
            PERFORM id FROM companies WHERE id = NEW.company_id FOR UPDATE;
            SELECT status INTO parent_status FROM legal_holds
                WHERE id = NEW.legal_hold_id AND company_id = NEW.company_id FOR UPDATE;
            IF parent_status IS DISTINCT FROM 'draft' THEN
                RAISE EXCEPTION 'Legal hold scope can only be added to a draft';
            END IF;
            UPDATE legal_holds
                SET updated_at = GREATEST(clock_timestamp(), updated_at + interval '1 microsecond')
                WHERE id = NEW.legal_hold_id AND company_id = NEW.company_id;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql""")
        op.execute("""CREATE TRIGGER trg_legal_hold_items_draft_insert
            BEFORE INSERT ON legal_hold_items FOR EACH ROW
            EXECUTE FUNCTION caseops_guard_hold_scope_insert()""")
    else:
        for action in ("UPDATE", "DELETE"):
            op.execute(f"""CREATE TRIGGER trg_hold_release_request_no_{action.lower()}
            BEFORE {action} ON {TABLE} BEGIN
            SELECT RAISE(ABORT, 'Legal hold release proposals are immutable'); END""")
        op.execute("""CREATE TRIGGER trg_legal_hold_items_draft_insert
            BEFORE INSERT ON legal_hold_items FOR EACH ROW
            WHEN COALESCE((SELECT status FROM legal_holds
                WHERE id = NEW.legal_hold_id AND company_id = NEW.company_id), '') <> 'draft'
            BEGIN SELECT RAISE(ABORT, 'Legal hold scope can only be added to a draft'); END""")
        op.execute("""CREATE TRIGGER trg_legal_hold_items_scope_version
            AFTER INSERT ON legal_hold_items FOR EACH ROW
            BEGIN UPDATE legal_holds SET updated_at = strftime('%Y-%m-%d %H:%M:%f',
                MAX(julianday('now'), julianday(updated_at) + 0.000000011574074))
                WHERE id = NEW.legal_hold_id AND company_id = NEW.company_id; END""")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.execute(sa.text(f"LOCK TABLE {TABLE} IN ACCESS EXCLUSIVE MODE"))
    if bind.scalar(sa.text(f"SELECT EXISTS (SELECT 1 FROM {TABLE})")):
        raise RuntimeError("Legal hold release evidence exists; roll forward instead.")
    op.drop_index("ix_legal_holds_register_page", table_name="legal_holds")
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER trg_legal_hold_items_draft_insert ON legal_hold_items")
        op.execute("DROP FUNCTION caseops_guard_hold_scope_insert()")
    else:
        op.execute("DROP TRIGGER trg_legal_hold_items_draft_insert")
        op.execute("DROP TRIGGER trg_legal_hold_items_scope_version")
    op.drop_table(TABLE)
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION caseops_retain_hold_release_request()")
