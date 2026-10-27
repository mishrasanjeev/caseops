"""Synchronous derived counsel read pages, retaining all old source writers.

Revision ID: 20261027_0005
Revises: 20261027_0004
DATA-GOVERNANCE-MAP: updated
MIGRATION-LOCK-RISK: acknowledged; bounded5s DDL/parent-lock and30s migration
statement budgets. Trigger installation fences source writers through the
transactional backfill. A failed/too-large backfill rolls back the whole upgrade.
MIGRATION-ROLLBACK: restore-forward; downgrade refuses before DDL. Source,
audit/outbox and derived legal-content rows are never erased by downgrade.

PostgreSQL packs only bounded scalar/name metadata. Each source's single
unbounded Text field uses an independent native Text column per slot, not a
JSON/array aggregate or an added payload constraint. SQLite keeps its canonical
reader and records native key/rank membership without copying wide source data.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20261027_0005"
down_revision = "20261027_0004"
branch_labels = None
depends_on = None

PAGE = "counsel_read_pages"
MEMBER = "counsel_read_page_members"
SOURCES = {
    "assignment": (
        "matter_outside_counsel_assignments",
        "assigned_by_membership_id",
        "internal_notes",
        (
            "id",
            "company_id",
            "matter_id",
            "counsel_id",
            "assigned_by_membership_id",
            "role_summary",
            "budget_amount_minor",
            "currency",
            "status",
            "created_at",
            "updated_at",
        ),
    ),
    "spend": (
        "outside_counsel_spend_records",
        "recorded_by_membership_id",
        "notes",
        (
            "id",
            "company_id",
            "matter_id",
            "counsel_id",
            "assignment_id",
            "recorded_by_membership_id",
            "invoice_reference",
            "stage_label",
            "description",
            "currency",
            "amount_minor",
            "approved_amount_minor",
            "status",
            "billed_on",
            "due_on",
            "paid_on",
            "created_at",
            "updated_at",
        ),
    ),
}


def _create_tables():
    op.create_table(
        "counsel_read_page_dirty",
        sa.Column("transaction_id", sa.BigInteger(), primary_key=True),
        sa.Column("record_kind", sa.String(16), primary_key=True),
        sa.Column("company_id", sa.String(36), primary_key=True),
        sa.Column("matter_id", sa.String(36), primary_key=True),
        sa.Column("source_user_id", sa.String(36), primary_key=True),
        sa.CheckConstraint(
            "record_kind IN ('assignment', 'spend', 'user')", name="ck_counsel_dirty_kind"
        ),
        sa.CheckConstraint(
            "(record_kind = 'user' AND company_id = '' AND matter_id = '' "
            ") OR (record_kind IN ('assignment', 'spend') AND source_user_id = '')",
            name="ck_counsel_dirty_scope",
        ),
    )
    op.create_table(
        PAGE,
        sa.Column("company_id", sa.String(36), primary_key=True),
        sa.Column("matter_id", sa.String(36), primary_key=True),
        sa.Column("record_kind", sa.String(16), primary_key=True),
        sa.Column("max_id", sa.String(36), primary_key=True),
        sa.Column("min_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column(
            "payload", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False
        ),
        *[sa.Column(f"note_{n:02}", sa.Text(), nullable=True) for n in range(25)],
        sa.CheckConstraint("record_kind IN ('assignment', 'spend')", name="ck_counsel_page_kind"),
        sa.CheckConstraint("page_number >= 0", name="ck_counsel_page_number"),
        sa.CheckConstraint("record_count BETWEEN 1 AND 25", name="ck_counsel_page_capacity"),
    )
    op.create_index("ix_counsel_read_pages_matter_id", PAGE, ["matter_id"])
    op.create_table(
        MEMBER,
        sa.Column("company_id", sa.String(36), primary_key=True),
        sa.Column("matter_id", sa.String(36), primary_key=True),
        sa.Column("record_kind", sa.String(16), primary_key=True),
        sa.Column("source_id", sa.String(36), primary_key=True),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("slot_number", sa.Integer(), nullable=False),
        sa.CheckConstraint("record_kind IN ('assignment', 'spend')", name="ck_counsel_member_kind"),
        sa.CheckConstraint("page_number >= 0", name="ck_counsel_member_page_number"),
        sa.CheckConstraint("slot_number BETWEEN 0 AND 24", name="ck_counsel_member_slot"),
    )
    op.create_index("ix_counsel_page_members_matter_id", MEMBER, ["matter_id"])


def _pg_rebuild_function():
    inserts = []
    for kind, (table, actor, note, columns) in SOURCES.items():
        pairs = ", ".join(f"'{key}', ranked.{key}" for key in columns)
        pairs += (
            ", 'counsel_name', ranked.counsel_name, 'actor_user_id', ranked.actor_user_id"
            ", 'actor_name', ranked.actor_name"
        )
        wide_columns = ", ".join(f"note_{n:02}" for n in range(25))
        wide_values = ", ".join(
            f"max(ranked.{note}) FILTER (WHERE ranked.slot_number = {n})" for n in range(25)
        )
        inserts.append(f"""
        {"IF" if not inserts else "ELSIF"} p_kind = '{kind}' THEN
          INSERT INTO public.{PAGE} (company_id, matter_id, record_kind, min_id, max_id,
              page_number, record_count, payload, {wide_columns})
          SELECT p_company, p_matter, p_kind, min(ranked.id), max(ranked.id),
              ranked.page_number, count(*)::integer,
              jsonb_agg(jsonb_build_object({pairs}) ORDER BY ranked.id), {wide_values}
          FROM (
            SELECT s.*, c.name AS counsel_name, a.user_id AS actor_user_id,
              u.full_name AS actor_name,
              ((row_number() OVER (ORDER BY s.id) - 1) / 25)::integer AS page_number,
              ((row_number() OVER (ORDER BY s.id) - 1) % 25)::integer AS slot_number
            FROM public.{table} AS s
            JOIN public.outside_counsel AS c ON c.id = s.counsel_id AND c.company_id = s.company_id
            LEFT JOIN public.company_memberships AS a
              ON a.id = s.{actor} AND a.company_id = s.company_id
            LEFT JOIN public.users AS u ON u.id=a.user_id
            WHERE s.company_id = p_company AND s.matter_id = p_matter
          ) AS ranked GROUP BY ranked.page_number;
        """)
    return (
        """
    CREATE FUNCTION public.caseops_counsel_rebuild_v1(
      p_company varchar, p_matter varchar, p_kind varchar)
    RETURNS void LANGUAGE plpgsql VOLATILE SET search_path = pg_catalog, public AS $$
    BEGIN
      IF p_kind NOT IN ('assignment','spend') THEN
        RAISE EXCEPTION 'Unsupported counsel record kind';
      END IF;
      PERFORM public.caseops_counsel_lock_scope_v1(p_company,p_matter);
      IF NOT EXISTS (SELECT 1 FROM public.matters WHERE id=p_matter AND company_id=p_company) THEN
        DELETE FROM public.counsel_read_pages
          WHERE company_id=p_company AND matter_id=p_matter AND record_kind=p_kind;
        RETURN;
      END IF;
      DELETE FROM public.counsel_read_pages
        WHERE company_id=p_company AND matter_id=p_matter AND record_kind=p_kind;
    """
        + "".join(inserts)
        + """
      END IF;
    END $$;
    """
    )


def _postgres_triggers():
    # Namespace CPG1 is projection-only; hashes can conservatively serialize
    # unrelated scopes, never change scope equality or grant read authority.
    # No Matter/Company FK is added from derived rows. In particular a profile
    # writer never waits for a source writer's previously acquired Matter lock.
    op.execute("""
    CREATE FUNCTION public.caseops_counsel_lock_scope_v1(p_company varchar,p_matter varchar)
    RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    BEGIN PERFORM pg_advisory_xact_lock(1129334577,hashtext(p_company || ':' || p_matter)); END $$;
    """)
    op.execute(_pg_rebuild_function())
    op.execute("""
    CREATE FUNCTION public.caseops_counsel_source_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    BEGIN
      INSERT INTO public.counsel_read_page_dirty
        (transaction_id,record_kind,company_id,matter_id,source_user_id)
      SELECT txid_current(),TG_ARGV[0],c,m,'' FROM (
        SELECT OLD.company_id AS c,OLD.matter_id AS m WHERE TG_OP <> 'INSERT'
        UNION SELECT NEW.company_id,NEW.matter_id WHERE TG_OP <> 'DELETE'
      ) changed WHERE c IS NOT NULL AND m IS NOT NULL ON CONFLICT DO NOTHING;
      RETURN NULL;
    END $$;
    """)
    # Counsel(company_id,name) and Membership(company_id,user_id) are existing
    # unique keys: their key updates conflict with the source's existing FK
    # KEY SHARE. No new User SHARE lock or User-to-parent enumeration is added.
    # User label propagation expands source scopes under DER1 at finalization;
    # it never enumerates parents before the source/FK/audit transaction ends.
    affected = """
      SELECT company_id AS c,matter_id AS m,'assignment' AS k
      FROM public.matter_outside_counsel_assignments
      WHERE (TG_TABLE_NAME='outside_counsel' AND counsel_id IN (OLD.id,NEW.id))
         OR (TG_TABLE_NAME='company_memberships' AND assigned_by_membership_id IN (OLD.id,NEW.id))
      UNION SELECT company_id,matter_id,'spend'
      FROM public.outside_counsel_spend_records
      WHERE (TG_TABLE_NAME='outside_counsel' AND counsel_id IN (OLD.id,NEW.id))
         OR (TG_TABLE_NAME='company_memberships' AND recorded_by_membership_id IN (OLD.id,NEW.id))
    """
    op.execute(
        """
    CREATE FUNCTION public.caseops_counsel_labels_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    BEGIN
      INSERT INTO public.counsel_read_page_dirty
        (transaction_id,record_kind,company_id,matter_id,source_user_id)
      SELECT txid_current(),k,c,m,'' FROM ("""
        + affected
        + """) scopes
      WHERE c IS NOT NULL AND m IS NOT NULL ON CONFLICT DO NOTHING;
      RETURN NULL;
    END $$;
    """
    )
    op.execute("""
    CREATE FUNCTION public.caseops_counsel_user_changed_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    BEGIN
      INSERT INTO public.counsel_read_page_dirty
        (transaction_id,record_kind,company_id,matter_id,source_user_id)
      SELECT txid_current(),'user','','',value FROM (
        SELECT OLD.id AS value WHERE TG_OP <> 'INSERT'
        UNION SELECT NEW.id WHERE TG_OP <> 'DELETE'
      ) changed WHERE value IS NOT NULL ON CONFLICT DO NOTHING;
      RETURN NULL;
    END $$;
    """)
    op.execute("""
    CREATE FUNCTION public.caseops_counsel_truncate_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    BEGIN
      INSERT INTO public.counsel_read_page_dirty
        (transaction_id,record_kind,company_id,matter_id,source_user_id)
      SELECT DISTINCT txid_current(),record_kind,company_id,matter_id,''
      FROM public.counsel_read_pages
      WHERE TG_ARGV[0]='all' OR record_kind=TG_ARGV[0] ON CONFLICT DO NOTHING;
      RETURN NULL;
    END $$;
    """)
    # DER1 is shared with the separately reviewed task projection finalizer.
    # It is NEVER acquired in a source/label trigger. Canonical API writers
    # finish their existing parent, source and audit/FK work before this gate.
    op.execute("""
    CREATE FUNCTION public.caseops_counsel_finalize_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $$
    DECLARE target record;
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM public.counsel_read_page_dirty
                     WHERE transaction_id=txid_current()) THEN RETURN NULL; END IF;
      PERFORM pg_advisory_xact_lock(1145393713,0);
      -- Expansion happens AFTER DER1 and uses a fresh VOLATILE command
      -- snapshot. Whichever source/User transaction commits first is visible
      -- to the later finalizer; no first-reference association can be missed.
      INSERT INTO public.counsel_read_page_dirty
        (transaction_id,record_kind,company_id,matter_id,source_user_id)
      SELECT DISTINCT txid_current(),changed.k,changed.c,changed.m,'' FROM (
        SELECT 'assignment' AS k,s.company_id AS c,s.matter_id AS m
        FROM public.matter_outside_counsel_assignments s
        JOIN public.company_memberships a
          ON a.id=s.assigned_by_membership_id AND a.company_id=s.company_id
        JOIN public.counsel_read_page_dirty d
          ON d.transaction_id=txid_current() AND d.record_kind='user' AND d.source_user_id=a.user_id
        UNION ALL
        SELECT 'spend',s.company_id,s.matter_id
        FROM public.outside_counsel_spend_records s
        JOIN public.company_memberships a
          ON a.id=s.recorded_by_membership_id AND a.company_id=s.company_id
        JOIN public.counsel_read_page_dirty d
          ON d.transaction_id=txid_current() AND d.record_kind='user' AND d.source_user_id=a.user_id
      ) changed ON CONFLICT DO NOTHING;
      FOR target IN
        SELECT DISTINCT hashtext(company_id || ':' || matter_id) AS lock_key
        FROM public.counsel_read_page_dirty
        WHERE transaction_id=txid_current() AND record_kind <> 'user' ORDER BY lock_key
      LOOP PERFORM pg_advisory_xact_lock(1129334577,target.lock_key); END LOOP;
      FOR target IN SELECT * FROM public.counsel_read_page_dirty
        WHERE transaction_id=txid_current()
        ORDER BY record_kind COLLATE "C",company_id COLLATE "C",
          matter_id COLLATE "C",source_user_id COLLATE "C"
      LOOP
        IF target.record_kind <> 'user' THEN
          PERFORM public.caseops_counsel_rebuild_v1(
            target.company_id,target.matter_id,target.record_kind);
        END IF;
      END LOOP;
      DELETE FROM public.counsel_read_page_dirty WHERE transaction_id=txid_current();
      RETURN NULL;
    END $$;
    """)
    op.execute("""
      CREATE CONSTRAINT TRIGGER counsel_page_finalize_v1
      AFTER INSERT ON public.counsel_read_page_dirty
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION public.caseops_counsel_finalize_v1()
    """)
    for kind, (table, _actor, _note, _columns) in SOURCES.items():
        op.execute(
            f"CREATE TRIGGER counsel_page_source_v1 AFTER INSERT OR UPDATE OR DELETE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION public.caseops_counsel_source_v1('{kind}')"
        )
        op.execute(
            f"CREATE TRIGGER counsel_page_truncate_v1 AFTER TRUNCATE ON {table} "
            f"FOR EACH STATEMENT EXECUTE FUNCTION public.caseops_counsel_truncate_v1('{kind}')"
        )
    for table, fields in (
        ("outside_counsel", "id,company_id,name"),
        ("company_memberships", "id,company_id,user_id"),
    ):
        for event in (f"UPDATE OF {fields}", "DELETE"):
            label = "update" if event.startswith("UPDATE") else "delete"
            op.execute(
                f"CREATE TRIGGER counsel_page_labels_{label}_v1 AFTER {event} ON {table} "
                "FOR EACH ROW EXECUTE FUNCTION public.caseops_counsel_labels_v1()"
            )
    for event in ("INSERT", "DELETE", "UPDATE"):
        condition = (
            " WHEN (OLD.full_name IS DISTINCT FROM NEW.full_name OR OLD.id IS DISTINCT FROM NEW.id)"
            if event == "UPDATE"
            else ""
        )
        op.execute(
            f"CREATE TRIGGER counsel_user_{event.lower()}_v1 AFTER {event} ON users "
            f"FOR EACH ROW{condition} EXECUTE FUNCTION public.caseops_counsel_user_changed_v1()"
        )
    for table in ("matters", "companies", "users"):
        op.execute(
            f"CREATE TRIGGER counsel_page_truncate_v1 AFTER TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.caseops_counsel_truncate_v1('all')"
        )
    for signature in (
        "caseops_counsel_lock_scope_v1(varchar,varchar)",
        "caseops_counsel_rebuild_v1(varchar,varchar,varchar)",
        "caseops_counsel_source_v1()",
        "caseops_counsel_finalize_v1()",
        "caseops_counsel_labels_v1()",
        "caseops_counsel_user_changed_v1()",
        "caseops_counsel_truncate_v1()",
    ):
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    op.execute("""
    DO $$ DECLARE scope record; BEGIN
      FOR scope IN SELECT company_id AS c,matter_id AS m,'assignment' AS k
        FROM matter_outside_counsel_assignments
        UNION SELECT company_id,matter_id,'spend' FROM outside_counsel_spend_records ORDER BY c,m,k
      LOOP PERFORM public.caseops_counsel_rebuild_v1(scope.c,scope.m,scope.k); END LOOP;
    END $$;
    """)


def _sqlite_select(kind, scope="1=1"):
    table, _actor, _note, _columns = SOURCES[kind]
    return f"""
      SELECT ranked.company_id,ranked.matter_id,'{kind}',ranked.id,
        CAST(ranked.position / 25 AS INTEGER),ranked.position % 25
      FROM (
        SELECT s.company_id,s.matter_id,s.id,
          row_number() OVER (PARTITION BY s.company_id,s.matter_id ORDER BY s.id)-1 AS position
        FROM {table} s
        JOIN outside_counsel c ON c.id=s.counsel_id AND c.company_id=s.company_id
        JOIN matters m ON m.id=s.matter_id AND m.company_id=s.company_id
        WHERE {scope}
      ) ranked
    """


def _sqlite_triggers():
    columns = "company_id,matter_id,record_kind,source_id,page_number,slot_number"
    for kind, (table, _actor, _note, _fields) in SOURCES.items():
        for event in ("INSERT", "UPDATE", "DELETE"):
            aliases = (
                ["OLD"] if event == "DELETE" else ["NEW"] if event == "INSERT" else ["OLD", "NEW"]
            )
            where = " OR ".join(
                f"(company_id={a}.company_id AND matter_id={a}.matter_id)" for a in aliases
            )
            scope = " OR ".join(
                f"(s.company_id={a}.company_id AND s.matter_id={a}.matter_id)" for a in aliases
            )
            op.execute(f"""CREATE TRIGGER counsel_{kind}_source_{event.lower()}_v1
              AFTER {event} ON {table}
              BEGIN
                DELETE FROM {MEMBER} WHERE record_kind='{kind}' AND ({where});
                INSERT INTO {MEMBER} ({columns}) {_sqlite_select(kind, scope)};
              END""")
        # Counsel tenant changes can change canonical source eligibility. Names
        # remain read fresh by the unchanged SQLite canonical serializer path.
        target = (
            f"(company_id,matter_id) IN (SELECT company_id,matter_id FROM {table} "
            "WHERE counsel_id IN (OLD.id,NEW.id))"
        )
        scope = (
            f"(s.company_id,s.matter_id) IN (SELECT company_id,matter_id FROM {table} "
            "WHERE counsel_id IN (OLD.id,NEW.id))"
        )
        op.execute(f"""CREATE TRIGGER counsel_{kind}_label_update_v1 AFTER UPDATE ON outside_counsel
          BEGIN
            DELETE FROM {MEMBER} WHERE record_kind='{kind}' AND {target};
            INSERT INTO {MEMBER} ({columns}) {_sqlite_select(kind, scope)};
          END""")
        op.execute(f"INSERT INTO {MEMBER} ({columns}) {_sqlite_select(kind)}")


def upgrade():
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        op.execute("SET LOCAL lock_timeout = '5s'")
        op.execute("SET LOCAL statement_timeout = '30s'")
    elif dialect != "sqlite":
        raise RuntimeError("Unsupported counsel projection database.")
    _create_tables()
    if dialect == "postgresql":
        _postgres_triggers()
    else:
        _sqlite_triggers()


def downgrade():
    raise RuntimeError("Counsel derived legal-content rows are retained; restore-forward only.")
