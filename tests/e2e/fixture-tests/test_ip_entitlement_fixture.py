"""Local E2E fixture DB-API/ORM parity; PostgreSQL is an explicit manual opt-in."""
from __future__ import annotations

import builtins
from contextlib import redirect_stdout
from datetime import UTC, datetime
import io
from itertools import count
import json
import os
from pathlib import Path
import re
import runpy
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine, event, func, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from caseops_api.db import models as m
from caseops_api.services.saas_billing import current_entitlements_for_company


REPO = Path(os.environ.get("CASEOPS_IP_FIXTURE_SOURCE_ROOT", str(Path(__file__).resolve().parents[3]))).resolve(strict=True)
SUPPORT = Path(os.environ.get("CASEOPS_IP_FIXTURE_SUPPORT_ROOT",
    str(REPO / "tests/e2e/support")))
SCRIPT = SUPPORT / "ip_entitlement_fixture.py"


if Path(m.__file__).resolve() != REPO / "apps/api/src/caseops_api/db/models.py":
    raise RuntimeError("The ORM oracle resolved outside the explicitly selected source.")

BACKENDS = os.environ.get("CASEOPS_IP_FIXTURE_TEST_BACKENDS", "sqlite").split(",")
TENANT_SEQUENCE = count(int(time.time() * 1000))
if not BACKENDS or any(item not in {"sqlite", "postgresql"} for item in BACKENDS):
    raise RuntimeError("Explicit sqlite/postgresql backend selection is required.")


@pytest.fixture(autouse=True)
def clean_libpq(monkeypatch):
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            monkeypatch.delenv(key)
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.delenv("CASEOPS_E2E_DOCKER_PROJECT", raising=False)


@pytest.fixture
def fixture_script(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(SCRIPT))
    namespace = namespace["main"].__globals__
    root = tmp_path / "owned checkout with spaces"
    root.mkdir()
    namespace["__file__"] = str(root / "tests/e2e/support/ip_entitlement_fixture.py")
    namespace["STARTED"] = time.monotonic()
    return SimpleNamespace(ns=namespace, root=root)


def invoke(fixture_script, monkeypatch, scope, database):
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(scope).encode())))
    fixture_script.ns["STARTED"] = time.monotonic()
    output = io.StringIO()
    with redirect_stdout(output):
        code = fixture_script.ns["main"]()
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    return code, events


def canonical_tables():
    requested = [m.Company, m.User, m.CompanyMembership, m.BillingSubscription,
                 m.BillingSubscriptionItem, m.BillingPlanPrice, m.BillingPlanEntitlement]
    tables = set()

    def visit(table):
        if table in tables:
            return
        tables.add(table)
        for foreign_key in table.foreign_keys:
            visit(foreign_key.column.table)

    for model in requested:
        visit(model.__table__)
    return sorted(tables, key=lambda table: table.name)


@pytest.fixture(scope="session", params=BACKENDS)
def database_storage(request, tmp_path_factory):
    backend = request.param
    root = tmp_path_factory.mktemp("owned checkout with spaces")
    if backend == "sqlite":
        url = "sqlite+pysqlite:///" + (root / "caseops-e2e.db").as_posix()
        engine = create_engine(url, hide_parameters=True)

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    else:
        url = os.environ.get("CASEOPS_IP_FIXTURE_TEST_POSTGRES_URL", "")
        # Validate before SQLAlchemy can connect. No shared app DB/schema is allowed.
        runpy.run_path(str(SCRIPT))["validate_database"](url)
        name = urlsplit(url).path.removeprefix("/")
        if (not re.fullmatch(r"ip_fixture_test_[a-f0-9]{12}", name)
                or os.environ.get("CASEOPS_IP_FIXTURE_TEST_POSTGRES_DATABASE") != name):
            pytest.fail("An explicitly owned fresh ip_fixture_test_<12hex> database is required.")
        engine = create_engine(url, hide_parameters=True, connect_args={"connect_timeout": 3})
    tables = canonical_tables()
    try:
        if backend == "postgresql":
            schemas = inspect(engine).get_schema_names()
            if any(name not in {"public", "information_schema"} and not name.startswith("pg_") for name in schemas):
                pytest.fail("Refusing a database with noncanonical user schemas.")
        if inspect(engine).get_table_names():
            pytest.fail("Refusing a nonempty fixture database; no DDL or cleanup was authorized.")
        m.Base.metadata.create_all(engine, tables=tables)
        yield SimpleNamespace(engine=engine, url=url, backend=backend, tables=tables, root=root)
    finally:
        # Dispose only. A failed run retains its owned schema/rows for diagnosis.
        # Each backend uses one fresh database; cases use disjoint tenant IDs.
        engine.dispose()


