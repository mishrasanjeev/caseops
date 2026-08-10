"""AQ-005 (2026-04-25) — Postgres-backed validation suite.

Codex's no-manual-tester replacement standard requires that critical
DB behavior be proven on real Postgres + pgvector, not just the
SQLite shim the rest of the suite uses. Every test in this module
carries `@pytest.mark.postgres` and is auto-skipped unless
CASEOPS_TEST_POSTGRES_URL is set (see `tests/conftest.py`).

The CI job `postgres-validation` (.github/workflows/ci.yml) starts a
service container of `pgvector/pgvector:pg17`, runs alembic
`upgrade head` once via `_ensure_migrations`, then runs
`pytest -m postgres`.

Each test creates its own rows with uuid4 IDs to avoid colliding
with neighboring tests. We do NOT roll back per-test — the service
container is fresh per CI job, and a small amount of accumulated
test data is fine for the few minutes the suite runs.

Why these specific tests:

- `test_alembic_upgrade_to_head_runs_cleanly`: catches every batch-
  mode migration that secretly assumes SQLite (e.g. our C-3
  20260424_0002 that uses `op.batch_alter_table`).
- `test_lifecycle_migration_neutralizes_legacy_children_on_postgres`:
  proves the July 15 data repair against the production dialect, not
  merely the SQLite migration harness. A legacy closed Matter is
  upgraded with its old task/deadline/hearing permanently cancelled.
- `test_pgvector_extension_and_hnsw_index_work`: the entire RAG
  retrieval path depends on pgvector's `<=>` cosine operator + an
  HNSW index. SQLite has no equivalent; this is the only place we
  prove the corpus retrieval shape works.
- `test_portal_user_fk_set_null_on_delete_propagates`: the C-3 FKs
  on matter_attachments / matter_invoices / matter_time_entries use
  `ON DELETE SET NULL`. SQLite ignores ON DELETE constraints unless
  PRAGMA foreign_keys=ON is set explicitly per session, so this
  behavior is effectively unverified outside Postgres.
- `test_jsonb_column_roundtrip_preserves_nested_dict`: SQLAlchemy's
  JSON column maps to JSONB on PG and TEXT-with-JSON-serialization
  on SQLite. The two have different ordering + key-handling
  semantics; this proves the prod path works.
- `test_unique_constraint_on_invoice_line_item_time_entry`: every
  UniqueConstraint we declare needs a real PG check — SQLite
  enforces them too but with looser semantics (e.g. NULL handling
  in composite UNIQUE).
- `test_oc_cross_visibility_server_default_inserts_false`: proves
  the C-3 `server_default=false()` on `Matter.oc_cross_visibility_enabled`
  actually fires on Postgres (the migration uses `sa.false()`).
"""

from __future__ import annotations

import importlib.util
import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

pytestmark = pytest.mark.postgres


# ---------- module-scope migrations (run once per CI job) ----------


@pytest.fixture(scope="module", autouse=True)
def _ensure_migrations():
    """Run alembic upgrade head once before any pg test executes.
    Idempotent: alembic skips already-applied revisions.

    Module-scoped → cannot depend on `pg_engine` (function-scoped).
    Reads CASEOPS_TEST_POSTGRES_URL directly so alembic targets the
    same DB the per-test pg_engine fixture binds to.
    """
    url = os.environ.get("CASEOPS_TEST_POSTGRES_URL", "").strip()
    if not url:
        # Tests will be skipped at collection-time (see conftest); we
        # still let the fixture run so module-scope teardown works.
        yield
        return
    from alembic.config import Config

    from alembic import command

    project_root = Path(__file__).resolve().parents[1]
    cfg = Config(str(project_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(project_root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    command.upgrade(cfg, "head")
    yield


# ---------- helpers ----------


def _seed_company(session: Session) -> str:
    company_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO companies "
            "(id, name, slug, company_type, tenant_key, is_active, "
            "timezone, created_at) "
            "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
        ),
        {
            "id": company_id,
            "n": f"PG Test Co {company_id[:8]}",
            "s": f"pgco-{company_id[:8]}",
            "tk": company_id,
            "tz": "Asia/Kolkata",
            "ts": datetime.now(UTC),
        },
    )
    return company_id


def _seed_matter(session: Session, company_id: str) -> str:
    """Raw-SQL seed: every NOT NULL column without a server_default
    must be supplied explicitly. Python-side `default=` on the
    SQLAlchemy model doesn't fire when we bypass the ORM."""
    matter_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO matters "
            "(id, company_id, title, matter_code, client_name, status, "
            "practice_area, forum_level, is_active, restricted_access, "
            "created_at, updated_at) "
            "VALUES (:id, :co, 'Test Matter', :code, 'Test Client', "
            "'active', 'commercial', 'high_court', true, false, :ts, :ts)"
        ),
        {
            "id": matter_id,
            "co": company_id,
            "code": f"PG-{matter_id[:6].upper()}",
            "ts": datetime.now(UTC),
        },
    )
    return matter_id


