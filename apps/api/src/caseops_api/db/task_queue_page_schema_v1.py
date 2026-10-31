"""Immutable version-one SQL shared by the closed migration and current model hook.

After publication, changes require a new helper version and forward migration.
Migration0006 verifies and compiles these exact source bytes before any SQL.

Statement transition tables collect old/new scopes without shared group locks.
The initially deferred finalizer takes every transaction scope in sorted order.
No Matter/Member row lock or parent FK is added. SQL source writers,
including compatibility writers and FK cascades, all meet the same triggers.
SET CONSTRAINTS IMMEDIATE followed by more source writes still needs explicit
concurrency proof; this source is not release acceptance.
"""

import re

SLOTS = 25
TASK_FIELDS = ("id", "title", "status", "priority", "due_on", "created_at", "updated_at")
GROUPS = "matter_task_queue_groups"
PAGES = "matter_task_queue_pages"
FINALIZE_GATE_NAMESPACE = 1145393713  # DER1, shared with counsel0005; COMMIT-only.
LOCK_NAMESPACE = 1297371441  # MTQ1; disjoint from counsel CPG1/CUN1.
ELIGIBLE = """company_id IS NOT NULL AND matter_id IS NOT NULL
AND ip_docket_id IS NULL AND status IN ('todo', 'in_progress', 'blocked')
AND cancelled_by_matter_disposal = false AND neutralized_at IS NULL
AND neutralized_by_ip_lifecycle_event_id IS NULL
AND neutralized_by_ip_lifecycle_version IS NULL"""
ORDER = "(due_on IS NULL), due_on, created_at, id"
SCOPE = (
    "company_id = p_company AND matter_id = p_matter "
    "AND owner_membership_id IS NOT DISTINCT FROM p_owner"
)


def packed_insert_sql(group_expression, predicate):
    """Complete group snapshot, dense fixed slots; source fields are never cut."""
    columns = [
        "group_id",
        "page_no",
        "entry_count",
        "has_dated",
        "has_undated",
        "min_dated",
        "max_dated",
        "last_null",
        "last_date",
        "last_created",
        "last_id",
    ]
    # MAX selects the one highest ordinal in each page, not independent fields.
    edge = "ordinal = ((ordinal / 25) * 25 + page_count - 1)"
    expressions = [
        group_expression,
        "ordinal / 25",
        "count(*)",
        "count(due_on) > 0",
        "count(*) > count(due_on)",
        "min(due_on)",
        "max(due_on)",
        f"max(CASE WHEN {edge} THEN CASE WHEN due_on IS NULL THEN 1 ELSE 0 END END) = 1",
        f"max(CASE WHEN {edge} THEN coalesce(due_on, '0001-01-01') END)",
        f"max(CASE WHEN {edge} THEN created_at END)",
        f"max(CASE WHEN {edge} THEN id END)",
    ]
    for slot in range(SLOTS):
        for name in TASK_FIELDS:
            columns.append(f"s{slot}_{name}")
            expressions.append(f"max(CASE WHEN ordinal % 25 = {slot} THEN {name} END)")
    ranked = (
        f"SELECT *, row_number() OVER (ORDER BY {ORDER}) - 1 AS ordinal "
        f"FROM matter_tasks WHERE {ELIGIBLE} AND ({predicate})"
    )
    counted = (
        "SELECT *, count(*) OVER (PARTITION BY ordinal / 25) AS page_count "
        f"FROM ({ranked}) AS ranked_source"
    )
    return (
        f"INSERT INTO {PAGES} ({', '.join(columns)}) SELECT {', '.join(expressions)} "
        f"FROM ({counted}) AS dense_source GROUP BY ordinal / 25"
    )


