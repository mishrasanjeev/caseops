"""Frozen0008 packed retained-read schema. Source rows/authorization stay canonical.

Versioned migration/model-create contract: never repurpose this module for a later
schema revision. PostgreSQL source triggers collect scopes only; DER1 is taken
at the deferred commit boundary, after existing source and audit FK work.
SQLite retains its canonical source reader and leaves these derived tables empty.
"""

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
)
from sqlalchemy.dialects.postgresql import JSONB

CAPACITY = 25
DIRTY = "matter_readthrough_dirty"
FAMILIES = {
    "recommendations": "matter_recommendation_read_pages",
    "recommendation_options": "matter_option_read_pages",
    "recommendation_decisions": "matter_decision_read_pages",
    "hearing_packs": "matter_hearing_pack_read_pages",
    "hearing_pack_items": "matter_pack_item_read_pages",
}
LAYOUTS = {
    "recommendations": ("chron", "id"),
    "recommendation_options": ("rank",),
    "recommendation_decisions": ("chron",),
    "hearing_packs": ("latest", "id"),
    "hearing_pack_items": ("rank",),
}
SOURCE_TABLES = (*FAMILIES, "matters", "matter_hearings")
FINALIZE_GATE_NAMESPACE = 1145393713  # DER1: shared with0005 and0006, commit only.
SCOPE_LOCK_NAMESPACE = 1381257265  # RTP1, actual integer keys sorted after DER1.

# Frozen scalar/prefix definitions. Identity/order fields remain native SQL
# values; each Text prefix retains its original octet extent for honest decode.
REC_META = {
    "id": None,
    "company_id": None,
    "matter_id": None,
    "created_at": None,
    "updated_at": None,
    "type": 40,
    "title": 400,
    "confidence": 16,
    "review_required": None,
    "status": 24,
}
REC_DETAIL = {
    **REC_META,
    "primary_option_index": None,
    "rationale": 16384,
    "assumptions_json": 16384,
    "missing_facts_json": 16384,
    "next_action": 16384,
    "retrieved_authorities_json": 16384,
    "strategy_payload_json": 16384,
    "analysis_json": 16384,
}
FIELDS = {
    ("recommendations", "chron"): REC_META,
    ("recommendations", "id"): REC_DETAIL,
    ("recommendation_options", "rank"): {
        "id": None,
        "recommendation_id": None,
        "rank": None,
        "label": 400,
        "confidence": 16,
        "rationale": 16384,
        "supporting_citations_json": 16384,
        "risk_notes": 16384,
    },
    ("recommendation_decisions", "chron"): {
        "id": None,
        "recommendation_id": None,
        "created_at": None,
        "actor_membership_id": 36,
        "selected_option_index": None,
        "decision": 24,
        "notes": 16384,
    },
    ("hearing_packs", "latest"): {
        "id": None,
        "matter_id": None,
        "hearing_id": None,
        "generated_at": None,
        "reviewed_at": None,
        "generated_by_membership_id": 36,
        "reviewed_by_membership_id": 36,
        "model_run_id": 36,
        "status": 24,
        "review_required": None,
        "summary": 16384,
    },
    ("hearing_pack_items", "rank"): {
        "id": None,
        "pack_id": None,
        "rank": None,
        "created_at": None,
        "item_type": 40,
        "title": 255,
        "body": 16384,
        "source_ref": 500,
    },
}
FIELDS[("hearing_packs", "id")] = FIELDS[("hearing_packs", "latest")]