def _seed_membership(session: Session, company_id: str) -> str:
    user_id = str(uuid4())
    membership_id = str(uuid4())
    now = datetime.now(UTC)
    session.execute(
        text(
            "INSERT INTO users "
            "(id, email, full_name, password_hash, is_active, created_at) "
            "VALUES (:id, :email, 'Notice PG User', 'not-used', true, :ts)"
        ),
        {
            "id": user_id,
            "email": f"notice-pg-{user_id[:8]}@example.com",
            "ts": now,
        },
    )
    session.execute(
        text(
            "INSERT INTO company_memberships "
            "(id, company_id, user_id, role, is_active, created_at) "
            "VALUES (:id, :company, :user, 'member', true, :ts)"
        ),
        {
            "id": membership_id,
            "company": company_id,
            "user": user_id,
            "ts": now,
        },
    )
    return membership_id


def _seed_notice(
    session: Session,
    company_id: str,
    membership_id: str,
    **overrides: object,
) -> str:
    notice_id = str(uuid4())
    values: dict[str, object] = {
        "id": notice_id,
        "company": company_id,
        "owner": membership_id,
        "creator": membership_id,
        "direction": "received",
        "subject": f"PG notice {notice_id[:8]}",
        "status": "Open",
        "reply_required": False,
        "reply_sent": False,
        "currency": "INR",
        "ts": datetime.now(UTC),
    }
    values.update(overrides)
    session.execute(
        text(
            "INSERT INTO company_notices "
            "(id, company_id, owner_membership_id, created_by_membership_id, "
            "direction, subject, status, reply_required, reply_sent, currency, "
            "created_at, updated_at) VALUES "
            "(:id, :company, :owner, :creator, :direction, :subject, :status, "
            ":reply_required, :reply_sent, :currency, :ts, :ts)"
        ),
        values,
    )
    return notice_id


def _seed_portal_user(session: Session, company_id: str) -> str:
    pu_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO portal_users "
            "(id, company_id, email, full_name, role, is_active, created_at) "
            "VALUES (:id, :co, :em, 'Test PU', 'outside_counsel', true, :ts)"
        ),
        {
            "id": pu_id,
            "co": company_id,
            "em": f"pu-{pu_id[:8]}@example.com",
            "ts": datetime.now(UTC),
        },
    )
    return pu_id


def _fk_index_pairs() -> tuple[tuple[str, str], ...]:
    migration = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "20260625_0002_fk_leading_indexes.py"
    )
    spec = importlib.util.spec_from_file_location(migration.stem, migration)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    pairs = module.FK_INDEXES
    assert isinstance(pairs, tuple)
    return pairs


# ---------- tests ----------


def test_alembic_upgrade_to_head_runs_cleanly(pg_engine):
    """If `_ensure_migrations` got us here without raising, head is
    applied. Belt-and-suspenders: assert alembic_version is non-empty
    and equals the latest revision file on disk.
    """
    project_root = Path(__file__).resolve().parents[1]
    versions_dir = project_root / "alembic" / "versions"
    revs = sorted(p.name for p in versions_dir.glob("*.py") if p.name[0].isdigit())
    latest_filename = revs[-1]  # 20260424_0002_outside_counsel_portal.py
    latest_rev = latest_filename.split("_")[0] + "_" + latest_filename.split("_")[1]

    with pg_engine.connect() as conn:
        rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
    assert len(rows) == 1, f"alembic_version should have one row, got {len(rows)}"
    assert rows[0][0] == latest_rev, (
        f"DB at {rows[0][0]} but latest revision file is {latest_rev}; "
        "alembic upgrade head did not advance the DB"
    )


