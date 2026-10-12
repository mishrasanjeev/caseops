"""Offline exact-release backup identity, completion and no-blind-retry controls."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
SHA = "a" * 40
PROJECT, REGION, INSTANCE = "perfect-period-305406", "asia-south1", "caseops-db"


@pytest.fixture
def backup_boundary(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("pre_migration_backup")
    base = datetime(2026, 10, 12, 17, 0, tzinfo=UTC)
    state = SimpleNamespace(calls=[], clock=0, mode="ok", fallback=False, polls=0)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return base + timedelta(seconds=state.clock)

    monkeypatch.setattr(module, "datetime", Clock)
    monkeypatch.setattr(module, "monotonic", lambda: state.clock)
    monkeypatch.setattr(module, "sleep", lambda seconds: setattr(
        state, "clock", state.clock + seconds,
    ))
    monkeypatch.setattr(module, "uuid4", lambda: SimpleNamespace(hex="b" * 32))
    description = f"caseops-pre-migration-{SHA}-{'b' * 32}"
    metadata = {"name": INSTANCE, "region": REGION, "state": "RUNNABLE",
                "connectionName": f"{PROJECT}:{REGION}:{INSTANCE}",
                "databaseVersion": "POSTGRES_17"}
    operation = {"name": "backup-op-123", "status": "RUNNING", "operationType": "BACKUP_VOLUME",
                 "targetId": INSTANCE, "targetProject": PROJECT, "backupContext": {"backupId": 123}}

    def run(arguments, *, expect_json, timeout):
        assert expect_json is True and 0 < timeout <= 60
        assert arguments[-4:-1] == ["--project", PROJECT, "--quiet"]
        state.calls.append(list(arguments))
        state.clock += 1
        command = arguments[:3]
        if command == ["sql", "instances", "describe"]:
            if state.mode.startswith("instance:"):
                field = state.mode.split(":")[1]
                return {**metadata, field: "wrong"}
            return dict(metadata)
        if command == ["sql", "operations", "list"]:
            assert "--limit=1000" in arguments
            assert not any(arg.startswith("--filter") for arg in arguments)
            rows = [{"name": f"prior-op-{number}", "status": "DONE",
                     "targetId": INSTANCE, "targetProject": PROJECT} for number in range(2)]
            if state.mode == "active":
                rows.append({**rows[0], "name": "older-running", "status": "RUNNING"})
            if state.mode == "saturated":
                rows = [{**rows[0], "name": f"saturated-{number}"} for number in range(1000)]
            if state.mode == "duplicate-operation":
                rows.append(rows[0])
            if state.mode == "unbound-operation":
                rows[0]["targetId"] = "other-instance"
            if state.mode.startswith("inventory-status-"):
                rows[0]["status"] = [] if state.mode.endswith("list") else {}
            return rows
        if command == ["sql", "backups", "create"]:
            assert arguments[arguments.index("--description") + 1] == description
            if state.mode == "unknown":
                raise module.inventory.InventoryError("private-credential-error-must-not-escape")
            result = dict(operation)
            if state.mode.startswith("operation:"):
                result[state.mode.split(":")[1]] = "wrong"
            if state.mode == "operation-error":
                result["error"] = {"errors": [{"code": "FAILED"}]}
            if state.mode.startswith("created-status-"):
                result["status"] = [] if state.mode.endswith("list") else {}
            return result
        if command == ["sql", "operations", "describe"]:
            state.polls += 1
            result = {**operation, "status": "RUNNING" if state.mode == "pending" else "DONE"}
            if state.fallback:
                result.pop("backupContext")
            if state.mode.startswith("polled-status-"):
                result["status"] = [] if state.mode.endswith("list") else {}
            return result
        backup = {"id": 123, "instance": INSTANCE, "description": description,
                  "type": "ON_DEMAND", "status": "SUCCESSFUL", "location": "asia",
                  "startTime": (base + timedelta(seconds=3)).isoformat(),
                  "endTime": (base + timedelta(seconds=state.clock - 1)).isoformat()}
        assert command != ["sql", "backups", "list"], "History scans are forbidden"
        assert command == ["sql", "backups", "describe"], "Only the admitted SQL commands may run"
        assert arguments[3] == "123"
        if state.mode.startswith("backup:"):
            backup[state.mode.split(":")[1]] = "wrong"
        if state.mode == "old-backup":
            backup["startTime"] = (base - timedelta(days=1)).isoformat()
        return backup

    monkeypatch.setattr(module.inventory, "run_gcloud", run)
    state.module = module
    state.invoke = lambda **kwargs: module.checkpoint(
        project=PROJECT, region=REGION, instance=INSTANCE, release_sha=SHA, **kwargs,
    )
    return state


def test_backup_requires_one_created_operation_and_successful_bound_readback(
    backup_boundary, capsys,
):
    state = backup_boundary
    receipt = state.invoke()
    assert receipt["operation"] == "backup-op-123" and receipt["backup_id"] == "123"
    assert state.polls == 1
    assert sum(call[:3] == ["sql", "backups", "create"] for call in state.calls) == 1
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [row["event"] for row in events] == [
        "backup_requested", "backup_operation_observed", "backup_operation", "backup_completed",
    ]
    assert all(row["release_sha"] == SHA and row["instance"] == INSTANCE for row in events)


@pytest.mark.parametrize("mode", [
    "instance:name", "instance:region", "instance:state", "instance:connectionName",
    "instance:databaseVersion", "active", "saturated", "duplicate-operation", "unbound-operation",
])
def test_unbound_or_busy_instance_is_rejected_before_backup_creation(backup_boundary, mode):
    state = backup_boundary
    state.mode = mode
    with pytest.raises(state.module.BackupError):
        state.invoke()
    assert not any(call[:3] == ["sql", "backups", "create"] for call in state.calls)


@pytest.mark.parametrize("mode", [
    "operation:name", "operation:targetId", "operation:targetProject", "operation:operationType",
    "operation:status", "operation-error", "backup:id", "backup:instance", "backup:description",
    "backup:type", "backup:status", "backup:startTime", "backup:endTime", "old-backup",
    "missing-backup-id", "pending", "unknown",
])
def test_failed_unknown_or_unbound_checkpoint_never_retries_creation(backup_boundary, mode, capsys):
    state = backup_boundary
    state.mode = mode
    state.fallback = mode == "missing-backup-id"
    with pytest.raises(state.module.BackupError) as caught:
        state.invoke(wait_seconds=12 if mode == "pending" else 720)
    assert sum(call[:3] == ["sql", "backups", "create"] for call in state.calls) == 1
    output = capsys.readouterr().out + str(caught.value)
    assert "backup_completed" not in output and "private-credential-error" not in output
    if mode == "operation-error":
        assert '"operation": "backup-op-123"' in output
        assert '"identity_validated": false' in output
    if mode == "pending":
        assert state.clock <= 12


def test_release_backup_is_between_worker_drain_and_migration_with_main_guards():
    script = (ROOT / "scripts/deploy-prod.sh").read_text(encoding="utf-8")
    backup = script.index("python scripts/pre_migration_backup.py")
    assert script.index("post-build pre-migration gate") < backup
    assert script.index("scheduler_inventory.py quiesce") < backup
    assert script.index('assert_current_main "pre-backup mutation gate"') < backup
    assert backup < script.index('assert_current_main "post-backup pre-migration gate"')
    assert backup < script.index("MIGRATION_JOB=caseops-migrate-job")
    assert "--instance caseops-db --release-sha" in script
    assert "SKIP_BACKUP" not in script


@pytest.mark.parametrize("boundary", ["inventory", "created", "polled"])
@pytest.mark.parametrize("shape", ["list", "dict"])
def test_malformed_status_remains_controlled_and_preserves_known_operation(
    backup_boundary, capsys, boundary, shape,
):
    state = backup_boundary
    state.mode = f"{boundary}-status-{shape}"
    with pytest.raises(state.module.BackupError):
        state.invoke()
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert not any(row["event"] == "backup_completed" for row in events)
    creations = sum(call[:3] == ["sql", "backups", "create"] for call in state.calls)
    assert creations == (0 if boundary == "inventory" else 1)
    if boundary != "inventory":
        candidate = next(row for row in events if row["event"] == "backup_operation_observed")
        assert candidate["operation"] == "backup-op-123"
        assert candidate["identity_validated"] is False
        assert candidate["status"] == ("unrecognized" if boundary == "created" else "RUNNING")
