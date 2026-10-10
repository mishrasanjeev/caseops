"""Default restore-forward and locked-empty document-fence removal controls."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

PATH = (Path(__file__).resolve().parents[1]
        / "alembic/versions/20261010_0003_document_execution_protocol.py")
TABLES = ("document_processing_jobs", "matter_compliance_extraction_runs")


def _migration(monkeypatch, opt_in, retained, *, lock_failure=None):
    spec = importlib.util.spec_from_file_location("document_downgrade_control", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checks, drops = [], []

    def execute(statement):
        sql = str(statement)
        checks.append(sql)
        if sql == lock_failure:
            raise RuntimeError("bounded migration lock failure")
        return SimpleNamespace(scalar=lambda:
            1 if retained and sql == f"SELECT 1 FROM {retained} LIMIT 1" else None)

    monkeypatch.setattr(module.context, "get_x_argument", lambda **_:
        {"document_execution_fresh_downgrade": opt_in})
    monkeypatch.setattr(module.op, "get_bind", lambda: SimpleNamespace(
        dialect=SimpleNamespace(name="postgresql"), execute=execute))
    monkeypatch.setattr(module.op, "execute", drops.append)
    return module, checks, drops


@pytest.mark.parametrize("opt_in", [None, "", "false", "TRUE", "true"])
@pytest.mark.parametrize("retained", [None, *TABLES])
def test_document_fence_removal_requires_exact_opt_in_and_two_locked_empty_tables(
    monkeypatch, opt_in, retained,
):
    module, checks, drops = _migration(monkeypatch, opt_in, retained)
    if opt_in == "true" and retained is None:
        module.downgrade()
        assert drops == [
            "DROP TRIGGER document_execution_protocol ON document_processing_jobs",
            "DROP TRIGGER document_execution_provenance ON document_processing_jobs",
            "DROP FUNCTION caseops_document_execution_protocol()",
        ]
    else:
        with pytest.raises(RuntimeError, match="Document execution protocol.*restore-forward"):
            module.downgrade()
        assert drops == []
    expected = []
    if opt_in == "true":
        expected = [f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE" for table in TABLES]
        expected += ["SELECT 1 FROM document_processing_jobs LIMIT 1"]
        if retained != "document_processing_jobs":
            expected += ["SELECT 1 FROM matter_compliance_extraction_runs LIMIT 1"]
    assert checks == expected


@pytest.mark.parametrize("locked", TABLES)
def test_document_downgrade_lock_failure_never_checks_emptiness_or_drops(monkeypatch, locked):
    failed = f"LOCK TABLE {locked} IN ACCESS EXCLUSIVE MODE"
    module, checks, drops = _migration(monkeypatch, "true", None, lock_failure=failed)
    with pytest.raises(RuntimeError, match="bounded migration lock failure"):
        module.downgrade()
    assert checks == [f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"
                      for table in TABLES[:TABLES.index(locked) + 1]]
    assert drops == []


def test_sqlite_downgrade_has_no_document_fence_or_destructive_ddl(monkeypatch):
    module, checks, drops = _migration(monkeypatch, None, None)
    monkeypatch.setattr(module.op, "get_bind", lambda:
        SimpleNamespace(dialect=SimpleNamespace(name="sqlite")))
    module.downgrade()
    assert checks == drops == []