def test_notification_convergence_backfills_boolean_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """A legacy reminder upgrades with a native PostgreSQL boolean value."""
    from alembic.config import Config

    from alembic import command
    from caseops_api.core.settings import get_settings

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)

    pg_engine.dispose()
    command.downgrade(config, "20260804_0003")

    reminder_id = str(uuid4())
    hearing_id = str(uuid4())
    scheduled_for = datetime(2099, 8, 5, 4, 30, tzinfo=UTC)
    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id)
        matter_id = _seed_matter(session, company_id)
        session.execute(
            text(
                "INSERT INTO matter_hearings "
                "(id, matter_id, hearing_on, forum_name, purpose, status, created_at) "
                "VALUES (:id, :matter_id, :hearing_on, 'Delhi High Court', "
                "'Legacy notification convergence proof', 'scheduled', :created_at)"
            ),
            {
                "id": hearing_id,
                "matter_id": matter_id,
                "hearing_on": scheduled_for.date(),
                "created_at": now,
            },
        )
        session.execute(
            text(
                "INSERT INTO hearing_reminders "
                "(id, company_id, matter_id, hearing_id, recipient_membership_id, "
                "recipient_email, channel, scheduled_for, status, attempts, "
                "created_at, updated_at) "
                "VALUES (:id, :company_id, :matter_id, :hearing_id, :membership_id, "
                "'notification-pg@example.com', 'email', :scheduled_for, 'queued', 0, "
                ":created_at, :updated_at)"
            ),
            {
                "id": reminder_id,
                "company_id": company_id,
                "matter_id": matter_id,
                "hearing_id": hearing_id,
                "membership_id": membership_id,
                "scheduled_for": scheduled_for,
                "created_at": now,
                "updated_at": now,
            },
        )
        session.commit()

    pg_engine.dispose()
    command.upgrade(config, "head")

    with pg_engine.connect() as connection:
        intent = connection.execute(
            text(
                "SELECT id, critical, destination_version, comparison_status "
                "FROM notification_delivery_intents "
                "WHERE source_type = 'hearing_reminder' AND source_id = :source_id"
            ),
            {"source_id": reminder_id},
        ).one()
        lineage_count = connection.execute(
            text(
                "SELECT count(*) FROM hearing_reminder_delivery_intents "
                "WHERE hearing_reminder_id = :reminder_id AND intent_id = :intent_id"
            ),
            {"reminder_id": reminder_id, "intent_id": intent.id},
        ).scalar_one()

    # The module contains another downgrade/re-upgrade regression. Remove this
    # isolated tenant so that a second upgrade cannot legitimately rediscover
    # the same legacy reminder and collide with its durable idempotency key.
    with pg_engine.begin() as connection:
        connection.execute(
            text("DELETE FROM companies WHERE id = :company_id"),
            {"company_id": company_id},
        )

    assert intent.critical is True
    assert intent.destination_version == 1
    assert intent.comparison_status == "legacy_backfilled"
    assert lineage_count == 1