@pytest.fixture
def database(database_storage, fixture_script):
    fixture_script.root = database_storage.root
    fixture_script.ns["__file__"] = str(database_storage.root / "tests/e2e/support/ip_entitlement_fixture.py")
    return database_storage


def seed(database):
    suffix = uuid4().hex[:5]
    slug = f"intelligent-review-{next(TENANT_SEQUENCE)}-{suffix}"
    scope = {"company_id": str(uuid4()), "membership_id": str(uuid4()),
             "user_id": str(uuid4()), "slug": slug, "email": f"owner-{slug}@example.com"}
    with Session(database.engine) as session:
        session.add(m.Company(id=scope["company_id"], name="IPLF 063B Intelligent Review LLP",
                              slug=slug, tenant_key=slug, company_type="law_firm"))
        session.add(m.User(id=scope["user_id"], email=scope["email"],
                           full_name="Intelligent Review Partner", password_hash="synthetic-unused-hash"))
        session.flush()
        session.add(m.CompanyMembership(id=scope["membership_id"], company_id=scope["company_id"],
                                        user_id=scope["user_id"], role="owner"))
        session.commit()
        assert session.scalar(select(func.count()).select_from(m.BillingSubscription)
                              .where(m.BillingSubscription.company_id == scope["company_id"])) == 0
    return scope


def rows(database, company_id):
    with database.engine.connect() as connection:
        return [dict(row) for row in connection.execute(select(m.BillingSubscription.__table__)
                    .where(m.BillingSubscription.company_id == company_id)).mappings()]


def effective(database, company_id):
    with Session(database.engine) as session:
        return current_entitlements_for_company(session, company_id)


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def test_original_orm_defaults_sql_null_and_effective_entitlement_parity(database, fixture_script, monkeypatch):
    original, replacement = seed(database), seed(database)
    before = datetime.now(UTC)
    with Session(database.engine) as session:
        # Literal original constructor: no copied defaults in the test oracle.
        session.add(m.BillingSubscription(company_id=original["company_id"], status="manual_active",
            segment="law_firm", source="iplf_063b_playwright", externally_billable=False,
            entitlement_overrides_json={"ip_workspace": True}))
        session.commit()
    code, events = invoke(fixture_script, monkeypatch, replacement, database.url)
    assert code == 0
    assert events[-1]["stage"] == "complete"
    after = datetime.now(UTC)
    old, new = rows(database, original["company_id"])[0], rows(database, replacement["company_id"])[0]
    expected_columns = {column.name for column in m.BillingSubscription.__table__.columns}
    assert len(expected_columns) == 24
    assert set(old) == set(new) == expected_columns
    volatile = {"id", "company_id", "created_at", "updated_at"}
    assert {key: old[key] for key in old.keys() - volatile} == {key: new[key] for key in new.keys() - volatile}
    for row in (old, new):
        assert UUID(row["id"]).version == 4
        assert before <= utc(row["created_at"]) <= utc(row["updated_at"]) <= after
        assert row["billing_interval"] == "month"
        assert row["cancel_at_period_end"] is False
        assert row["externally_billable"] is False
        assert row["entitlement_overrides_json"] == {"ip_workspace": True}
        assert row["metadata_json"] is None
        with database.engine.connect() as connection:
            is_sql_null = connection.execute(select(m.BillingSubscription.metadata_json.is_(None))
                .where(m.BillingSubscription.id == row["id"])).scalar_one()
        assert is_sql_null is True  # JSON null must not satisfy this assertion.
    assert effective(database, original["company_id"]) == effective(database, replacement["company_id"]) == {"ip_workspace": True}
    with database.engine.connect() as connection:
        for table in (m.BillingAccount.__table__, m.BillingSubscriptionItem.__table__):
            assert connection.scalar(select(func.count()).select_from(table)) == 0