def define_tables(metadata: MetaData) -> dict[str, Table]:
    result = {}
    for source, name in FAMILIES.items():
        choices = ",".join(repr(x) for x in LAYOUTS[source])
        result[name] = Table(
            name,
            metadata,
            Column("company_id", String(36), nullable=False),
            Column("matter_id", String(36), nullable=False),
            Column("layout", String(8), nullable=False),
            Column("parent_key", String(36), nullable=False),
            Column("page_number", Integer, nullable=False),
            Column("record_count", Integer, nullable=False),
            Column("last_stamp", DateTime(timezone=True)),
            Column("last_rank", BigInteger),
            Column("last_id", String(36), nullable=False),
            Column("payload", JSON().with_variant(JSONB, "postgresql"), nullable=False),
            PrimaryKeyConstraint(
                "company_id",
                "matter_id",
                "layout",
                "parent_key",
                "page_number",
                name="pk_" + name,
            ),
            CheckConstraint("layout IN (" + choices + ")", name="ck_" + name + "_layout"),
            CheckConstraint("page_number >= 0", name="ck_" + name + "_number"),
            CheckConstraint("record_count BETWEEN 1 AND 25", name="ck_" + name + "_size"),
        )
    for source, name in FAMILIES.items():
        table = result[name]
        for layout in LAYOUTS[source]:
            key = "last_id" if layout == "id" else "last_rank" if layout == "rank" else "last_stamp"
            keys = ["company_id", "matter_id", "layout", "parent_key", key]
            if key != "last_id":
                keys.append("last_id")
            Index("ix_" + name + "_" + layout + "_seek", *(table.c[key] for key in keys))
    result[DIRTY] = Table(
        DIRTY,
        metadata,
        Column("transaction_id", BigInteger, primary_key=True),
        Column("company_id", String(36), primary_key=True),
        Column("matter_id", String(36), primary_key=True),
    )
    return result


def create_tables(connection):
    for table in define_tables(MetaData()).values():
        table.create(connection)


def _source(source):
    if source == "recommendations":
        return (
            "public.recommendations s",
            "s.company_id",
            "s.matter_id",
            "s.type <> 'intelligent_review'",
        )
    if source in {"recommendation_options", "recommendation_decisions"}:
        return (
            f"public.{source} s JOIN public.recommendations r ON r.id=s.recommendation_id "
            "JOIN public.matters m ON m.id=r.matter_id AND m.company_id=r.company_id",
            "r.company_id",
            "r.matter_id",
            "r.type <> 'intelligent_review'",
        )
    if source == "hearing_packs":
        return (
            "public.hearing_packs s JOIN public.matters m ON m.id=s.matter_id",
            "m.company_id",
            "s.matter_id",
            "true",
        )
    return (
        "public.hearing_pack_items s JOIN public.hearing_packs p ON p.id=s.pack_id "
        "JOIN public.matters m ON m.id=p.matter_id",
        "m.company_id",
        "p.matter_id",
        "true",
    )


def _insert(source, layout):
    relation, company, matter, predicate = _source(source)
    parent = {
        "recommendations": "''::varchar",
        "recommendation_options": "s.recommendation_id",
        "recommendation_decisions": "s.recommendation_id",
        "hearing_packs": ("coalesce(s.hearing_id,'')" if layout == "latest" else "''::varchar"),
        "hearing_pack_items": "s.pack_id",
    }[source]
    key = (
        "s.id"
        if layout == "id"
        else "s.rank"
        if layout == "rank"
        else "s.generated_at"
        if layout == "latest"
        else "s.created_at"
    )
    direction = "ASC" if layout in {"id", "rank"} else "DESC"
    order = f"{key} {direction},s.id {direction}"
    pairs = []
    for field, cap in FIELDS[(source, layout)].items():
        value = f"s.{field}"
        pairs.extend((repr(field), value if cap is None else f"substr({value},1,{cap + 1})"))
        if cap is not None:
            pairs.extend((repr(field + "_source_bytes"), f"octet_length({value})"))
    pairs.extend(("'__company_id'", company, "'__matter_id'", matter))
    payload = "jsonb_build_object(" + ",".join(pairs) + ")"
    stamp = key if layout in {"chron", "latest"} else "NULL::timestamptz"
    rank = key if layout == "rank" else "NULL::bigint"
    return f"""INSERT INTO public.{FAMILIES[source]}
      (company_id,matter_id,layout,parent_key,page_number,record_count,
       last_stamp,last_rank,last_id,payload)
    SELECT p_company,p_matter,'{layout}',parent_key,(position/25)::integer,count(*)::integer,
      (array_agg(stamp ORDER BY position DESC))[1],
      (array_agg(rank_key ORDER BY position DESC))[1],
      (array_agg(source_id ORDER BY position DESC))[1],
      jsonb_agg(entry ORDER BY position)
    FROM (
      SELECT {parent} AS parent_key,{stamp} AS stamp,{rank} AS rank_key,s.id AS source_id,
        {payload} AS entry,
        row_number() OVER (PARTITION BY {parent} ORDER BY {order})-1 AS position
      FROM {relation}
      WHERE {company}=p_company AND {matter}=p_matter AND {predicate}
    ) ranked GROUP BY parent_key,(position/25)::integer"""


