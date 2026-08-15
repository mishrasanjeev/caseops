from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event, func, insert, select, update
from sqlalchemy.engine import Engine

from caseops_api.db.models import AuditEvent, CompanyIpRulePolicy, IpRuleSet, IpRuleVersion
from caseops_api.scripts import ip_rule_governance_fingerprint as fingerprint

FINGERPRINT_TABLES = (
    IpRuleSet.__table__,
    IpRuleVersion.__table__,
    CompanyIpRulePolicy.__table__,
    AuditEvent.__table__,
)


@pytest.fixture
def governance_engine() -> Engine:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    IpRuleSet.metadata.create_all(engine, tables=list(FINGERPRINT_TABLES))
    created_at = datetime(2026, 8, 14, 10, 30, tzinfo=UTC)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)"
        )
        connection.exec_driver_sql(
            "INSERT INTO alembic_version (version_num) VALUES ('20260813_0002')"
        )
        connection.execute(
            insert(IpRuleSet),
            {
                "id": "rule-set-1",
                "key": "in-trademark-opposition",
                "rule_kind": "deadline",
                "jurisdiction": "IN",
                "office": "CGPDTM",
                "right_kind": "trademark",
                "proceeding_kind": "opposition",
                "role": "applicant",
                "stage": "counterstatement",
                "created_at": created_at,
            },
        )
        connection.execute(
            insert(IpRuleVersion),
            {
                "id": "rule-version-1",
                "rule_set_id": "rule-set-1",
                "version": 1,
                "status": "active",
                "source_record_id": "legal-source-private-id",
                "source_hash": "a" * 64,
                "source_reference": "https://private.example/legal-source",
                "effective_from": date(2026, 8, 1),
                "effective_until": None,
                "engine_compatibility": "v1",
                "fixture_set_json": [{"id": "private-fixture", "days": 30}],
                "definition_json": {"private_rule_detail": "do-not-log", "days": 30},
                "proposed_by_membership_id": None,
                "proposer_label_snapshot": "Confidential Reviewer",
                "reviewed_by_membership_id": None,
                "reviewer_label_snapshot": None,
                "legal_approved_by_membership_id": None,
                "legal_approver_label_snapshot": None,
                "fixtures_passed_at": created_at,
                "activated_at": created_at,
                "disabled_at": None,
                "created_at": created_at,
            },
        )
        connection.execute(
            insert(CompanyIpRulePolicy),
            {
                "id": "policy-1",
                "company_id": "private-company-id",
                "rule_set_id": "rule-set-1",
                "active_rule_version_id": "rule-version-1",
                "auto_confirm_eligible": False,
                "internal_target_policy_json": {"private_target": "do-not-log"},
                "version": 1,
                "updated_by_membership_id": None,
                "updater_label_snapshot": "Confidential Operator",
                "created_at": created_at,
                "updated_at": created_at,
            },
        )
        for audit_row in (
            {
                "id": "audit-included",
                "company_id": "private-company-id",
                "actor_type": "human",
                "actor_label": "Confidential Operator",
                "action": "ip.rule_version.proposed",
                "target_type": "ip_rule_version",
                "target_id": "rule-version-1",
                "result": "success",
                "metadata_json": '{"private":"audit detail"}',
                "created_at": created_at,
            },
            {
                "id": "audit-wrong-target",
                "company_id": "private-company-id",
                "actor_type": "human",
                "action": "ip.rule_version.activated",
                "target_type": "ip_deadline",
                "result": "success",
                "created_at": created_at,
            },
            {
                "id": "audit-wrong-action",
                "company_id": "private-company-id",
                "actor_type": "human",
                "action": "ip.deadline.confirmed",
                "target_type": "ip_rule_version",
                "result": "success",
                "created_at": created_at,
            },
            {
                "id": "audit-like-wildcard-trap",
                "company_id": "private-company-id",
                "actor_type": "human",
                "action": "ipXrule_version.proposed",
                "target_type": "matter",
                "result": "success",
                "created_at": created_at,
            },
        ):
            connection.execute(insert(AuditEvent), audit_row)
    yield engine
    engine.dispose()