@pytest.mark.parametrize("status", ["active", "trialing", "grace", "manual_active"])
def test_duplicate_fails_without_overwriting_any_retained_field(database, fixture_script, monkeypatch, status):
    scope = seed(database)
    with Session(database.engine) as session:
        session.add(m.BillingSubscription(company_id=scope["company_id"], status=status,
            segment="law_firm", source="retained-offline", externally_billable=True,
            entitlement_overrides_json={"ip_workspace": False}, metadata_json={"retained": [1, "exact"]}))
        session.commit()
    before = rows(database, scope["company_id"])
    code, events = invoke(fixture_script, monkeypatch, scope, database.url)
    assert code == 1
    assert not any(item["stage"] == "complete" for item in events)
    assert rows(database, scope["company_id"]) == before


def test_repeat_of_successful_fixture_is_not_an_upsert(database, fixture_script, monkeypatch):
    scope = seed(database)
    first = invoke(fixture_script, monkeypatch, scope, database.url)
    assert first[0] == 0
    before = rows(database, scope["company_id"])
    second = invoke(fixture_script, monkeypatch, scope, database.url)
    assert second[0] == 1
    assert rows(database, scope["company_id"]) == before


def test_inactive_history_is_retained_when_new_fixture_is_admitted(database, fixture_script, monkeypatch):
    scope = seed(database)
    with Session(database.engine) as session:
        session.add(m.BillingSubscription(company_id=scope["company_id"], status="cancelled",
            segment="law_firm", source="retained-history", metadata_json={"do_not_touch": True}))
        session.commit()
    historical = rows(database, scope["company_id"])[0]
    result = invoke(fixture_script, monkeypatch, scope, database.url)
    assert result[0] == 0
    after = rows(database, scope["company_id"])
    assert len(after) == 2 and historical in after


def test_admission_rechecks_scope_after_initial_select(database, fixture_script):
    scope = seed(database)
    raw = database.engine.raw_connection()

    class Cursor:
        def __init__(self): self.inner = raw.cursor()
        def __enter__(self): return self
        def __exit__(self, *_args): self.close()
        def execute(self, sql, params): return self.inner.execute(sql, params)
        def fetchone(self):
            row = self.inner.fetchone()
            assert row == (scope["company_id"],)
            self.inner.fetchall()  # Exhaust the LIMIT-1 SQLite statement before the independent writer.
            with database.engine.begin() as connection:
                connection.execute(m.Company.__table__.update().where(m.Company.id == scope["company_id"])
                                   .values(is_active=False))
            return row
        @property
        def rowcount(self): return self.inner.rowcount
        def close(self): self.inner.close()

    try:
        with pytest.raises(fixture_script.ns["FixtureRejected"]):
            fixture_script.ns["grant"](SimpleNamespace(cursor=Cursor, commit=raw.commit), database.backend, scope)
        raw.rollback()
    finally:
        raw.close()
    assert rows(database, scope["company_id"]) == []


@pytest.mark.parametrize("model,column,value", [
    ("Company", "slug", "not-the-fixture"), ("Company", "tenant_key", "wrong-key"),
    ("Company", "name", "Unowned company"), ("Company", "company_type", "corporate_legal"),
    ("Company", "is_active", False), ("CompanyMembership", "role", "admin"),
    ("CompanyMembership", "is_active", False), ("User", "email", "unowned@example.com"),
    ("User", "full_name", "Other Owner"), ("User", "is_active", False),
])
def test_persisted_scope_mismatch_rejects_without_insert(database, fixture_script, monkeypatch, model, column, value):
    scope = seed(database)
    table = getattr(m, model).__table__
    key = {"Company": "company_id", "CompanyMembership": "membership_id", "User": "user_id"}[model]
    with database.engine.begin() as connection:
        connection.execute(table.update().where(table.c.id == scope[key]).values({column: value}))
    result = invoke(fixture_script, monkeypatch, scope, database.url)
    assert result[0] == 1
    assert rows(database, scope["company_id"]) == []