def test_lifecycle_migration_neutralizes_legacy_children_on_postgres(
    pg_engine,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upgrade a real legacy terminal row and prove children cannot revive."""
    from alembic.config import Config

    from alembic import command
    from caseops_api.core.settings import get_settings
    from caseops_api.db.models import (
        CalendarEventSync,
        Company,
        CompanyMembership,
        Matter,
        MatterDeadline,
        MatterHearing,
        MatterTask,
        User,
        UserCalendarConnection,
    )

    url = os.environ["CASEOPS_TEST_POSTGRES_URL"].strip()
    monkeypatch.setenv("CASEOPS_DATABASE_URL", url)
    get_settings.cache_clear()
    project_root = Path(__file__).resolve().parents[1]
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    config.set_main_option("sqlalchemy.url", url)

    company_id = str(uuid4())
    user_id = str(uuid4())
    membership_id = str(uuid4())
    matter_id = str(uuid4())
    task_id = str(uuid4())
    deadline_id = str(uuid4())
    hearing_id = str(uuid4())
    calendar_sync_id = str(uuid4())
    with Session(pg_engine) as session:
        session.add_all(
            [
                Company(
                    id=company_id,
                    name="Legacy PostgreSQL Lifecycle Firm",
                    slug=f"legacy-pg-lifecycle-{company_id[:8]}",
                    company_type="law_firm",
                    tenant_key=company_id,
                ),
                User(
                    id=user_id,
                    email=f"legacy-pg-lifecycle-{user_id[:8]}@example.com",
                    full_name="Legacy PostgreSQL Lifecycle Owner",
                    password_hash="not-used",
                ),
            ]
        )
        session.commit()
        session.add_all(
            [
                CompanyMembership(
                    id=membership_id,
                    company_id=company_id,
                    user_id=user_id,
                    role="owner",
                ),
                Matter(
                    id=matter_id,
                    company_id=company_id,
                    title="Legacy PostgreSQL closed matter",
                    matter_code=f"LEGACY-PG-{matter_id[:8].upper()}",
                    client_name="Legacy Client",
                    status="disposed",
                    practice_area="litigation",
                    forum_level="high_court",
                    is_active=False,
                    next_hearing_on=date(2099, 4, 10),
                    next_hearing_source="manual",
                    next_hearing_source_ref_type="matter_hearing",
                    next_hearing_source_ref_id=hearing_id,
                    next_hearing_manual_lock=True,
                ),
            ]
        )
        # These models are linked by scalar IDs, not in-memory relationships,
        # so SQLAlchemy has no unit-of-work edge from each child to the pending
        # Matter. Persist valid FK parents first; SQLite's permissive insert
        # ordering must not make an impossible production fixture look green.
        session.commit()
        session.add_all(
            [
                MatterTask(
                    id=task_id,
                    matter_id=matter_id,
                    title="Legacy PostgreSQL open task",
                    status="todo",
                ),
                MatterDeadline(
                    id=deadline_id,
                    matter_id=matter_id,
                    source="manual",
                    kind="filing",
                    title="Legacy PostgreSQL open deadline",
                    due_on=date(2099, 4, 9),
                    status="open",
                ),
                MatterHearing(
                    id=hearing_id,
                    matter_id=matter_id,
                    hearing_on=date(2099, 4, 10),
                    forum_name="Delhi High Court",
                    purpose="Legacy PostgreSQL open hearing",
                    status="scheduled",
                ),
            ]
        )
        session.commit()
        connection = UserCalendarConnection(
            company_id=company_id,
            membership_id=membership_id,
            provider="outlook",
            status="connected",
        )
        session.add(connection)
        session.commit()
        session.add(
            CalendarEventSync(
                id=calendar_sync_id,
                company_id=company_id,
                calendar_connection_id=connection.id,
                source_type="matter_hearing",
                source_id=hearing_id,
                provider_event_id="legacy-pg-provider-event",
                sync_status="synced",
            )
        )
        session.commit()

    pg_engine.dispose()
    command.downgrade(config, "20260708_0001")
    with pg_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE matters SET status = 'closed', is_active = true, "
                "next_hearing_on = '2099-04-10', next_hearing_source = 'manual', "
                "next_hearing_source_ref_type = 'matter_hearing', "
                "next_hearing_source_ref_id = :hearing_id, "
                "next_hearing_manual_lock = true WHERE id = :matter_id"
            ),
            {"hearing_id": hearing_id, "matter_id": matter_id},
        )
    pg_engine.dispose()
    command.upgrade(config, "head")

    with pg_engine.connect() as connection:
        matter_row = connection.execute(
            text(
                "SELECT status, is_active, next_hearing_on, next_hearing_source, "
                "next_hearing_source_ref_type, next_hearing_source_ref_id, "
                "next_hearing_manual_lock FROM matters WHERE id = :id"
            ),
            {"id": matter_id},
        ).one()
        task_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_tasks WHERE id = :id"
            ),
            {"id": task_id},
        ).one()
        deadline_row = connection.execute(
            text(
                "SELECT status, completed_at, cancelled_by_matter_disposal "
                "FROM matter_deadlines WHERE id = :id"
            ),
            {"id": deadline_id},
        ).one()
        hearing_row = connection.execute(
            text(
                "SELECT status, cancelled_by_matter_disposal "
                "FROM matter_hearings WHERE id = :id"
            ),
            {"id": hearing_id},
        ).one()
        calendar_sync_row = connection.execute(
            text(
                "SELECT sync_status, next_attempt_at, dead_letter_reason "
                "FROM calendar_event_syncs WHERE id = :id"
            ),
            {"id": calendar_sync_id},
        ).one()

    assert tuple(matter_row) == ("disposed", False, None, "unknown", None, None, False)
    assert task_row.status == "cancelled"
    assert task_row.completed_at is not None
    assert task_row.cancelled_by_matter_disposal is True
    assert deadline_row.status == "cancelled"
    assert deadline_row.completed_at is not None
    assert deadline_row.cancelled_by_matter_disposal is True
    assert tuple(hearing_row) == ("cancelled", True)
    assert calendar_sync_row.sync_status == "delete_pending"
    assert calendar_sync_row.next_attempt_at is not None
    assert calendar_sync_row.dead_letter_reason == "matter_disposed_delete"


def test_hearing_resync_query_does_not_compare_json_columns_on_postgres(pg_engine):
    """The no-provider path must not apply DISTINCT to a JSON column."""
    from caseops_api.db.models import Company, CompanyMembership, User
    from caseops_api.services.calendar_sync import (
        resync_synced_hearing_events_for_context,
    )
    from caseops_api.services.session_context import SessionContext

    company_id = str(uuid4())
    user_id = str(uuid4())
    membership_id = str(uuid4())
    with Session(pg_engine) as session:
        company = Company(
            id=company_id,
            name="PostgreSQL Calendar Resync Firm",
            slug=f"pg-calendar-resync-{company_id[:8]}",
            company_type="law_firm",
            tenant_key=company_id,
        )
        user = User(
            id=user_id,
            email=f"pg-calendar-resync-{user_id[:8]}@example.com",
            full_name="PostgreSQL Calendar Resync Owner",
            password_hash="not-used",
        )
        membership = CompanyMembership(
            id=membership_id,
            company_id=company_id,
            user_id=user_id,
            role="owner",
        )
        session.add_all([company, user])
        session.commit()
        session.add(membership)
        session.commit()

        context = SessionContext(
            company=company,
            membership=membership,
            user=user,
        )
        assert (
            resync_synced_hearing_events_for_context(
                session,
                context=context,
                hearing_id=str(uuid4()),
            )
            == 0
        )


def test_foreign_key_indexes_exist_after_head(pg_engine):
    inspector = inspect(pg_engine)
    missing: list[tuple[str, str]] = []

    for table, column in _fk_index_pairs():
        indexes = inspector.get_indexes(table)
        if not any(index.get("column_names", [None])[0] == column for index in indexes):
            missing.append((table, column))

    assert not missing, f"Foreign-key columns missing leading indexes: {missing}"


def test_conflict_check_trigram_indexes_exist_after_head(pg_engine):
    expected = {
        "ix_clients_name_trgm",
        "ix_matters_client_name_trgm",
        "ix_matters_opposing_party_trgm",
    }
    with pg_engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname, indexdef "
                "FROM pg_indexes "
                "WHERE schemaname = current_schema() "
                "AND indexname = ANY(:names)"
            ),
            {"names": list(expected)},
        ).mappings()
        indexes = {str(row["indexname"]): str(row["indexdef"]) for row in rows}

    assert set(indexes) == expected
    for indexdef in indexes.values():
        assert "USING gin" in indexdef
        assert "gin_trgm_ops" in indexdef
        assert "lower(" in indexdef


def test_authority_exact_name_prefilter_matches_party_tokens_on_postgres(pg_engine):
    from caseops_api.services.authorities import _exact_name_match_document_ids

    doc_id = str(uuid4())
    now = datetime.now(UTC)
    with Session(pg_engine) as session:
        session.execute(
            text(
                "INSERT INTO authority_documents "
                "(id, source, adapter_name, court_name, forum_level, document_type, "
                "title, canonical_key, summary, extracted_char_count, parties_json, "
                "bench_name, ingested_at, created_at, updated_at) "
                "VALUES (:id, 'pg-test', 'pg-test-adapter', 'Delhi High Court', "
                "'high_court', 'judgment', 'Acme Logistics v Kumar', :key, "
                "'Summary', 7, :parties, 'Commercial Bench', :ts, :ts, :ts)"
            ),
            {
                "id": doc_id,
                "key": f"pg-test::{doc_id}",
                "parties": '["Acme Logistics", "Kumar"]',
                "ts": now,
            },
        )
        session.commit()

        matches = _exact_name_match_document_ids(
            session,
            query="Acme Kumar",
            forum_level="high_court",
            court_name="Delhi High Court",
            document_type="judgment",
            limit=10,
        )
        court_misses = _exact_name_match_document_ids(
            session,
            query="Acme Kumar",
            forum_level="high_court",
            court_name="Bombay High Court",
            document_type="judgment",
            limit=10,
        )

    assert doc_id in matches
    assert doc_id not in court_misses


def test_pgvector_extension_and_hnsw_index_work(pg_engine):
    """Prove pgvector + HNSW + cosine distance round-trip on the same
    PG instance the corpus uses. No caseops table needed — we create
    a throwaway temp table so this test is hermetic.
    """
    with pg_engine.begin() as conn:
        ext = conn.execute(
            text("SELECT extversion FROM pg_extension WHERE extname='vector'")
        ).scalar()
        assert ext is not None, "pgvector extension must be installed"
        # Create a temp table — auto-dropped at session end.
        conn.execute(text("CREATE TEMP TABLE pg_aq005_vec_test (id int PRIMARY KEY, v vector(3))"))
        conn.execute(
            text(
                "INSERT INTO pg_aq005_vec_test (id, v) VALUES "
                "(1, '[1.0, 0.0, 0.0]'), "
                "(2, '[0.0, 1.0, 0.0]'), "
                "(3, '[0.95, 0.05, 0.0]')"
            )
        )
        # HNSW index — same shape as production
        conn.execute(text("CREATE INDEX ON pg_aq005_vec_test USING hnsw (v vector_cosine_ops)"))
        # Cosine-distance nearest-neighbour to [1,0,0]: id=1 first,
        # id=3 second, id=2 last.
        rows = conn.execute(
            text("SELECT id FROM pg_aq005_vec_test ORDER BY v <=> '[1.0, 0.0, 0.0]' LIMIT 3")
        ).fetchall()
        assert [r[0] for r in rows] == [1, 3, 2]


def test_portal_user_fk_set_null_on_delete_propagates(pg_engine):
    """C-3 schema: matter_attachments.submitted_by_portal_user_id is
    `ON DELETE SET NULL`. Insert a row with the FK set, delete the
    parent PortalUser, verify the FK is nulled (not cascaded).
    SQLite silently ignores ON DELETE without per-session PRAGMA;
    this is the only place we prove it on prod-shaped Postgres.
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        # Above call commits via transaction; reload session pattern
        # is awkward — use raw text for this small test.
        matter_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PG-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )
        pu_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO portal_users "
                "(id, company_id, email, full_name, role, is_active, "
                "created_at) "
                "VALUES (:id, :co, :em, 'PU', 'outside_counsel', true, :ts)"
            ),
            {
                "id": pu_id,
                "co": company_id,
                "em": f"pu-{pu_id[:6]}@x.example",
                "ts": datetime.now(UTC),
            },
        )
        att_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_attachments "
                "(id, matter_id, submitted_by_portal_user_id, "
                "original_filename, storage_key, size_bytes, sha256_hex, "
                "processing_status, extracted_char_count, created_at) "
                "VALUES (:id, :m, :pu, 'a.pdf', :sk, 0, "
                "'0000000000000000000000000000000000000000000000000000000000000000', "
                "'pending', 0, :ts)"
            ),
            {
                "id": att_id,
                "m": matter_id,
                "pu": pu_id,
                "sk": f"k/{att_id}",
                "ts": datetime.now(UTC),
            },
        )

    # Verify FK is set BEFORE delete
    with pg_engine.connect() as conn:
        before = conn.execute(
            text("SELECT submitted_by_portal_user_id FROM matter_attachments WHERE id = :id"),
            {"id": att_id},
        ).scalar()
        assert before == pu_id

    # Delete the portal_user
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM portal_users WHERE id = :id"), {"id": pu_id})

    # FK should now be NULL (SET NULL behavior)
    with pg_engine.connect() as conn:
        after = conn.execute(
            text("SELECT submitted_by_portal_user_id FROM matter_attachments WHERE id = :id"),
            {"id": att_id},
        ).scalar()
    assert after is None, (
        f"Expected FK SET NULL after parent delete, got {after}. "
        "ON DELETE SET NULL is not enforced — schema bug."
    )


