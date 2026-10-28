"""Historical counsel projection rehearsals, not current-model schema creation.

Every database starts at the literal 0004 boundary. PostgreSQL cases are
explicitly marked and use the existing isolated temporary-database fixture.
Forward reentry after a refused downgrade is not a backup/restore rehearsal.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.script import ScriptDirectory
from sqlalchemy import MetaData, Table, inspect, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import TextClause

from alembic import command
from caseops_api.db.models import (
    AuditEvent,
    DomainOutboxEvent,
    InAppNotification,
    NotificationDeliveryEvent,
    NotificationDeliveryIntent,
)
from tests.test_platform_console_migration import KINDS, fresh_engine, migration_config
from tests.test_postgres_validation import _seed_company, _seed_matter, _seed_membership

PREVIOUS = "20261027_0004"
HEAD = "20261027_0005"
NOW = datetime(2026, 10, 27, 6, 17, 19, 123456, tzinfo=UTC)
PAGE = "counsel_read_pages"
MEMBER = "counsel_read_page_members"
DIRTY = "counsel_read_page_dirty"
NEW_TABLES = {PAGE, MEMBER, DIRTY}
SOURCES = {
    "assignment": ("matter_outside_counsel_assignments", "internal_notes"),
    "spend": ("outside_counsel_spend_records", "notes"),
}
PRESERVED = (
    "companies",
    "matters",
    "users",
    "company_memberships",
    "outside_counsel",
    "matter_outside_counsel_assignments",
    "outside_counsel_spend_records",
    "audit_events",
    "domain_outbox_events",
    "in_app_notifications",
    "notification_delivery_intents",
    "notification_delivery_events",
)
OUTBOXES = PRESERVED[-5:]


def _canonical(value):
    return json.dumps(value, sort_keys=True, default=str)


def _reflected_value(value):
    # Inspector partial-index predicates are fresh TextClause objects on each
    # read. Preserve their exact SQL bytes, rather than compare object identity.
    if isinstance(value, TextClause):
        return {"reflected_text_clause": value.text}
    if isinstance(value, dict):
        return {key: _reflected_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_reflected_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_reflected_value(item) for item in value)
    return value


def test_reflected_catalog_preserves_exact_predicates_and_all_options():
    options = {
        "name": "retained_partial_index",
        "unique": True,
        "column_names": ["company_id", "id"],
        "dialect_options": {"sqlite_where": text("status = 'active'"), "include": ["name"]},
    }
    same = {
        **options,
        "dialect_options": {
            **options["dialect_options"],
            "sqlite_where": text("status = 'active'"),
        },
    }
    changed = {
        **options,
        "dialect_options": {
            **options["dialect_options"],
            "sqlite_where": text("status = 'revoked'"),
        },
    }
    assert _reflected_value(options) == _reflected_value(same)
    assert _reflected_value(options) != _reflected_value(changed)
    actual = _reflected_value(options)
    assert set(actual) == {"name", "unique", "column_names", "dialect_options"}
    assert actual["dialect_options"] == {
        "sqlite_where": {"reflected_text_clause": "status = 'active'"},
        "include": ["name"],
    }
    assert actual["unique"] is True and actual["column_names"] == ["company_id", "id"]


def _catalog(engine):
    """Complete live table/index/trigger/function catalog, including backing PKs."""
    schema = inspect(engine)
    tables = {}
    for name in sorted(schema.get_table_names()):
        tables[name] = {
            "columns": [
                {key: str(value) if key == "type" else value for key, value in c.items()}
                for c in schema.get_columns(name)
            ],
            "primary_key": schema.get_pk_constraint(name),
            "unique": sorted(schema.get_unique_constraints(name), key=_canonical),
            "checks": sorted(schema.get_check_constraints(name), key=_canonical),
            "foreign_keys": sorted(schema.get_foreign_keys(name), key=_canonical),
            "indexes": sorted(_reflected_value(schema.get_indexes(name)), key=_canonical),
        }
    with engine.connect() as connection:
        if engine.dialect.name == "postgresql":
            indexes = connection.execute(
                text(
                    "SELECT tablename,indexname,indexdef FROM pg_indexes "
                    "WHERE schemaname='public' ORDER BY tablename,indexname"
                )
            ).all()
            triggers = connection.execute(
                text(
                    "SELECT c.relname,t.tgname,pg_get_triggerdef(t.oid) "
                    "FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname='public' AND NOT t.tgisinternal "
                    "ORDER BY c.relname,t.tgname"
                )
            ).all()
            functions = connection.execute(
                text(
                    "SELECT p.proname,pg_get_function_identity_arguments(p.oid),"
                    "pg_get_functiondef(p.oid),p.proowner,r.rolname,p.prosecdef,"
                    "p.proconfig,p.proacl::text FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "JOIN pg_roles r ON r.oid=p.proowner "
                    "WHERE n.nspname='public' AND p.prokind IN ('f','p') "
                    "ORDER BY p.proname,pg_get_function_identity_arguments(p.oid)"
                )
            ).all()
            sequences = connection.execute(
                text(
                    "SELECT sequencename,data_type,start_value,min_value,max_value,"
                    "increment_by,cycle,cache_size FROM pg_sequences "
                    "WHERE schemaname='public' ORDER BY sequencename"
                )
            ).all()
        else:
            indexes = connection.execute(
                text(
                    "SELECT tbl_name,name,sql FROM sqlite_master "
                    "WHERE type='index' ORDER BY tbl_name,name"
                )
            ).all()
            triggers = connection.execute(
                text(
                    "SELECT tbl_name,name,sql FROM sqlite_master "
                    "WHERE type='trigger' ORDER BY tbl_name,name"
                )
            ).all()
            functions, sequences = [], []
    return {
        "tables": tables,
        "indexes": indexes,
        "triggers": triggers,
        "functions": functions,
        "sequences": sequences,
    }


def _rows(engine, names):
    """Retain every column; JSON is captured as stored text, not decoded equality."""
    result = {}
    schema = inspect(engine)
    with engine.connect() as connection:
        for name in names:
            columns = schema.get_columns(name)
            expressions = [
                f'CAST("{c["name"]}" AS TEXT) AS "{c["name"]}"'
                if "JSON" in str(c["type"]).upper()
                else f'"{c["name"]}"'
                for c in columns
            ]
            keys = schema.get_pk_constraint(name)["constrained_columns"]
            order = ",".join(f'"{key}"' for key in keys)
            assert order, "Every retained fixture table has an independent primary key"
            result[name] = connection.execute(
                text(f'SELECT {",".join(expressions)} FROM "{name}" ORDER BY {order}')
            ).all()
    return result


def _table(engine, name):
    return Table(name, MetaData(), autoload_with=engine)


def _insert_source(engine, kind, scope, number, *, note="retained source note"):
    identity = str(UUID(int=(0x100000 if kind == "assignment" else 0x200000) + number))
    counsel = str(uuid4())
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO outside_counsel "
                "(id,company_id,name,panel_status,created_at,updated_at) "
                "VALUES (:id,:company,:name,'active',:created,:created)"
            ),
            {
                "id": counsel,
                "company": scope["company"],
                "name": f"Literal retained {kind} counsel {number}",
                "created": NOW,
            },
        )
        values = {
            "id": identity,
            "company_id": scope["company"],
            "matter_id": scope["matter"],
            "counsel_id": counsel,
            "currency": "INR",
            "created_at": NOW,
            "updated_at": NOW,
        }
        if kind == "assignment":
            values.update(
                assigned_by_membership_id=scope["member"],
                role_summary="Historical external counsel",
                budget_amount_minor=12345,
                status="approved",
                internal_notes=note,
            )
        else:
            values.update(
                assignment_id=None,
                recorded_by_membership_id=scope["member"],
                invoice_reference=f"RETAINED-{number}",
                stage_label="Trial",
                description="Literal spend retaining paise",
                amount_minor=12345,
                approved_amount_minor=6789,
                status="approved",
                billed_on=NOW.date(),
                due_on=NOW.date() + timedelta(days=7),
                paid_on=None,
                notes=note,
            )
        source = _table(engine, SOURCES[kind][0])
        # This is the complete old-column writer; no projection model/default is used.
        connection.execute(source.insert().values(**values))
    return identity


def _seed(engine, *, count=27):
    with Session(engine) as session:
        company = _seed_company(session)
        member = _seed_membership(session, company)
        matter = _seed_matter(session, company)
        foreign_company = _seed_company(session)
        foreign_member = _seed_membership(session, foreign_company)
        foreign_matter = _seed_matter(session, foreign_company)
        session.add(
            AuditEvent(
                company_id=company,
                actor_type="membership",
                actor_membership_id=member,
                actor_label="Retained synthetic actor",
                matter_id=matter,
                action="counsel.fixture.retained",
                target_type="matter",
                target_id=matter,
                metadata_json='{"literal":"retained audit bytes"}',
                created_at=NOW,
            )
        )
        payload = {"literal": "retained neutral outbox", "no_paid_providers": True}
        session.add(
            DomainOutboxEvent(
                company_id=company,
                event_key="counsel-migration-retained-event",
                event_type="fixture.retained",
                schema_version=1,
                aggregate_type="matter",
                aggregate_id=matter,
                aggregate_version=1,
                occurred_at=NOW,
                effective_at=NOW,
                source_command_id="counsel-migration-retained-command",
                producer="offline-test",
                confidentiality="privileged",
                correlation_id="retained-correlation",
                payload_hash=hashlib.sha256(_canonical(payload).encode()).hexdigest(),
                payload_json=payload,
                expected_consumers_json=["offline-test-only"],
                state="retry_scheduled",
                next_attempt_at=NOW + timedelta(hours=1),
                attempts=1,
                max_attempts=3,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        notification = InAppNotification(
            company_id=company,
            recipient_membership_id=member,
            event_type="fixture.retained",
            source_type="matter",
            source_id=matter,
            matter_id=matter,
            title="Retained synthetic receipt",
            body="No transport invoked",
            status="unread",
            metadata_json={"literal": "original receipt"},
            created_at=NOW,
        )
        session.add(notification)
        session.flush()
        intent = NotificationDeliveryIntent(
            company_id=company,
            recipient_membership_id=member,
            matter_id=matter,
            in_app_notification_id=notification.id,
            channel="in_app",
            event_type="fixture.retained",
            source_type="matter",
            source_id=matter,
            idempotency_key="retained-counsel-intent",
            status="failed",
            attempts=1,
            max_attempts=3,
            metadata_json={"literal": "retained intent", "no_paid_providers": True},
            created_at=NOW,
            updated_at=NOW,
        )
        session.add(intent)
        session.flush()
        session.add(
            NotificationDeliveryEvent(
                company_id=company,
                intent_id=intent.id,
                event_type="fixture.retained",
                provider="offline-fixture",
                idempotency_key="retained-counsel-event",
                status="failed",
                applied_to_state=True,
                error_redacted="Retained synthetic failure",
                metadata_json={"literal": "original delivery evidence"},
                occurred_at=NOW,
                received_at=NOW,
            )
        )
        session.commit()
    scope = {"company": company, "member": member, "matter": matter}
    foreign = {"company": foreign_company, "member": foreign_member, "matter": foreign_matter}
    expected = {}
    for kind in SOURCES:
        # Deliberately insert in reverse order; the literal UUID order defines pages.
        expected[kind] = sorted(
            _insert_source(engine, kind, scope, n) for n in reversed(range(1, count + 1))
        )
        _insert_source(engine, kind, foreign, 900)
    return scope, expected


def _assert_projection(engine, kind, scope, expected):
    expected = sorted(expected)
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            actual = connection.execute(
                text(
                    "SELECT source_id,page_number,slot_number FROM counsel_read_page_members "
                    "WHERE company_id=:company AND matter_id=:matter AND record_kind=:kind "
                    "ORDER BY source_id"
                ),
                {**scope, "kind": kind},
            ).all()
            assert actual == [(identity, n // 25, n % 25) for n, identity in enumerate(expected)]
            assert connection.scalar(text("SELECT count(*) FROM counsel_read_pages")) == 0
        else:
            pages = connection.execute(
                text(
                    "SELECT min_id,max_id,page_number,record_count,payload "
                    "FROM counsel_read_pages WHERE company_id=:company AND matter_id=:matter "
                    "AND record_kind=:kind ORDER BY page_number"
                ),
                {**scope, "kind": kind},
            ).all()
            chunks = [expected[n : n + 25] for n in range(0, len(expected), 25)]
            assert [(p.min_id, p.max_id, p.page_number, p.record_count) for p in pages] == [
                (chunk[0], chunk[-1], n, len(chunk)) for n, chunk in enumerate(chunks)
            ]
            assert [[entry["id"] for entry in page.payload] for page in pages] == chunks
            for page in pages:
                assert all(
                    entry["company_id"] == scope["company"]
                    and entry["matter_id"] == scope["matter"]
                    for entry in page.payload
                )
                assert all(SOURCES[kind][1] not in entry for entry in page.payload)
            assert connection.scalar(text("SELECT count(*) FROM counsel_read_page_members")) == 0


def _assert_new_shape(engine, role_evidence_path):
    schema = inspect(engine)
    literal = {
        PAGE: {
            "pk": ["company_id", "matter_id", "record_kind", "max_id"],
            "columns": {
                "company_id",
                "matter_id",
                "record_kind",
                "max_id",
                "min_id",
                "page_number",
                "record_count",
                "payload",
            }
            | {f"note_{n:02}" for n in range(25)},
            "indexes": {"ix_counsel_read_pages_matter_id": (["matter_id"], False)},
            "checks": {
                "ck_counsel_page_kind",
                "ck_counsel_page_number",
                "ck_counsel_page_capacity",
            },
        },
        MEMBER: {
            "pk": ["company_id", "matter_id", "record_kind", "source_id"],
            "columns": {
                "company_id",
                "matter_id",
                "record_kind",
                "source_id",
                "page_number",
                "slot_number",
            },
            "indexes": {"ix_counsel_page_members_matter_id": (["matter_id"], False)},
            "checks": {
                "ck_counsel_member_kind",
                "ck_counsel_member_page_number",
                "ck_counsel_member_slot",
            },
        },
        DIRTY: {
            "pk": ["transaction_id", "record_kind", "company_id", "matter_id", "source_user_id"],
            "columns": {
                "transaction_id",
                "record_kind",
                "company_id",
                "matter_id",
                "source_user_id",
            },
            "indexes": {},
            "checks": {"ck_counsel_dirty_kind", "ck_counsel_dirty_scope"},
        },
    }
    for name, expected in literal.items():
        assert schema.get_pk_constraint(name)["constrained_columns"] == expected["pk"]
        assert {c["name"] for c in schema.get_columns(name)} == expected["columns"]
        assert schema.get_foreign_keys(name) == []
        assert schema.get_unique_constraints(name) == []
        # No blanket unique-index filtering: a surprise backing index also fails.
        assert {
            x["name"]: (x["column_names"], bool(x["unique"])) for x in schema.get_indexes(name)
        } == expected["indexes"]
        assert {x["name"] for x in schema.get_check_constraints(name)} == expected["checks"]
    notes = [c for c in schema.get_columns(PAGE) if c["name"].startswith("note_")]
    assert len(notes) == 25 and all(str(c["type"]) == "TEXT" and c["nullable"] for c in notes)
    if engine.dialect.name == "postgresql":
        with engine.connect() as connection:
            indexes = connection.execute(
                text(
                    "SELECT t.relname,i.relname,x.indisprimary,"
                    "x.indisunique,x.indisvalid,x.indisready "
                    "FROM pg_index x JOIN pg_class i ON i.oid=x.indexrelid "
                    "JOIN pg_class t ON t.oid=x.indrelid WHERE t.relname IN "
                    "('counsel_read_pages','counsel_read_page_members',"
                    "'counsel_read_page_dirty') "
                    "ORDER BY t.relname,i.relname"
                )
            ).all()
        assert indexes == [
            (DIRTY, DIRTY + "_pkey", True, True, True, True),
            (MEMBER, MEMBER + "_pkey", True, True, True, True),
            (MEMBER, "ix_counsel_page_members_matter_id", False, False, True, True),
            (PAGE, PAGE + "_pkey", True, True, True, True),
            (PAGE, "ix_counsel_read_pages_matter_id", False, False, True, True),
        ]
        with engine.connect() as connection:
            role = connection.execute(
                text(
                    "SELECT current_user,session_user,r.oid,current_setting('role') "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            ).one()
            table_owners = connection.execute(
                text(
                    "SELECT c.relname,c.relowner,r.rolname FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid=c.relnamespace "
                    "JOIN pg_roles r ON r.oid=c.relowner WHERE n.nspname='public' "
                    "AND c.relkind='r' AND c.relname IN "
                    "('counsel_read_pages','counsel_read_page_members',"
                    "'counsel_read_page_dirty') "
                    "ORDER BY c.relname"
                )
            ).all()
            functions = connection.execute(
                text(
                    "SELECT p.proname,p.oid,p.proowner,r.rolname,p.prosecdef,p.proconfig,"
                    "oidvectortypes(p.proargtypes),p.proacl IS NOT NULL,"
                    "EXISTS(SELECT 1 FROM aclexplode(coalesce(p.proacl,"
                    "acldefault('f',p.proowner))) "
                    "a WHERE a.grantee=0 AND a.privilege_type='EXECUTE'),"
                    "has_function_privilege(current_user,p.oid,'EXECUTE') "
                    "FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                    "JOIN pg_roles r ON r.oid=p.proowner WHERE n.nspname='public' "
                    "AND p.proname LIKE 'caseops_counsel_%' ORDER BY p.proname"
                )
            ).all()
        # The existing isolated test connection is the accepted migrator AND
        # runtime role. This does not claim arbitrary restricted-role support.
        assert role[0] == role[1] == engine.url.username
        assert type(role[2]) is int and role[2] > 0 and role[3] == "none"
        assert table_owners == [(name, role[2], role[0]) for name in sorted(NEW_TABLES)]
        signatures = {
            "caseops_counsel_finalize_v1": "",
            "caseops_counsel_labels_v1": "",
            "caseops_counsel_lock_scope_v1": "character varying, character varying",
            "caseops_counsel_rebuild_v1": "character varying, character varying, character varying",
            "caseops_counsel_source_v1": "",
            "caseops_counsel_truncate_v1": "",
            "caseops_counsel_user_changed_v1": "",
        }
        assert {f[0]: f[6] for f in functions} == signatures and len(functions) == 7
        for function in functions:
            assert type(function[1]) is int and function[1] > 0
            assert (function[2], function[3]) == (role[2], role[0])
            assert function[4] is False  # SECURITY INVOKER; no authority widening.
            assert len(function[5]) == 1
            key, value = function[5][0].split("=", 1)
            assert key == "search_path"
            assert [part.strip() for part in value.split(",")] == ["pg_catalog", "public"]
            assert function[7] is True  # Explicit ACL after PUBLIC revocation.
            assert function[8] is False  # PUBLIC has no EXECUTE entry.
            assert function[9] is True  # The exact accepted runtime owner can invoke.
        public_evidence = {
            "schemaVersion": 1,
            "scope": "actual-isolated-migrator-runtime-role",
            "currentUser": role[0],
            "sessionUser": role[1],
            "roleOid": role[2],
            "setRole": role[3],
            "tableOwners": [list(row) for row in table_owners],
            "functions": [
                {
                    "name": f[0],
                    "oid": f[1],
                    "ownerOid": f[2],
                    "ownerName": f[3],
                    "securityDefiner": f[4],
                    "configuration": f[5],
                    "argumentTypes": f[6],
                    "explicitAcl": f[7],
                    "publicExecute": f[8],
                    "runtimeExecute": f[9],
                }
                for f in functions
            ],
            "rolesCreatedOrGranted": False,
            "arbitraryRestrictedRoleSupportClaimed": False,
        }
        encoded = (json.dumps(public_evidence, indent=2, sort_keys=True) + "\n").encode()
        assert len(encoded) <= 16384
        with role_evidence_path.open("xb") as output:
            written = output.write(encoded)
            assert written == len(encoded)


@pytest.mark.parametrize("kind", KINDS)
def test_historical_0004_upgrade_backfills_both_kinds_and_preserves_sources_outboxes(
    kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        assert NEW_TABLES.isdisjoint(inspect(engine).get_table_names())
        scope, expected = _seed(engine)
        before_rows, before_catalog = _rows(engine, PRESERVED), _catalog(engine)
        assert all(before_rows[name] for name in PRESERVED)
        command.upgrade(config, HEAD)
        after_catalog = _catalog(engine)
        assert set(after_catalog["tables"]) == set(before_catalog["tables"]) | NEW_TABLES
        retained_catalog = {
            name: after_catalog["tables"][name] for name in before_catalog["tables"]
        }
        assert retained_catalog == before_catalog["tables"]
        for category in ("indexes", "triggers", "functions", "sequences"):
            assert all(row in after_catalog[category] for row in before_catalog[category])
        assert _rows(engine, PRESERVED) == before_rows
        _assert_new_shape(engine, tmp_path / "counsel-role-ownership.json")
        for record_kind in SOURCES:
            _assert_projection(engine, record_kind, scope, expected[record_kind])
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("record_kind", ["assignment", "spend"])
def test_old_column_insert_update_delete_remains_immediately_visible(
    kind, record_kind, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        scope, expected = _seed(engine, count=2)
        command.upgrade(config, HEAD)
        retained_outboxes = _rows(engine, OUTBOXES)
        retained_sources = _rows(engine, tuple(name for name, _note in SOURCES.values()))
        source = _table(engine, SOURCES[record_kind][0])
        added = _insert_source(engine, record_kind, scope, 28, note="Old writer after deployment")
        _assert_projection(engine, record_kind, scope, expected[record_kind] + [added])
        field = SOURCES[record_kind][1]
        with engine.begin() as connection:
            connection.execute(
                source.update()
                .where(source.c.id == added)
                .values(
                    **{
                        field: "Updated old-column note",
                        "currency": "USD",
                        "updated_at": NOW + timedelta(seconds=1),
                    }
                )
            )
        with engine.connect() as connection:
            row = connection.execute(select(source).where(source.c.id == added)).one()
            assert getattr(row, field) == "Updated old-column note" and row.currency == "USD"
            if engine.dialect.name == "postgresql":
                page = connection.execute(
                    text(
                        "SELECT payload,note_02 FROM counsel_read_pages WHERE company_id=:company "
                        "AND matter_id=:matter AND record_kind=:kind AND page_number=0"
                    ),
                    {**scope, "kind": record_kind},
                ).one()
                assert page.payload[2]["id"] == added and page.payload[2]["currency"] == "USD"
                assert page.note_02 == "Updated old-column note"
        _assert_projection(engine, record_kind, scope, expected[record_kind] + [added])
        with engine.begin() as connection:
            connection.execute(source.delete().where(source.c.id == added))
        _assert_projection(engine, record_kind, scope, expected[record_kind])
        for other_kind in SOURCES:
            _assert_projection(engine, other_kind, scope, expected[other_kind])
        assert _rows(engine, tuple(name for name, _note in SOURCES.values())) == retained_sources
        assert _rows(engine, OUTBOXES) == retained_outboxes


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("record_kind", ["assignment", "spend"])
def test_valid_native_text_larger_than_one_mib_survives_backfill_and_rolling_writes(
    kind, record_kind, tmp_path, monkeypatch
):
    # A literal valid TEXT counterexample to a newly invented 1MiB/JSON-page cap.
    wide = "Retained legal note: " + ("x" * (1024 * 1024 + 37)) + " Ω END"
    assert len(wide.encode("utf-8")) > 1024 * 1024
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        scope, expected = _seed(engine, count=1)
        source = _table(engine, SOURCES[record_kind][0])
        field = SOURCES[record_kind][1]
        original = expected[record_kind][0]
        with engine.begin() as connection:
            connection.execute(
                source.update().where(source.c.id == original).values(**{field: wide})
            )
        before = _rows(engine, PRESERVED)
        command.upgrade(config, HEAD)
        assert _rows(engine, PRESERVED) == before
        added = _insert_source(engine, record_kind, scope, 28, note=wide + " rolling writer")
        _assert_projection(engine, record_kind, scope, [original, added])
        with engine.connect() as connection:
            assert connection.scalar(select(source.c[field]).where(source.c.id == original)) == wide
            assert (
                connection.scalar(select(source.c[field]).where(source.c.id == added))
                == wide + " rolling writer"
            )
            if engine.dialect.name == "postgresql":
                page = connection.execute(
                    text(
                        "SELECT note_00,note_01,payload FROM counsel_read_pages "
                        "WHERE company_id=:company "
                        "AND matter_id=:matter AND record_kind=:kind AND page_number=0"
                    ),
                    {**scope, "kind": record_kind},
                ).one()
                assert page.note_00 == wide and page.note_01 == wide + " rolling writer"
                assert all(field not in item for item in page.payload)


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("populated", [False, True], ids=["empty", "retained"])
def test_restore_forward_refusal_preserves_complete_catalog_rows_and_revision(
    kind, populated, tmp_path, monkeypatch
):
    with fresh_engine(kind, tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        command.upgrade(config, PREVIOUS)
        if populated:
            _seed(engine, count=2)
        command.upgrade(config, HEAD)
        _assert_new_shape(engine, tmp_path / "counsel-role-ownership.json")
        names = (*PRESERVED, *sorted(NEW_TABLES))
        before_rows, before_catalog = _rows(engine, names), _catalog(engine)
        with pytest.raises(
            RuntimeError,
            match=(r"^Counsel derived legal-content rows are retained; restore-forward only\.$"),
        ):
            command.downgrade(config, PREVIOUS)
        assert _rows(engine, names) == before_rows
        assert _catalog(engine) == before_catalog
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
        # Idempotent forward reentry, explicitly not a dump/restore claim.
        command.upgrade(config, HEAD)
        assert _rows(engine, names) == before_rows
        assert _catalog(engine) == before_catalog


def test_canonical_map_and_compiled_projection_cover_pages_and_transaction_scopes():
    root = Path(__file__).resolve().parents[3]
    for script in ("ip_data_governance_map.py", "ip_data_class_projection.py"):
        spec = importlib.util.spec_from_file_location(
            "counsel_migration_" + script[:-3], root / "scripts" / script
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert module.validate() == []
    from caseops_api.governance import generated_data_class_projection as compiled
    from caseops_api.governance.schema_fingerprint import orm_schema_fingerprint

    assert NEW_TABLES <= compiled.INVENTORIED_SQL_TABLES
    assert compiled.ORM_SCHEMA_FINGERPRINT == orm_schema_fingerprint()


def test_exact_migration_parent_and_restore_forward_contract(monkeypatch, tmp_path):
    with fresh_engine("sqlite", tmp_path) as engine:
        config = migration_config(engine, monkeypatch)
        script = ScriptDirectory.from_config(config)
        revision = script.get_revision(HEAD)
        assert revision.revision == HEAD and revision.down_revision == PREVIOUS
        assert revision.module.PAGE == "counsel_read_pages"
        assert revision.module.MEMBER == "counsel_read_page_members"
        assert revision.module.branch_labels is None and revision.module.depends_on is None
        # Pure direct refusal must precede any attempt to obtain an Alembic bind.
        with pytest.raises(
            RuntimeError,
            match=(r"^Counsel derived legal-content rows are retained; restore-forward only\.$"),
        ):
            revision.module.downgrade()