@pytest.mark.parametrize("key", ["company_id", "membership_id", "user_id"])
def test_foreign_identity_is_not_a_synthetic_scope(database, fixture_script, monkeypatch, key):
    scope, foreign = seed(database), seed(database)
    target = scope["company_id"]
    scope[key] = foreign[key]
    result = invoke(fixture_script, monkeypatch, scope, database.url)
    assert result[0] == 1
    assert rows(database, target) == rows(database, foreign["company_id"]) == []


def test_actual_foreign_keys_reject_dangling_subscription_and_membership(database):
    scope = seed(database)
    with Session(database.engine) as session:
        session.add(m.BillingSubscription(company_id=str(uuid4()), status="manual_active", segment="law_firm"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
        session.add(m.CompanyMembership(company_id=str(uuid4()), user_id=scope["user_id"], role="owner"))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    assert rows(database, scope["company_id"]) == []


def test_main_inserts_with_database_fk_enforcement(database, fixture_script, monkeypatch):
    scope = seed(database)
    if database.backend != "sqlite":
        result = invoke(fixture_script, monkeypatch, scope, database.url)
        assert result[0] == 0
        assert rows(database, scope["company_id"])[0]["company_id"] == scope["company_id"]
        foreign_keys = inspect(database.engine).get_foreign_keys("billing_subscriptions")
        assert any(key["referred_table"] == "companies" for key in foreign_keys)
        return
    import sqlite3
    seen = []
    original_connect = sqlite3.connect

    class Connection(sqlite3.Connection):
        def close(self):
            seen.append(self.execute("PRAGMA foreign_keys").fetchone()[0])
            super().close()

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=Connection)

    monkeypatch.setattr(sqlite3, "connect", connect)
    result = invoke(fixture_script, monkeypatch, scope, database.url)
    assert result[0] == 0
    assert seen == [1]


def test_sql_injection_is_bound_data_not_statement_text(database, fixture_script):
    scope = seed(database)
    scope["slug"] = "x'); DROP TABLE companies; --"
    recorded = []

    def capture(_connection, _cursor, sql, params, _context, _many):
        recorded.append((sql, params))

    event.listen(database.engine, "before_cursor_execute", capture)
    raw = database.engine.raw_connection()
    try:
        with pytest.raises(fixture_script.ns["FixtureRejected"]):
            fixture_script.ns["grant"](raw, database.backend, scope)
        raw.rollback()
    finally:
        raw.close()
        event.remove(database.engine, "before_cursor_execute", capture)
    # raw_connection bypasses SQLAlchemy observers: use an actual cursor spy too.
    class SpyCursor:
        def __enter__(self): return self
        def __exit__(self, *_args): self.close()
        def execute(self, sql, params):
            recorded.append((sql, params))
        def fetchone(self): return None
        def close(self): return None
    with pytest.raises(fixture_script.ns["FixtureRejected"]):
        fixture_script.ns["grant"](SimpleNamespace(cursor=SpyCursor), database.backend, scope)
    sql, params = recorded[-1]
    assert scope["slug"] not in sql and scope["slug"] in params
    assert "DROP TABLE" not in sql
    assert inspect(database.engine).has_table("companies")
    assert rows(database, scope["company_id"]) == []


UNSAFE_URLS = [
    "postgresql+psycopg://u:p@cloud.example/db", "postgresql+psycopg://u:p@/cloudsql/project/db",
    "postgresql+psycopg://u:p@localhost/db?host=cloud.example",
    "postgresql+psycopg://u:p@localhost/db?hostaddr=203.0.113.1",
    "postgresql+psycopg://u:p@localhost/db?service=cloud", "postgresql+psycopg://u:p@localhost/db#x",
    "postgresql+psycopg://u:p@localhost/db?", "postgresql+psycopg://u:p@localhost:0/db",
    "postgresql+psycopg://u:p@localhost:65536/db", "postgresql+psycopg://u:p@127%2E0%2E0%2E1/db",
    "postgresql+psycopg://u:p@localhost,cloud.example/db", "postgresql+psycopg2://u:p@localhost/db",
    "postgresql+psycopg://localhost/db", "postgresql+psycopg://u@localhost/db",
    "sqlite+pysqlite:///:memory:", "sqlite+pysqlite:///foreign.db",
    "sqlite+pysqlite:///file:foreign.db?uri=true",
]


@pytest.mark.parametrize("url", UNSAFE_URLS)
def test_unsafe_url_rejected_before_driver_import_or_connect(fixture_script, monkeypatch, url):
    calls = []
    original_import = builtins.__import__

    def refuse_driver(name, *args, **kwargs):
        if name in {"psycopg", "sqlite3"}:
            calls.append(name)
            raise AssertionError("Unsafe URL reached a database driver.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_driver)
    valid = {"company_id": str(uuid4()), "membership_id": str(uuid4()), "user_id": str(uuid4()),
             "slug": "intelligent-review-1793200000000-abcde",
             "email": "owner-intelligent-review-1793200000000-abcde@example.com"}
    code, events = invoke(fixture_script, monkeypatch, valid, url)
    assert code == 1 and calls == []
    assert [(event["stage"], event["event"]) for event in events] == [("validate", "begin"), ("validate", "failed")]


@pytest.mark.parametrize("key", ["company_id", "membership_id", "user_id", "slug", "email"])
def test_injected_input_rejected_before_connect(fixture_script, monkeypatch, key):
    scope = {"company_id": str(uuid4()), "membership_id": str(uuid4()), "user_id": str(uuid4()),
             "slug": "intelligent-review-1793200000000-abcde",
             "email": "owner-intelligent-review-1793200000000-abcde@example.com"}
    scope[key] = "x'; DROP TABLE companies; --"
    calls = []
    original_import = builtins.__import__

    def refuse_driver(name, *args, **kwargs):
        if name in {"psycopg", "sqlite3"}:
            calls.append(name)
            raise AssertionError("Injected input reached a driver.")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", refuse_driver)
    code, events = invoke(fixture_script, monkeypatch, scope, "postgresql+psycopg://u:p@localhost/test_db")
    assert code == 1 and calls == []
    assert events[-1]["stage"] == "validate" and events[-1]["event"] == "failed"


def test_checkout_sqlite_missing_foreign_link_and_docker_guards(fixture_script, monkeypatch):
    expected = fixture_script.root / "caseops-e2e.db"
    validate = fixture_script.ns["validate_database"]
    url = "sqlite+pysqlite:///" + expected.as_posix()
    with pytest.raises((OSError, fixture_script.ns["FixtureRejected"])):
        validate(url)
    expected.touch()
    assert validate(url) == ("sqlite", expected)
    monkeypatch.setenv("CASEOPS_E2E_DOCKER_PROJECT", "owned-docker")
    with pytest.raises(fixture_script.ns["FixtureRejected"]):
        validate(url)
    monkeypatch.delenv("CASEOPS_E2E_DOCKER_PROJECT")
    foreign = fixture_script.root / "foreign.db"
    foreign.write_bytes(b"retain-this-sentinel")
    with pytest.raises(fixture_script.ns["FixtureRejected"]):
        validate("sqlite+pysqlite:///" + foreign.as_posix())
    alias = fixture_script.root / "alias.db"
    os.link(expected, alias)
    with pytest.raises(fixture_script.ns["FixtureRejected"]):
        validate(url)
    assert foreign.read_bytes() == b"retain-this-sentinel"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "[::1]"])
def test_loopback_keywords_are_explicit_and_cannot_use_pgpass(fixture_script, host):
    dialect, options = fixture_script.ns["validate_database"](f"postgresql+psycopg://u:p%40ss@{host}:5432/test_db")
    assert dialect == "postgresql"
    assert options["hostaddr"] in {"127.0.0.1", "::1"}
    assert options["password"] == "p@ss" and options["passfile"] == os.devnull
    assert options["connect_timeout"] == 3 and options["sslmode"] == "disable"


def test_ambient_libpq_override_rejected(fixture_script, monkeypatch):
    monkeypatch.setenv("PGSERVICE", "must-not-load")
    with pytest.raises(fixture_script.ns["FixtureRejected"]):
        fixture_script.ns["validate_database"]("postgresql+psycopg://u:p@localhost/test_db")