def test_snapshot_is_deterministic_filtered_and_contains_no_row_values(
    governance_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_times = iter(
        (
            datetime(2026, 8, 14, 11, 0, tzinfo=UTC),
            datetime(2026, 8, 14, 11, 5, tzinfo=UTC),
        )
    )
    monkeypatch.setattr(fingerprint, "_now_utc", lambda: next(capture_times))
    first = fingerprint.fingerprint_database(governance_engine)
    second = fingerprint.fingerprint_database(governance_engine)

    assert first["captured_at"] != second["captured_at"]
    assert first["overall_sha256"] == second["overall_sha256"]
    assert fingerprint.compare_fingerprints(first, second) == []
    assert first["database_context"] == {
        "alembic_heads": ["20260813_0002"],
        "database_schema": "main",
        "dialect": "sqlite",
    }
    datasets = first["datasets"]
    assert isinstance(datasets, dict)
    assert datasets["ip_rule_sets"]["count"] == 1
    assert datasets["ip_rule_versions"]["count"] == 1
    assert datasets["company_ip_rule_policies"]["count"] == 1
    # Governance action OR governance target is included. The similarly
    # spelled wildcard trap matches neither side and remains excluded.
    assert datasets["audit_events_ip_rule_governance"]["count"] == 3
    assert datasets["ip_rule_sets"]["max_timestamp"] == "2026-08-14T10:30:00.000000Z"

    emitted = json.dumps(first, sort_keys=True)
    for sensitive_value in (
        "private-company-id",
        "Confidential Operator",
        "private.example",
        "private_rule_detail",
        "audit detail",
    ):
        assert sensitive_value not in emitted


def test_content_mutation_changes_dataset_and_overall_hash(
    governance_engine: Engine,
) -> None:
    before = fingerprint.fingerprint_database(governance_engine)
    with governance_engine.begin() as connection:
        connection.execute(
            update(CompanyIpRulePolicy)
            .where(CompanyIpRulePolicy.id == "policy-1")
            .values(internal_target_policy_json={"changed": True}, version=2)
        )
    after = fingerprint.fingerprint_database(governance_engine)

    before_datasets = before["datasets"]
    after_datasets = after["datasets"]
    assert isinstance(before_datasets, dict) and isinstance(after_datasets, dict)
    assert (
        before_datasets["company_ip_rule_policies"]["content_sha256"]
        != after_datasets["company_ip_rule_policies"]["content_sha256"]
    )
    assert before_datasets["company_ip_rule_policies"]["count"] == 1
    assert after_datasets["company_ip_rule_policies"]["count"] == 1
    assert before["overall_sha256"] != after["overall_sha256"]
    assert fingerprint.compare_fingerprints(before, after) == ["company_ip_rule_policies"]


def test_fingerprint_issues_no_write_or_commit(governance_engine: Engine) -> None:
    statements: list[str] = []
    commits: list[bool] = []

    def record_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        statements.append(statement.strip().upper())

    event.listen(governance_engine, "before_cursor_execute", record_statement)
    event.listen(governance_engine, "commit", lambda _connection: commits.append(True))
    try:
        before_counts = _counts(governance_engine)
        fingerprint.fingerprint_database(governance_engine)
        after_counts = _counts(governance_engine)
    finally:
        event.remove(governance_engine, "before_cursor_execute", record_statement)

    assert before_counts == after_counts
    assert commits == []
    assert statements
    assert all(statement.startswith(("SELECT", "PRAGMA")) for statement in statements)


def test_cli_compare_exits_three_and_names_changed_dataset(
    governance_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    baseline = fingerprint.fingerprint_database(governance_engine)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    with governance_engine.begin() as connection:
        connection.execute(
            update(IpRuleVersion)
            .where(IpRuleVersion.id == "rule-version-1")
            .values(status="disabled")
        )
    monkeypatch.setattr(fingerprint, "get_engine", lambda: governance_engine)

    exit_code = fingerprint.main(["--compare", str(baseline_path)])
    output = capsys.readouterr()

    assert exit_code == 3
    assert json.loads(output.out)["overall_sha256"] != baseline["overall_sha256"]
    error = json.loads(output.err)
    assert error["error"] == "fingerprint_mismatch"
    assert error["mismatched_datasets"] == ["ip_rule_versions"]


def test_cli_fails_nonzero_without_partial_output_on_query_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_schema_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    monkeypatch.setattr(fingerprint, "get_engine", lambda: missing_schema_engine)

    exit_code = fingerprint.main([])
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    assert json.loads(output.err) == {
        "error": "fingerprint_failed",
        "type": "OperationalError",
    }


def test_cli_fails_nonzero_without_partial_output_on_serialization_error(
    governance_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = fingerprint._canonicalize

    def fail_on_persisted_id(value: object) -> object:
        if value == "rule-set-1":
            raise TypeError("deliberate serialization failure")
        return original(value)

    monkeypatch.setattr(fingerprint, "get_engine", lambda: governance_engine)
    monkeypatch.setattr(fingerprint, "_canonicalize", fail_on_persisted_id)

    exit_code = fingerprint.main([])
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    assert json.loads(output.err) == {
        "error": "fingerprint_failed",
        "type": "TypeError",
    }


def test_postgres_snapshot_asserts_read_only_and_bounded_statement_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakePostgresConnection(read_only="on")
    engine = _FakePostgresEngine(connection)
    expected = {"safe": "snapshot"}
    monkeypatch.setattr(fingerprint, "_collect_snapshot", lambda _connection: expected)

    assert fingerprint.fingerprint_database(engine) == expected  # type: ignore[arg-type]
    assert connection.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SET LOCAL statement_timeout = '60000ms'",
        "SELECT current_setting('transaction_read_only')",
        "SELECT current_setting('transaction_isolation')",
        "SELECT current_setting('statement_timeout')",
    ]
    assert connection.transaction.rolled_back is True


def test_postgres_snapshot_fails_if_database_does_not_confirm_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakePostgresConnection(read_only="off")
    engine = _FakePostgresEngine(connection)
    monkeypatch.setattr(
        fingerprint,
        "_collect_snapshot",
        lambda _connection: pytest.fail("collection must not begin without read-only proof"),
    )

    with pytest.raises(RuntimeError, match="did not enter a read-only transaction"):
        fingerprint.fingerprint_database(engine)  # type: ignore[arg-type]

    assert connection.transaction.rolled_back is True


def test_evidence_validator_ignores_capture_time_but_rejects_scope_drift(
    governance_engine: Engine,
    tmp_path: Path,
) -> None:
    validator = (
        Path(__file__).resolve().parents[3]
        / "scripts"
        / "validate_ip_rule_governance_fingerprint.py"
    )
    snapshot = fingerprint.fingerprint_database(governance_engine)
    snapshot_path = tmp_path / "snapshot.json"
    snapshot["captured_at"] = "2026-08-14T23:59:59.000000Z"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")

    unchanged = subprocess.run(
        [sys.executable, str(validator), str(snapshot_path), "--print-sha"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert unchanged.returncode == 0, unchanged.stderr
    assert unchanged.stdout.strip() == snapshot["overall_sha256"]

    snapshot["scope"]["read_control"]["stream_batch_size"] = 999  # type: ignore[index]
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    drifted = subprocess.run(
        [sys.executable, str(validator), str(snapshot_path)],
        capture_output=True,
        check=False,
        text=True,
    )
    assert drifted.returncode == 1
    assert "read_control" in drifted.stderr


def test_one_off_job_wrapper_requires_image_digest_and_has_no_scheduler() -> None:
    script = (
        Path(__file__).resolve().parents[3] / "scripts" / "ip-rule-governance-fingerprint-job.sh"
    ).read_text(encoding="utf-8")
    configure_block = script.split("configure)", maxsplit=1)[1].split(";;", maxsplit=1)[0]

    assert "caseops-api@sha256:" in script
    assert "--max-retries 0" in script
    assert "--expect-sha256=" in script
    assert "validate_job" in script
    assert "validate_execution" in script
    assert 'EXECUTION_LABEL="${EXECUTION##*/}"' in script
    assert "CASEOPS_AUTH_SECRET=caseops-auth-secret:latest" in script
    assert '"CASEOPS_AUTH_SECRET": "caseops-auth-secret"' in script
    assert "gcloud run jobs execute" not in configure_block
    assert "gcloud scheduler" not in script

    deploy_script = (Path(__file__).resolve().parents[3] / "scripts" / "deploy-prod.sh").read_text(
        encoding="utf-8"
    )
    hook_position = deploy_script.index("A0 pre-route rule-governance fingerprint")
    assert "CASEOPS_A0_CAPTURE_RULE_GOVERNANCE_BASELINE:-false" in deploy_script
    assert deploy_script.index("scheduler_inventory.py reconcile") < hook_position
    assert hook_position < deploy_script.index("--- 4/6 deploy caseops-api")
    assert "caseops-ip-qa-bootstrap" in deploy_script
    assert "NONTERMINAL" in deploy_script


class _FakeScalarResult:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _FakeTransaction:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


class _FakePostgresConnection:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, *, read_only: str) -> None:
        self.read_only = read_only
        self.statements: list[str] = []
        self.transaction = _FakeTransaction()

    def __enter__(self) -> _FakePostgresConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def begin(self) -> _FakeTransaction:
        return self.transaction

    def exec_driver_sql(self, statement: str) -> _FakeScalarResult:
        self.statements.append(statement)
        if "transaction_isolation" in statement:
            return _FakeScalarResult("repeatable read")
        if "statement_timeout" in statement and statement.startswith("SELECT"):
            return _FakeScalarResult("1min")
        return _FakeScalarResult(self.read_only)


class _FakePostgresEngine:
    dialect = SimpleNamespace(name="postgresql")

    def __init__(self, connection: _FakePostgresConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakePostgresConnection:
        return self.connection


def _counts(engine: Engine) -> tuple[int, int, int, int]:
    with engine.connect() as connection:
        return (
            int(connection.scalar(select(func.count()).select_from(IpRuleSet)) or 0),
            int(connection.scalar(select(func.count()).select_from(IpRuleVersion)) or 0),
            int(connection.scalar(select(func.count()).select_from(CompanyIpRulePolicy)) or 0),
            int(connection.scalar(select(func.count()).select_from(AuditEvent)) or 0),
        )