def test_jsonb_column_roundtrip_preserves_nested_dict(pg_engine):
    """SQLAlchemy `JSON` column maps to JSONB on PG. Verify a nested
    dict survives the roundtrip with the same structure (not stringified)."""
    import json as _json

    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        payload = {"facts": ["a", "b"], "score": 0.42, "nested": {"k": "v"}}
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "executive_summary_json, created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, CAST(:j AS json), :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGJ-{matter_id[:6]}",
                "j": _json.dumps(payload),
                "ts": datetime.now(UTC),
            },
        )

    with pg_engine.connect() as conn:
        got = conn.execute(
            text("SELECT executive_summary_json FROM matters WHERE id = :id"),
            {"id": matter_id},
        ).scalar()
    # psycopg returns a dict for JSON/JSONB columns
    assert got == payload, f"JSON roundtrip mismatch: {got!r}"


def test_unique_constraint_on_invoice_line_item_time_entry(pg_engine):
    """matter_invoice_line_items has UniqueConstraint(time_entry_id).
    Two rows with the same non-null time_entry_id must trigger
    IntegrityError on the second insert.
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGI-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )
        invoice_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_invoices "
                "(id, company_id, matter_id, invoice_number, status, currency, "
                "subtotal_amount_minor, tax_amount_minor, total_amount_minor, "
                "amount_received_minor, balance_due_minor, issued_on, "
                "created_at, updated_at) "
                "VALUES (:id, :co, :m, :no, 'needs_review', 'INR', "
                "0, 0, 0, 0, 0, :d, :ts, :ts)"
            ),
            {
                "id": invoice_id,
                "co": company_id,
                "m": matter_id,
                "no": f"PG-{invoice_id[:6]}",
                "d": date.today(),
                "ts": datetime.now(UTC),
            },
        )
        time_entry_id = str(uuid4())
        conn.execute(
            text(
                "INSERT INTO matter_time_entries "
                "(id, matter_id, work_date, description, duration_minutes, "
                "billable, rate_currency, total_amount_minor, created_at) "
                "VALUES (:id, :m, :d, 'work', 60, true, 'INR', 0, :ts)"
            ),
            {
                "id": time_entry_id,
                "m": matter_id,
                "d": date.today(),
                "ts": datetime.now(UTC),
            },
        )
        conn.execute(
            text(
                "INSERT INTO matter_invoice_line_items "
                "(id, invoice_id, time_entry_id, description, "
                "line_total_amount_minor, created_at) "
                "VALUES (:id, :inv, :te, 'first', 1000, :ts)"
            ),
            {
                "id": str(uuid4()),
                "inv": invoice_id,
                "te": time_entry_id,
                "ts": datetime.now(UTC),
            },
        )

    # Second insert with the same time_entry_id must fail
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO matter_invoice_line_items "
                    "(id, invoice_id, time_entry_id, description, "
                    "line_total_amount_minor, created_at) "
                    "VALUES (:id, :inv, :te, 'second', 1000, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "inv": invoice_id,
                    "te": time_entry_id,
                    "ts": datetime.now(UTC),
                },
            )


def test_unique_tenant_key_blocks_cross_tenant_collisions(pg_engine):
    """AQ-005 expansion (2026-04-28) — `companies.tenant_key` is the
    cornerstone of tenant isolation. Inserting two companies with the
    same tenant_key must be rejected by Postgres at the unique-index
    layer, not just by application code. SQLite would also reject it,
    but with looser semantics (NULL/case handling); only Postgres
    proves the production guarantee.
    """
    shared_tenant_key = str(uuid4())
    with pg_engine.begin() as conn:
        # First insert succeeds.
        conn.execute(
            text(
                "INSERT INTO companies "
                "(id, name, slug, company_type, tenant_key, is_active, "
                "timezone, created_at) "
                "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
            ),
            {
                "id": str(uuid4()),
                "n": "Tenant key uniqueness test A",
                "s": f"tk-test-a-{shared_tenant_key[:8]}",
                "tk": shared_tenant_key,
                "tz": "Asia/Kolkata",
                "ts": datetime.now(UTC),
            },
        )

    # Second insert with the same tenant_key MUST raise IntegrityError.
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO companies "
                    "(id, name, slug, company_type, tenant_key, is_active, "
                    "timezone, created_at) "
                    "VALUES (:id, :n, :s, 'law_firm', :tk, true, :tz, :ts)"
                ),
                {
                    "id": str(uuid4()),
                    "n": "Tenant key uniqueness test B",
                    "s": f"tk-test-b-{shared_tenant_key[:8]}",
                    "tk": shared_tenant_key,
                    "tz": "Asia/Kolkata",
                    "ts": datetime.now(UTC),
                },
            )


def test_oc_cross_visibility_server_default_inserts_false(pg_engine):
    """C-3c added oc_cross_visibility_enabled with
    server_default=false(). Insert a matter row WITHOUT supplying that
    column and verify it lands as False (not NULL, not True).
    """
    with pg_engine.begin() as conn:
        company_id = _seed_company(Session(bind=conn))
        matter_id = str(uuid4())
        # Do NOT include oc_cross_visibility_enabled in the column list.
        conn.execute(
            text(
                "INSERT INTO matters "
                "(id, company_id, title, matter_code, client_name, status, "
                "practice_area, forum_level, is_active, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', true, false, :ts, :ts)"
            ),
            {
                "id": matter_id,
                "co": company_id,
                "code": f"PGD-{matter_id[:6]}",
                "ts": datetime.now(UTC),
            },
        )

    with pg_engine.connect() as conn:
        v = conn.execute(
            text("SELECT oc_cross_visibility_enabled FROM matters WHERE id = :id"),
            {"id": matter_id},
        ).scalar()
    assert v is False, (
        f"Expected server_default=false to land False, got {v!r}. "
        "Migration 20260424_0002 server_default may not have applied."
    )


def test_notice_tenant_constraints_and_delete_policy_on_postgres(pg_engine):
    """Production DB must reject tenant drift and notice globalization."""
    with Session(pg_engine) as session:
        company_a = _seed_company(session)
        company_b = _seed_company(session)
        membership_a = _seed_membership(session, company_a)
        membership_b = _seed_membership(session, company_b)
        matter_a = _seed_matter(session, company_a)
        matter_b = _seed_matter(session, company_b)
        notice_a = _seed_notice(session, company_a, membership_a)
        session.execute(
            text(
                "INSERT INTO company_notice_matter_links "
                "(id, company_id, notice_id, matter_id, created_at) "
                "VALUES (:id, :company, :notice, :matter, :ts)"
            ),
            {
                "id": str(uuid4()),
                "company": company_a,
                "notice": notice_a,
                "matter": matter_a,
                "ts": datetime.now(UTC),
            },
        )
        session.commit()

    for overrides in (
        {"owner": membership_b},
        {"creator": membership_b},
        {"creator": None},
    ):
        with pytest.raises(IntegrityError):
            with Session(pg_engine) as session:
                _seed_notice(session, company_a, membership_a, **overrides)
                session.commit()

    invalid_links = (
        (company_a, notice_a, matter_b),
        (company_b, notice_a, matter_b),
    )
    for company_id, notice_id, matter_id in invalid_links:
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO company_notice_matter_links "
                        "(id, company_id, notice_id, matter_id, created_at) "
                        "VALUES (:id, :company, :notice, :matter, :ts)"
                    ),
                    {
                        "id": str(uuid4()),
                        "company": company_id,
                        "notice": notice_id,
                        "matter": matter_id,
                        "ts": datetime.now(UTC),
                    },
                )

    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM matters WHERE id = :id"),
                {"id": matter_a},
            )
    with pytest.raises(IntegrityError):
        with pg_engine.begin() as connection:
            connection.execute(
                text("DELETE FROM company_memberships WHERE id = :id"),
                {"id": membership_a},
            )


def test_notice_direction_and_reply_checks_on_postgres(pg_engine):
    with Session(pg_engine) as session:
        company_id = _seed_company(session)
        membership_id = _seed_membership(session, company_id)
        session.commit()

    invalid_states = (
        {
            "direction": "received",
            "received_on": None,
            "received_from": None,
            "sent_on": date(2026, 7, 15),
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": None,
            "received_from": "Invalid sender",
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "sent",
            "received_on": None,
            "received_from": None,
            "sent_on": date(2026, 7, 15),
            "reply_due_on": None,
            "reply_required": True,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": True,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": date(2026, 7, 20),
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": None,
        },
        {
            "direction": "received",
            "received_on": date(2026, 7, 15),
            "received_from": None,
            "sent_on": None,
            "reply_due_on": None,
            "reply_required": False,
            "reply_sent": False,
            "reply_sent_on": date(2026, 7, 19),
        },
    )
    statement = text(
        "INSERT INTO company_notices "
        "(id, company_id, owner_membership_id, created_by_membership_id, "
        "direction, subject, status, received_on, received_from, sent_on, "
        "reply_due_on, reply_required, reply_sent, reply_sent_on, currency, "
        "created_at, updated_at) VALUES "
        "(:id, :company, :membership, :membership, :direction, :subject, "
        "'Open', :received_on, :received_from, :sent_on, :reply_due_on, "
        ":reply_required, :reply_sent, :reply_sent_on, 'INR', :ts, :ts)"
    )
    for index, invalid_state in enumerate(invalid_states):
        with pytest.raises(IntegrityError):
            with pg_engine.begin() as connection:
                connection.execute(
                    statement,
                    {
                        "id": str(uuid4()),
                        "company": company_id,
                        "membership": membership_id,
                        "subject": f"Invalid PG notice state {index}",
                        "ts": datetime.now(UTC),
                        **invalid_state,
                    },
                )
