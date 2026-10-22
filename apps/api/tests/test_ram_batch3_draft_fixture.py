"""Synthetic browser seed cannot escape its explicitly local database."""
import io
import json
import runpy
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def fixture_namespace() -> dict:
    path = Path(__file__).resolve().parents[3] / "tests/e2e/support/ram_batch3_draft_fixture.py"
    return runpy.run_path(str(path))


@pytest.mark.parametrize("database", [
    "postgresql+psycopg://caseops:caseops@127.0.0.1:41093/caseops",
    "postgresql+psycopg://caseops:caseops@localhost:20000/caseops",
])
def test_batch3_fixture_accepts_only_admitted_local_postgres(
    fixture_namespace: dict, database: str,
) -> None:
    fixture_namespace["validate_database"](database)


def test_batch3_fixture_accepts_checkout_sqlite(fixture_namespace: dict) -> None:
    target = Path(__file__).resolve().parents[3] / "caseops-e2e.db"
    fixture_namespace["validate_database"](f"sqlite+pysqlite:///{target.as_posix()}")


@pytest.mark.parametrize("database", [
    "postgresql+psycopg://caseops:caseops@127.0.0.1:41093/caseops?host=production.example",
    "postgresql+psycopg://caseops:caseops@localhost:41093/caseops?hostaddr=203.0.113.1",
    "postgresql+psycopg://caseops:caseops@localhost:41093/caseops?sslmode=require",
    "postgresql+psycopg://caseops:caseops@production.example:41093/caseops",
    "postgresql+psycopg://caseops:caseops@localhost:15443/caseops",
    "postgresql+psycopg://caseops:caseops@localhost/caseops",
    "postgresql+psycopg://real:secret@localhost:41093/caseops",
    "postgresql+psycopg://caseops:caseops@localhost:41093/retained_database",
    "postgresql+psycopg2://caseops:caseops@localhost:41093/caseops",
    "sqlite+pysqlite:///retained_database.db",
    "sqlite+pysqlite:///:memory:",
    "sqlite+pysqlite:///file:retained_database.db?uri=true",
])
def test_batch3_fixture_rejects_connection_escape_before_session(
    fixture_namespace: dict, database: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def unexpected_session():
        nonlocal called
        called = True
        raise AssertionError("A rejected database must never create a session")

    main = fixture_namespace["main"]
    monkeypatch.setitem(main.__globals__, "get_session_factory", unexpected_session)
    monkeypatch.setenv("CASEOPS_ENV", "e2e")
    monkeypatch.setenv("CASEOPS_LLM_PROVIDER", "mock")
    monkeypatch.setenv("CASEOPS_DATABASE_URL", database)
    identity = "12345678-1234-1234-1234-123456789012"
    payload = {
        key: identity for key in ("company_id", "membership_id", "matter_id", "draft_id", "run")
    }
    payload.update(web="http://127.0.0.1:3100", api="http://127.0.0.1:8000")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(ValueError):
        main()
    assert called is False
