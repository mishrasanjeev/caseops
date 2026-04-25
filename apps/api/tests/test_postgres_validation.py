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

import os
from datetime import UTC, date, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
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
    from alembic import command
    from alembic.config import Config

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
    matter_id = str(uuid4())
    session.execute(
        text(
            "INSERT INTO matters "
            "(id, company_id, title, matter_code, client_name, status, "
            "practice_area, forum_level, restricted_access, created_at, updated_at) "
            "VALUES (:id, :co, 'Test Matter', :code, 'Test Client', 'active', "
            "'commercial', 'high_court', false, :ts, :ts)"
        ),
        {
            "id": matter_id,
            "co": company_id,
            "code": f"PG-{matter_id[:6].upper()}",
            "ts": datetime.now(UTC),
        },
    )
    return matter_id


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
        conn.execute(
            text(
                "CREATE TEMP TABLE pg_aq005_vec_test "
                "(id int PRIMARY KEY, v vector(3))"
            )
        )
        conn.execute(
            text(
                "INSERT INTO pg_aq005_vec_test (id, v) VALUES "
                "(1, '[1.0, 0.0, 0.0]'), "
                "(2, '[0.0, 1.0, 0.0]'), "
                "(3, '[0.95, 0.05, 0.0]')"
            )
        )
        # HNSW index — same shape as production
        conn.execute(
            text(
                "CREATE INDEX ON pg_aq005_vec_test USING hnsw "
                "(v vector_cosine_ops)"
            )
        )
        # Cosine-distance nearest-neighbour to [1,0,0]: id=1 first,
        # id=3 second, id=2 last.
        rows = conn.execute(
            text(
                "SELECT id FROM pg_aq005_vec_test "
                "ORDER BY v <=> '[1.0, 0.0, 0.0]' LIMIT 3"
            )
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
                "practice_area, forum_level, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', false, :ts, :ts)"
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
            text(
                "SELECT submitted_by_portal_user_id FROM matter_attachments "
                "WHERE id = :id"
            ),
            {"id": att_id},
        ).scalar()
        assert before == pu_id

    # Delete the portal_user
    with pg_engine.begin() as conn:
        conn.execute(text("DELETE FROM portal_users WHERE id = :id"), {"id": pu_id})

    # FK should now be NULL (SET NULL behavior)
    with pg_engine.connect() as conn:
        after = conn.execute(
            text(
                "SELECT submitted_by_portal_user_id FROM matter_attachments "
                "WHERE id = :id"
            ),
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
                "practice_area, forum_level, restricted_access, "
                "executive_summary_json, created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', false, CAST(:j AS json), :ts, :ts)"
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
            text(
                "SELECT executive_summary_json FROM matters WHERE id = :id"
            ),
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
                "practice_area, forum_level, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', false, :ts, :ts)"
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
                "practice_area, forum_level, restricted_access, "
                "created_at, updated_at) "
                "VALUES (:id, :co, 'M', :code, 'C', 'active', 'commercial', "
                "'high_court', false, :ts, :ts)"
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
            text(
                "SELECT oc_cross_visibility_enabled FROM matters "
                "WHERE id = :id"
            ),
            {"id": matter_id},
        ).scalar()
    assert v is False, (
        f"Expected server_default=false to land False, got {v!r}. "
        "Migration 20260424_0002 server_default may not have applied."
    )
