"""Pure admission controls; native PostgreSQL arbitration is a separate inventory."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from caseops_api.db.models import MatterComplianceExtractionRun
from caseops_api.services import compliance_tail_protocol as protocol

LEGACY_SHA256 = "15b0353be9ea24f376aac63d6a1b6e71ba1eb0bd6b93201d5e29a43299971a87"
ROOT = Path(__file__).resolve().parents[1]


class _Session:
    def __init__(self, dialect="postgresql"):
        self.dialect, self.info, self.calls, self.in_no_autoflush = dialect, {}, [], False

    def get_bind(self):
        return SimpleNamespace(dialect=SimpleNamespace(name=self.dialect))

    @property
    @contextmanager
    def no_autoflush(self):
        self.in_no_autoflush = True
        try:
            yield
        finally:
            self.in_no_autoflush = False

    def execute(self, statement, parameters):
        assert self.in_no_autoflush
        self.calls.append((str(statement), parameters))


def _run(**values):
    return MatterComplianceExtractionRun(
        **{
            "company_id": str(uuid4()),
            "matter_id": str(uuid4()),
            "source_type": "manual_order",
            "trigger": "manual_order_create",
            "source_hash": "a" * 64,
            **values,
        }
    )


def _admitted(**values):
    run, session = _run(**values), _Session()
    protocol.admit_compliance_run(session, run)
    return run, session


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_new_run_has_explicit_marker_without_server_default(dialect):
    run, session = _run(), _Session(dialect)
    assert run.persistence_protocol is None
    protocol.admit_compliance_run(session, run)
    assert run.persistence_protocol == protocol.COMPLIANCE_TAIL_PROTOCOL
    assert run.id and len(run.id) == 36
    column = MatterComplianceExtractionRun.__table__.c.persistence_protocol
    assert column.nullable and column.default is None and column.server_default is None
    assert len(session.calls) == (1 if dialect == "postgresql" else 0)


def test_context_is_parameterized_transaction_local_and_contains_no_source_text():
    run, session = _admitted()
    sql, parameters = session.calls[0]
    assert sql == "SELECT set_config('caseops.compliance_tail', :identity, true)"
    payload = parameters["identity"]
    identity = json.loads(payload)
    assert identity["run_id"] == run.id
    assert identity["document_attempt"] is None
    assert len(payload.encode()) <= protocol.MAX_CONTEXT_BYTES
    assert set(identity) == {
        "protocol",
        "run_id",
        "company_id",
        "matter_id",
        "court_order_id",
        "attachment_id",
        "actor_membership_id",
        "source_type",
        "trigger",
        "source_hash",
        "document_attempt",
    }


@pytest.mark.parametrize("marker", [None, "", "legacy", "compliance-tail-v2"])
def test_existing_run_is_never_autostamped(marker):
    run, session = _run(id=str(uuid4()), persistence_protocol=marker), _Session()
    with pytest.raises(protocol.ComplianceTailProtocolError) as rejected:
        protocol.bind_compliance_run_context(session, run)
    assert rejected.value.detail == {"code": "compliance_execution_protocol_rejected"}
    assert run.persistence_protocol == marker and not session.calls


def test_pending_run_cannot_be_adopted_as_new():
    run = _run()
    with Session() as orm:
        orm.add(run)
        with pytest.raises(protocol.ComplianceTailProtocolError):
            protocol.admit_compliance_run(_Session(), run)
        assert run.persistence_protocol is None


def test_already_admitted_run_cannot_be_admitted_twice():
    run, session = _admitted()
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.admit_compliance_run(session, run)
    assert len(session.calls) == 1


@pytest.mark.parametrize(
    "field",
    [
        "id",
        "company_id",
        "matter_id",
        "court_order_id",
        "attachment_id",
        "created_by_membership_id",
    ],
)
@pytest.mark.parametrize("value", ["not-a-uuid", "A" * 36])
def test_invalid_identity_fails_before_any_statement(field, value):
    run, session = _admitted()
    session.calls.clear()
    setattr(run, field, value)
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)
    assert not session.calls


@pytest.mark.parametrize("value", ["", "a" * 63, "a" * 65, "Z" * 64, 123])
def test_invalid_source_hash_is_bounded(value):
    run, session = _admitted()
    session.calls.clear()
    run.source_hash = value
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)
    assert not session.calls


@pytest.mark.parametrize("field", ["source_type", "trigger"])
@pytest.mark.parametrize("value", [None, "", "x" * 41])
def test_invalid_source_category_is_bounded(field, value):
    run, session = _admitted()
    session.calls.clear()
    setattr(run, field, value)
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)
    assert not session.calls


def test_document_context_uses_captured_attempt_not_database_adoption():
    run, session = _admitted(attachment_id=str(uuid4()))
    captured = SimpleNamespace(
        id=str(uuid4()), company_id=run.company_id, number=2, started_at=datetime.now(UTC)
    )
    session.info["document_job_attempt"] = captured
    protocol.bind_compliance_run_context(session, run)
    identity = json.loads(session.calls[-1][1]["identity"])
    assert identity["document_attempt"] == {
        "id": captured.id,
        "attempt_count": 2,
        "started_at": captured.started_at.isoformat(),
    }
    assert len(session.calls) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"company_id": str(uuid4())},
        {"number": True},
        {"number": 0},
        {"number": 2147483648},
        {"started_at": None},
        {"started_at": datetime(2026, 10, 10)},
        {"id": "wrong"},
    ],
)
def test_bad_document_attempt_is_rejected_without_io(change):
    run, session = _admitted(attachment_id=str(uuid4()))
    session.info["document_job_attempt"] = SimpleNamespace(
        **{
            "id": str(uuid4()),
            "company_id": run.company_id,
            "number": 1,
            "started_at": datetime.now(UTC),
            **change,
        }
    )
    session.calls.clear()
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)
    assert not session.calls


def test_document_attempt_cannot_be_used_for_an_order_only_run():
    run, session = _admitted()
    session.info["document_job_attempt"] = SimpleNamespace(
        id=str(uuid4()),
        company_id=run.company_id,
        number=1,
        started_at=datetime.now(UTC),
    )
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)


def test_serialized_context_limit_is_checked_before_io(monkeypatch):
    run, session = _admitted()
    monkeypatch.setattr(protocol, "MAX_CONTEXT_BYTES", 1)
    session.calls.clear()
    with pytest.raises(protocol.ComplianceTailProtocolError):
        protocol.bind_compliance_run_context(session, run)
    assert not session.calls


def test_frozen_compliance_and_document_sources_are_exact_3dbf_bytes():
    fixtures = Path(__file__).parent / "fixtures"
    expected = {
        "compliance_extraction_3dbf.py": LEGACY_SHA256,
        "document_jobs_3dbf.py": "c4acf5992cf7e73c62702c2420a7468beb1358723dca4db4f674bc179cf0f78f",
    }
    for name, digest in expected.items():
        assert (
            hashlib.sha256((fixtures / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            == digest
        )


def test_current_create_and_finish_bind_before_any_flush_or_run_mutation():
    source = ROOT / "src/caseops_api/services/compliance_extraction.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    create, finish = functions["_create_run"], functions["_finish_run"]
    calls = [node for node in ast.walk(create) if isinstance(node, ast.Call)]
    admitted = next(
        node
        for node in calls
        if isinstance(node.func, ast.Name) and node.func.id == "admit_compliance_run"
    )
    flushed = next(
        node for node in calls if isinstance(node.func, ast.Attribute) and node.func.attr == "flush"
    )
    assert admitted.lineno < flushed.lineno
    first = finish.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert first.value.func.id == "bind_compliance_run_context"


def test_migration_chain_and_no_legacy_default():
    path = ROOT / "alembic/versions/20261010_0004_compliance_tail_protocol.py"
    spec = importlib.util.spec_from_file_location("compliance_tail_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.revision == "20261010_0004"
    assert migration.down_revision == "20261010_0003"
    assert "UPDATE matter_compliance_extraction_runs" not in migration.FUNCTION_SQL


@pytest.mark.parametrize("opt_in", [None, "false", "true"])
@pytest.mark.parametrize("retained", [False, True])
@pytest.mark.parametrize("dialect", ["postgresql", "sqlite"])
def test_downgrade_requires_explicit_empty_rehearsal_before_any_drop(
    monkeypatch, opt_in, retained, dialect
):
    path = ROOT / "alembic/versions/20261010_0004_compliance_tail_protocol.py"
    spec = importlib.util.spec_from_file_location("tail_downgrade_control", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    calls = []
    checks = []

    def execute(statement):
        checks.append(str(statement))
        return SimpleNamespace(scalar=lambda: 1 if retained else None)

    bind = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect),
        execute=execute,
    )
    monkeypatch.setattr(
        migration.context,
        "get_x_argument",
        lambda **_: {
            "compliance_tail_fresh_downgrade": opt_in,
        },
    )
    monkeypatch.setattr(migration.op, "get_bind", lambda: bind)
    monkeypatch.setattr(migration.op, "execute", calls.append)
    monkeypatch.setattr(migration.op, "drop_column", lambda *args: calls.append(args))
    if opt_in == "true" and not retained:
        migration.downgrade()
        assert len(calls) == (4 if dialect == "postgresql" else 1)
    else:
        with pytest.raises(RuntimeError, match="restore-forward"):
            migration.downgrade()
        assert calls == []
    assert checks == (
        (
            ["LOCK TABLE matter_compliance_extraction_runs IN ACCESS EXCLUSIVE MODE"]
            if dialect == "postgresql"
            else []
        )
        + ["SELECT 1 FROM matter_compliance_extraction_runs LIMIT 1"]
        if opt_in == "true"
        else []
    )


def test_downgrade_lock_failure_never_checks_emptiness_or_drops(monkeypatch):
    path = ROOT / "alembic/versions/20261010_0004_compliance_tail_protocol.py"
    spec = importlib.util.spec_from_file_location("tail_downgrade_lock_control", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checks, drops = [], []

    def execute(statement):
        checks.append(str(statement))
        raise RuntimeError("bounded lock failure")

    monkeypatch.setattr(
        migration.context,
        "get_x_argument",
        lambda **_: {"compliance_tail_fresh_downgrade": "true"},
    )
    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), execute=execute),
    )
    monkeypatch.setattr(migration.op, "execute", drops.append)
    monkeypatch.setattr(migration.op, "drop_column", lambda *args: drops.append(args))
    with pytest.raises(RuntimeError, match="bounded lock failure"):
        migration.downgrade()
    assert checks == ["LOCK TABLE matter_compliance_extraction_runs IN ACCESS EXCLUSIVE MODE"]
    assert not drops