def postgres_statements():
    pack = packed_insert_sql("v_group_id", SCOPE)
    statements = [
        f"""
CREATE FUNCTION caseops_refresh_task_queue_group(p_company text, p_matter text, p_owner text)
RETURNS void LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $queue$
DECLARE v_group_id bigint;
BEGIN
 IF p_company IS NULL OR p_matter IS NULL THEN RETURN; END IF;
 INSERT INTO {GROUPS} (company_id,matter_id,owner_is_null,owner_key)
 VALUES (p_company,p_matter,p_owner IS NULL,coalesce(p_owner,''))
 ON CONFLICT (company_id,matter_id,owner_is_null,owner_key) DO NOTHING;
 SELECT id INTO STRICT v_group_id FROM {GROUPS}
 WHERE company_id=p_company AND matter_id=p_matter
 AND owner_is_null=(p_owner IS NULL) AND owner_key=coalesce(p_owner,'');
 DELETE FROM {PAGES} WHERE {PAGES}.group_id=v_group_id;
 {pack};
 IF NOT EXISTS (SELECT 1 FROM {PAGES} WHERE {PAGES}.group_id=v_group_id) THEN
  DELETE FROM {GROUPS} WHERE id=v_group_id;
 END IF;
END;
$queue$
"""
    ]
    statements.append(f"""
CREATE FUNCTION caseops_finalize_task_queue() RETURNS trigger
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $queue$
DECLARE scope record; actual_key integer;
BEGIN
 -- Both queue0006 and counsel0005 take DER1 first at normal COMMIT, after
 -- canonical source/FK/audit writes. No source-phase projection gate is used.
 PERFORM pg_advisory_xact_lock({FINALIZE_GATE_NAMESPACE}, 0);
 FOR actual_key IN SELECT DISTINCT hashtext(jsonb_build_array(
   company_id,matter_id,owner_is_null,owner_key)::text) AS lock_key
 FROM matter_task_queue_dirty WHERE transaction_id=txid_current() ORDER BY lock_key
 LOOP
  PERFORM pg_advisory_xact_lock({LOCK_NAMESPACE}, actual_key);
 END LOOP;
 FOR scope IN SELECT company_id,matter_id,owner_is_null,owner_key
 FROM matter_task_queue_dirty WHERE transaction_id=txid_current()
 ORDER BY company_id COLLATE "C",matter_id COLLATE "C",owner_is_null,owner_key COLLATE "C"
 LOOP
  PERFORM caseops_refresh_task_queue_group(scope.company_id,scope.matter_id,
    CASE WHEN scope.owner_is_null THEN NULL ELSE scope.owner_key END);
 END LOOP;
 DELETE FROM matter_task_queue_dirty WHERE transaction_id=txid_current();
 RETURN NULL;
END;
$queue$
""")
    statements.append(
        "CREATE CONSTRAINT TRIGGER trg_task_queue_finalize AFTER INSERT ON matter_task_queue_dirty "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION caseops_finalize_task_queue()"
    )
    for operation, sources in (
        ("insert", ["new_tasks"]),
        ("update", ["old_tasks", "new_tasks"]),
        ("delete", ["old_tasks"]),
    ):
        unions = " UNION ".join(
            f"SELECT company_id,matter_id,owner_membership_id FROM {source} "
            "WHERE company_id IS NOT NULL AND matter_id IS NOT NULL"
            for source in sources
        )
        statements.append(f"""
CREATE FUNCTION caseops_task_queue_{operation}() RETURNS trigger
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $queue$
BEGIN
 INSERT INTO matter_task_queue_dirty (transaction_id,company_id,matter_id,owner_is_null,owner_key)
 SELECT txid_current(),company_id,matter_id,owner_membership_id IS NULL,
 coalesce(owner_membership_id,'')
 FROM ({unions}) AS affected ON CONFLICT DO NOTHING;
 RETURN NULL;
END;
$queue$
""")
        referencing = {
            "insert": "NEW TABLE AS new_tasks",
            "update": "OLD TABLE AS old_tasks NEW TABLE AS new_tasks",
            "delete": "OLD TABLE AS old_tasks",
        }[operation]
        statements.append(
            f"CREATE TRIGGER trg_task_queue_{operation} AFTER {operation.upper()} ON matter_tasks "
            f"REFERENCING {referencing} FOR EACH STATEMENT "
            f"EXECUTE FUNCTION caseops_task_queue_{operation}()"
        )
    statements.append(f"""CREATE FUNCTION caseops_task_queue_truncate() RETURNS trigger
LANGUAGE plpgsql VOLATILE SET search_path=pg_catalog,public AS $queue$
BEGIN
 DELETE FROM {PAGES}; DELETE FROM {GROUPS}; DELETE FROM matter_task_queue_dirty;
 RETURN NULL;
END; $queue$""")
    statements.append(
        "CREATE TRIGGER trg_task_queue_truncate AFTER TRUNCATE ON matter_tasks "
        "FOR EACH STATEMENT EXECUTE FUNCTION caseops_task_queue_truncate()"
    )
    names = (
        "matter_tasks",
        "matter_task_queue_groups",
        "matter_task_queue_pages",
        "matter_task_queue_dirty",
        "caseops_refresh_task_queue_group",
        "caseops_finalize_task_queue",
        "caseops_task_queue_insert",
        "caseops_task_queue_update",
        "caseops_task_queue_delete",
        "caseops_task_queue_truncate",
    )
    for name in names:
        statements = [re.sub(rf"\b{name}\b", f"public.{name}", sql) for sql in statements]
    # Trigger/helper invocation belongs to the migration/application owner.
    # No new public database entry point is needed for these invoker functions.
    for signature in (
        "caseops_refresh_task_queue_group(text,text,text)",
        "caseops_finalize_task_queue()",
        "caseops_task_queue_insert()",
        "caseops_task_queue_update()",
        "caseops_task_queue_delete()",
        "caseops_task_queue_truncate()",
    ):
        statements.append(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
    return statements


def sqlite_statements():
    statements = []
    for operation, labels in (
        ("INSERT", ("NEW",)),
        ("UPDATE", ("OLD", "NEW")),
        ("DELETE", ("OLD",)),
    ):
        chunks = []
        for label in labels:
            valid = f"{label}.company_id IS NOT NULL AND {label}.matter_id IS NOT NULL"
            target = (
                f"company_id={label}.company_id AND matter_id={label}.matter_id "
                f"AND owner_is_null=({label}.owner_membership_id IS NULL) "
                f"AND owner_key=coalesce({label}.owner_membership_id,'')"
            )
            group = f"(SELECT id FROM {GROUPS} WHERE {target})"
            source = (
                f"company_id={label}.company_id AND matter_id={label}.matter_id "
                f"AND owner_membership_id IS {label}.owner_membership_id"
            )
            chunks.extend(
                [
                    f"INSERT OR IGNORE INTO {GROUPS} "
                    "(company_id,matter_id,owner_is_null,owner_key) "
                    f"SELECT {label}.company_id,{label}.matter_id,"
                    f"{label}.owner_membership_id IS NULL,"
                    f"coalesce({label}.owner_membership_id,'') WHERE {valid}",
                    f"DELETE FROM {PAGES} WHERE group_id={group}",
                    packed_insert_sql(group, source),
                    f"DELETE FROM {GROUPS} WHERE {target} AND NOT EXISTS "
                    f"(SELECT 1 FROM {PAGES} WHERE group_id={GROUPS}.id)",
                ]
            )
        statements.append(
            f"CREATE TRIGGER trg_task_queue_{operation.lower()} "
            f"AFTER {operation} ON matter_tasks BEGIN " + ";\n".join(chunks) + "; END"
        )
    return statements


def install(connection):
    statements = (
        postgres_statements() if connection.dialect.name == "postgresql" else sqlite_statements()
    )
    if connection.dialect.name not in {"postgresql", "sqlite"}:
        raise RuntimeError("Task queue pages require a reviewed database dialect.")
    for statement in statements:
        # Raw DDL has SQL modulo percent signs, never driver placeholders.
        # Empty DBAPI parameter collections would make psycopg parse those signs.
        connection.exec_driver_sql(statement, execution_options={"no_parameters": True})


def backfill(connection):
    """Run only while migration owns the source write fence."""
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql("""DO $queue$ DECLARE scope record; BEGIN
FOR scope IN SELECT DISTINCT company_id,matter_id,owner_membership_id FROM public.matter_tasks
WHERE company_id IS NOT NULL AND matter_id IS NOT NULL
ORDER BY company_id,matter_id,owner_membership_id NULLS FIRST LOOP
 PERFORM public.caseops_refresh_task_queue_group(
  scope.company_id,scope.matter_id,scope.owner_membership_id);
END LOOP; END; $queue$""")
    else:
        # Read-only source discovery, no id=id update that could activate an
        # unrelated retained source trigger or timestamp writer.
        rows = connection.exec_driver_sql(
            "SELECT DISTINCT company_id,matter_id,owner_membership_id "
            f"FROM matter_tasks WHERE {ELIGIBLE}"
        ).all()
        for company, matter, owner in rows:
            params = {
                "company": company,
                "matter": matter,
                "owner": owner,
                "owner_null": owner is None,
                "owner_key": owner or "",
            }
            connection.exec_driver_sql(
                f"INSERT OR IGNORE INTO {GROUPS} "
                "(company_id,matter_id,owner_is_null,owner_key) "
                "VALUES (:company,:matter,:owner_null,:owner_key)",
                params,
            )
            params["group_id"] = connection.exec_driver_sql(
                f"SELECT id FROM {GROUPS} WHERE company_id=:company AND matter_id=:matter "
                "AND owner_is_null=:owner_null AND owner_key=:owner_key",
                params,
            ).scalar_one()
            connection.exec_driver_sql(f"DELETE FROM {PAGES} WHERE group_id=:group_id", params)
            connection.exec_driver_sql(
                packed_insert_sql(
                    ":group_id",
                    "company_id=:company AND matter_id=:matter AND owner_membership_id IS :owner",
                ),
                params,
            )


def install_model_schema(metadata, connection, **kw):
    names = set(metadata.tables)
    created = {table.name for table in kw.get("tables", ())}
    if {"matter_tasks", GROUPS, PAGES} <= names and PAGES in created:
        if connection.dialect.name == "postgresql":
            connection.exec_driver_sql("LOCK TABLE matter_tasks IN SHARE ROW EXCLUSIVE MODE")
        install(connection)
        backfill(connection)