def postgres_statements():
    delete = "\n".join(
        f"DELETE FROM public.{name} WHERE company_id=p_company AND matter_id=p_matter;"
        for name in FAMILIES.values()
    )
    inserts = ";\n".join(
        _insert(source, layout) for source in FAMILIES for layout in LAYOUTS[source]
    )
    statements = [
        f"""CREATE FUNCTION public.caseops_readthrough_rebuild_v1(
      p_company varchar,p_matter varchar) RETURNS void
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $fn$
    BEGIN
      {delete}
      IF NOT EXISTS (SELECT 1 FROM public.matters
                     WHERE id=p_matter AND company_id=p_company) THEN RETURN; END IF;
      {inserts};
    END $fn$"""
    ]
    # Only source scope discovery, no projection lock or source/parent FOR UPDATE.
    direct = """SELECT OLD.company_id c,OLD.matter_id m WHERE TG_OP<>'INSERT'
      UNION SELECT NEW.company_id,NEW.matter_id WHERE TG_OP<>'DELETE'"""
    matter = """SELECT OLD.company_id c,OLD.id m WHERE TG_OP<>'INSERT'
      UNION SELECT NEW.company_id,NEW.id WHERE TG_OP<>'DELETE'"""
    pack = """SELECT m.company_id c,m.id m FROM public.matters m WHERE m.id IN (
      SELECT OLD.matter_id WHERE TG_OP<>'INSERT'
      UNION SELECT NEW.matter_id WHERE TG_OP<>'DELETE')"""
    child = """SELECT r.company_id c,r.matter_id m FROM public.recommendations r
      WHERE r.id IN (SELECT OLD.recommendation_id WHERE TG_OP<>'INSERT'
                    UNION SELECT NEW.recommendation_id WHERE TG_OP<>'DELETE')"""
    item = """SELECT m.company_id c,m.id m FROM public.hearing_packs p
      JOIN public.matters m ON m.id=p.matter_id
      WHERE p.id IN (SELECT OLD.pack_id WHERE TG_OP<>'INSERT'
                    UNION SELECT NEW.pack_id WHERE TG_OP<>'DELETE')"""
    branches = []
    for tables, select_sql in [
        (("recommendations",), direct),
        (("matters",), matter),
        (("hearing_packs", "matter_hearings"), pack),
        (("recommendation_options", "recommendation_decisions"), child),
        (("hearing_pack_items",), item),
    ]:
        condition = "TG_TABLE_NAME IN (" + ",".join(repr(x) for x in tables) + ")"
        branches.append(
            ("IF" if not branches else "ELSIF") + f" {condition} THEN\n"
            f"INSERT INTO public.{DIRTY}(transaction_id,company_id,matter_id) "
            f"SELECT txid_current(),c,m FROM ({select_sql}) changed "
            "WHERE c IS NOT NULL AND m IS NOT NULL ON CONFLICT DO NOTHING;"
        )
    statements.append(
        """CREATE FUNCTION public.caseops_readthrough_mark_v1() RETURNS trigger
      LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $fn$ BEGIN
    """
        + "\n".join(branches)
        + "\nEND IF; RETURN NULL; END $fn$"
    )
    statements.append(f"""CREATE FUNCTION public.caseops_readthrough_finalize_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $fn$
    DECLARE target record;
    BEGIN
      IF NOT EXISTS (SELECT 1 FROM public.{DIRTY} WHERE transaction_id=txid_current())
        THEN RETURN NULL; END IF;
      PERFORM pg_advisory_xact_lock({FINALIZE_GATE_NAMESPACE},0);
      FOR target IN SELECT DISTINCT hashtext(company_id || ':' || matter_id) lock_key
        FROM public.{DIRTY} WHERE transaction_id=txid_current() ORDER BY lock_key
      LOOP PERFORM pg_advisory_xact_lock({SCOPE_LOCK_NAMESPACE},target.lock_key); END LOOP;
      FOR target IN SELECT company_id,matter_id FROM public.{DIRTY}
        WHERE transaction_id=txid_current() ORDER BY company_id COLLATE "C",matter_id COLLATE "C"
      LOOP
        PERFORM public.caseops_readthrough_rebuild_v1(target.company_id,target.matter_id);
      END LOOP;
      DELETE FROM public.{DIRTY} WHERE transaction_id=txid_current(); RETURN NULL;
    END $fn$""")
    union = " UNION ".join(
        f"SELECT company_id,matter_id FROM public.{p}" for p in FAMILIES.values()
    )
    statements.append(f"""CREATE FUNCTION public.caseops_readthrough_truncate_v1() RETURNS trigger
    LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $fn$ BEGIN
      INSERT INTO public.{DIRTY}(transaction_id,company_id,matter_id)
      SELECT txid_current(),company_id,matter_id FROM ({union}) scopes
      ON CONFLICT DO NOTHING; RETURN NULL;
    END $fn$""")
    statements.append(f"""CREATE CONSTRAINT TRIGGER readthrough_finalize_v1
      AFTER INSERT ON public.{DIRTY} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      EXECUTE FUNCTION public.caseops_readthrough_finalize_v1()""")
    for table in SOURCE_TABLES:
        statements.append(
            "CREATE TRIGGER readthrough_source_v1 AFTER INSERT OR UPDATE OR DELETE "
            f"ON public.{table} "
            "FOR EACH ROW EXECUTE FUNCTION public.caseops_readthrough_mark_v1()"
        )
    for table in (*SOURCE_TABLES, "companies"):
        statements.append(
            f"CREATE TRIGGER readthrough_truncate_v1 AFTER TRUNCATE ON public.{table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION public.caseops_readthrough_truncate_v1()"
        )
    for signature in [
        "caseops_readthrough_rebuild_v1(varchar,varchar)",
        "caseops_readthrough_mark_v1()",
        "caseops_readthrough_finalize_v1()",
        "caseops_readthrough_truncate_v1()",
    ]:
        statements.append(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    return statements


def install(connection):
    if connection.dialect.name == "sqlite":
        return  # SQLite canonical reads; no JSON copy/new legacy-write restriction.
    if connection.dialect.name != "postgresql":
        raise RuntimeError("Retained read pages require a reviewed database dialect.")
    for statement in postgres_statements():
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})


def backfill(connection):
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""DO $backfill$ DECLARE target record; BEGIN
          PERFORM pg_advisory_xact_lock(1145393713,0);
          FOR target IN SELECT id,company_id FROM public.matters ORDER BY company_id,id
          LOOP PERFORM public.caseops_readthrough_rebuild_v1(target.company_id,target.id); END LOOP;
        END $backfill$""")


def install_model_schema(metadata, connection, **kw):
    created = {table.name for table in kw.get("tables", ())}
    if DIRTY in created and set(FAMILIES.values()).issubset(created):
        if connection.dialect.name == "postgresql":
            names = ",".join("public." + table for table in sorted(SOURCE_TABLES))
            connection.exec_driver_sql("LOCK TABLE " + names + " IN SHARE ROW EXCLUSIVE MODE")
        install(connection)
        backfill(connection)
