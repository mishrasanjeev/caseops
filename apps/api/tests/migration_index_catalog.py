"""Historical schema catalogs: compare the dated database, never moving models."""

import json

from sqlalchemy import text


def schema_catalog(engine):
    """Capture complete SQLite DDL or PostgreSQL public schema definitions/state.

    Row data is retained separately by each journey. PostgreSQL physical OIDs
    and mutable sequence values are deliberately not schema definitions; each
    owned index's restart identity is checked independently by the journey.
    """
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            rows = connection.execute(
                text("SELECT type,tbl_name,name,sql FROM sqlite_master ORDER BY type,tbl_name,name")
            ).all()
            return {tuple(row[:3]): tuple(row[3:]) for row in rows}
        assert engine.dialect.name == "postgresql"
        queries = {
            "relation": (
                "SELECT c.relname,'',c.relkind,c.relpersistence,c.relrowsecurity,"
                "c.relforcerowsecurity,CASE WHEN c.relkind IN ('v','m') "
                "THEN pg_get_viewdef(c.oid,false) ELSE NULL END "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','S','f')"
            ),
            "column": (
                "SELECT c.relname,a.attnum::text,a.attname,format_type(a.atttypid,a.atttypmod),"
                "a.attnotnull,a.attidentity,a.attgenerated,a.attcollation::regcollation::text,"
                "pg_get_expr(d.adbin,d.adrelid) FROM pg_attribute a "
                "JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "LEFT JOIN pg_attrdef d ON d.adrelid=a.attrelid AND d.adnum=a.attnum "
                "WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f') "
                "AND a.attnum>0 AND NOT a.attisdropped"
            ),
            "constraint": (
                "SELECT c.relname,k.conname,k.contype,pg_get_constraintdef(k.oid,false),"
                "k.convalidated "
                "FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'"
            ),
            "index": (
                "SELECT t.relname,c.relname,pg_get_indexdef(i.indexrelid),"
                "i.indisvalid,i.indisready,i.indislive,i.indisunique,"
                "i.indisprimary,i.indisexclusion "
                "FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid "
                "JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                "WHERE n.nspname='public'"
            ),
            "trigger": (
                "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid,false),t.tgenabled "
                "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public' AND NOT t.tgisinternal"
            ),
            "function": (
                "SELECT p.oid::regprocedure::text,'',pg_get_functiondef(p.oid) "
                "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname='public' AND p.prokind IN ('f','p','w')"
            ),
            "policy": (
                "SELECT c.relname,p.polname,p.polcmd,p.polpermissive,p.polroles::text,"
                "pg_get_expr(p.polqual,p.polrelid),pg_get_expr(p.polwithcheck,p.polrelid) "
                "FROM pg_policy p JOIN pg_class c ON c.oid=p.polrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'"
            ),
            "sequence": (
                "SELECT c.relname,'',s.seqtypid::regtype::text,s.seqstart,s.seqincrement,"
                "s.seqmax,s.seqmin,s.seqcache,s.seqcycle FROM pg_sequence s "
                "JOIN pg_class c ON c.oid=s.seqrelid JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname='public'"
            ),
        }
        result = {}
        for kind, sql in queries.items():
            rows = connection.execute(text(sql)).all()
            for row in rows:
                key = (kind, *row[:2])
                assert key not in result, ("DUPLICATE_SCHEMA_OBJECT", key)
                if kind == "index":
                    assert all(row[3:6]), ("INVALID_OR_UNREADY_HISTORICAL_INDEX", key)
                result[key] = tuple(row[2:])
        assert result and any(key[0] == "index" for key in result)
        return result


def require_index_additions(before, after, expected):
    owned = {("index", table, name) for table, name, _ in expected}
    assert owned.isdisjoint(before), "OWNED_INDEX_ALREADY_IN_PARENT"
    assert set(after) == set(before) | owned, "UNEXPECTED_SCHEMA_ADDITION_OR_REMOVAL"
    assert {key: after[key] for key in before} == before, "HISTORICAL_SCHEMA_CHANGED"


def require_revision(engine, expected):
    with engine.connect() as connection:
        observed = list(connection.scalars(text("SELECT version_num FROM alembic_version")))
    assert observed == [expected], observed


def write_catalog(path, catalog, revision):
    path.write_text(
        json.dumps(
            {
                "revision": revision,
                "objects": [
                    {"identity": list(key), "definition": list(value)}
                    for key, value in sorted(catalog.items())
                ],
            },
            indent=2,
        )
        + "\n"
    )
