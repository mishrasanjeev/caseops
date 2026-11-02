import json
from types import SimpleNamespace

import pytest

from caseops_api.db import migrations
from caseops_api.services import case_tracking_summary, court_sync_jobs, document_jobs
from caseops_api.services import qa_document_quiescence as gate
from caseops_api.workers import document_processor as worker


@pytest.fixture
def document_worker_settings(monkeypatch):
    settings = SimpleNamespace(
        env="local",
        auto_migrate=True,
        document_worker_batch_size=5,
        document_worker_poll_interval_seconds=10,
        document_processing_stale_after_minutes=15,
        document_retry_after_hours=24,
        document_reindex_after_hours=24,
        document_reprocessing_batch_size=5,
        court_sync_worker_batch_size=5,
        court_sync_stale_after_minutes=15,
    )
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    return settings


class Clock:
    def __init__(self):
        self.value = 0
        self.sleeps = []

    def monotonic(self):
        return self.value

    def sleep(self, value):
        self.sleeps.append(value)
        self.value += value


@pytest.mark.parametrize(
    "reason",
    [
        "qa_document_tenant_inventory_changed",
        "qa_document_queue_not_quiescent",
    ],
)
def test_quiescence_cli_retains_safe_actionable_blocker_code(
    monkeypatch,
    capsys,
    document_worker_settings,
    reason,
):
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = True

    def observe():
        raise RuntimeError(reason)

    monkeypatch.setattr(gate, "wait_for_qa_document_quiescence", observe)
    assert (
        worker.main(
            [
                "--require-qa-quiescence",
                "--documents-only",
                "--once",
                "--skip-migrations",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert json.loads(output.err)["reason_code"] == reason
    assert output.out == ""


@pytest.mark.parametrize("ids", [(), ("a", "b", "c", "d"), ("",), (None,), ("a", "a")])
def test_queue_scope_cannot_turn_missing_or_invalid_identity_into_empty_success(ids):
    session = SimpleNamespace(scalar=lambda *_: pytest.fail("Invalid scope reached SQL"))
    with pytest.raises(ValueError, match="invalid_document_queue_scope"):
        gate.pending_document_jobs(session, ids)


@pytest.mark.parametrize("pending", [[], [True], [True, False, True]])
def test_quiescence_requires_two_consecutive_idle_observations(monkeypatch, pending):
    clock = Clock()
    monkeypatch.setattr(gate, "time", clock)
    values = iter([*pending, False, False])
    calls = []

    def snapshot():
        calls.append(True)
        return ("qa-a", "qa-b", "qa-c"), next(values)

    monkeypatch.setattr(gate, "_pending_snapshot", snapshot)
    receipt = gate.wait_for_qa_document_quiescence()
    assert receipt == {
        "schema_version": 1,
        "status": "ok",
        "company_count": 3,
        "stable_observations": 2,
        "polls": len(pending) + 2,
        "elapsed_seconds": 2 * (len(pending) + 1),
    }
    assert len(clock.sleeps) == len(calls) - 1


def test_quiescence_times_out_without_claiming_or_reclassifying_work(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(gate, "time", clock)
    monkeypatch.setattr(gate, "_pending_snapshot", lambda: (("a", "b", "c"), True))
    with pytest.raises(RuntimeError, match="qa_document_queue_not_quiescent"):
        gate.wait_for_qa_document_quiescence()
    assert clock.value == 300
    assert len(clock.sleeps) == 150


def test_quiescence_rejects_changed_tenant_inventory(monkeypatch):
    monkeypatch.setattr(gate, "time", Clock())
    rows = iter([(("a", "b", "c"), False), (("a", "b", "replacement"), False)])
    monkeypatch.setattr(gate, "_pending_snapshot", lambda: next(rows))
    with pytest.raises(RuntimeError, match="qa_document_tenant_inventory_changed"):
        gate.wait_for_qa_document_quiescence()


@pytest.mark.parametrize(
    "args",
    [
        ["--require-qa-quiescence"],
        ["--require-qa-quiescence", "--documents-only", "--once"],
        [
            "--require-qa-quiescence",
            "--documents-only",
            "--once",
            "--skip-migrations",
            "--admission-disabled",
        ],
    ],
)
def test_quiescence_cli_rejects_incomplete_or_disabled_mode(
    monkeypatch,
    document_worker_settings,
    args,
):
    monkeypatch.setattr(
        gate, "wait_for_qa_document_quiescence", lambda: pytest.fail("Gate invoked")
    )
    with pytest.raises(SystemExit) as raised:
        worker.main(args)
    assert raised.value.code == 2


@pytest.mark.parametrize("protocol,admission", [(0, True), (1, False), (1, None)])
def test_quiescence_cli_cannot_report_disabled_startup_as_idle(
    monkeypatch,
    document_worker_settings,
    protocol,
    admission,
):
    document_worker_settings.document_worker_admission_protocol_version = protocol
    document_worker_settings.document_worker_admission_enabled = admission
    monkeypatch.setattr(
        gate, "wait_for_qa_document_quiescence", lambda: pytest.fail("Gate invoked")
    )
    with pytest.raises(SystemExit) as raised:
        worker.main(["--require-qa-quiescence", "--documents-only", "--once", "--skip-migrations"])
    assert raised.value.code == 2


@pytest.mark.parametrize("failure", [False, True])
def test_quiescence_cli_only_observes_queue_and_sanitizes_failure(
    monkeypatch,
    capsys,
    document_worker_settings,
    failure,
):
    document_worker_settings.env = "production"
    document_worker_settings.document_worker_admission_protocol_version = 1
    document_worker_settings.document_worker_admission_enabled = True
    for module, names in (
        (migrations, ("run_migrations",)),
        (worker, ("run_worker_iteration",)),
        (document_jobs, (
            "drain_document_processing_jobs", "recover_stale_document_processing_jobs",
            "enqueue_scheduled_document_reprocessing",
        )),
        (court_sync_jobs, ("drain_matter_court_sync_jobs",)),
        (case_tracking_summary, ("drain_update_summaries",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, lambda **_: pytest.fail("Mutation path invoked"))

    def observe():
        if failure:
            raise RuntimeError("private error and credential must not leave memory")
        return {"status": "ok", "stable_observations": 2}

    monkeypatch.setattr(gate, "wait_for_qa_document_quiescence", observe)
    assert worker.main(
        [
            "--require-qa-quiescence",
            "--documents-only",
            "--once",
            "--skip-migrations",
        ]
    ) == int(failure)
    output = capsys.readouterr()
    assert "private error" not in output.err
    if failure:
        assert '"status": "blocked"' in output.err
        assert output.out == ""
    else:
        assert output.out.startswith("CASEOPS_QA_DOCUMENT_QUIESCENCE ")
        assert output.err == ""
