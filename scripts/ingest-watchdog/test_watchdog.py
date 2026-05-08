from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import Mock


def _load_watchdog(row):
    state = {}

    class _Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def execute(self, sql):
            state["sql"] = sql

        def fetchone(self):
            return row

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def cursor(self):
            return _Cursor()

    psycopg = types.SimpleNamespace(connect=Mock(return_value=_Connection()))
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    compute_v1 = types.SimpleNamespace(InstancesClient=object)
    cloud.compute_v1 = compute_v1
    google.cloud = cloud
    sys.modules["psycopg"] = psycopg
    sys.modules["google"] = google
    sys.modules["google.cloud"] = cloud
    sys.modules["google.cloud.compute_v1"] = compute_v1

    path = Path(__file__).with_name("watchdog.py")
    spec = importlib.util.spec_from_file_location("watchdog_under_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module, psycopg, state


def test_latest_activity_uses_model_runs_not_only_ingest(monkeypatch):
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql://caseops:test@127.0.0.1/caseops")
    watchdog, _psycopg, state = _load_watchdog(("model_runs.metadata_extract", 30))

    source, stale = watchdog._latest_activity()

    assert source == "model_runs.metadata_extract"
    assert stale == 30
    sql = state["sql"]
    assert "authority_documents" in sql
    assert "authority_document_chunks" in sql
    assert "model_runs" in sql
    assert "voyage_usage" in sql


def test_stale_seconds_handles_empty_corpus(monkeypatch):
    monkeypatch.setenv("CASEOPS_DATABASE_URL", "postgresql://caseops:test@127.0.0.1/caseops")
    watchdog, _psycopg, _state = _load_watchdog(None)

    assert watchdog._stale_seconds() is None
