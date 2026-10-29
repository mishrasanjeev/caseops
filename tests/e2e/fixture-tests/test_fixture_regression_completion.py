"""Completion evidence must fail closed without swallowing controller interruptions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import runpy
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(os.environ.get("CASEOPS_IP_FIXTURE_SOURCE_ROOT", str(Path(__file__).resolve().parents[3])))
SQLITE_MODULE = "tests/e2e/fixture-tests/test_ip_entitlement_fixture.py"
CONTROLLER_MODULE = "tests/e2e/fixture-tests/test_fixture_regression_completion.py"
PASSED_PHASES = [{"phase": "process", "passed": 19}, {"phase": "sqlite", "passed": 51},
                 {"phase": "controller", "passed": 6}]


def read_journal(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def controller(tmp_path, monkeypatch):
    namespace = runpy.run_path(str(ROOT / "scripts/e2e_fixture_regression.py"))
    namespace = namespace["main"].__globals__
    for key in list(os.environ):
        if key.upper().startswith("PG"):
            monkeypatch.delenv(key)
    results = tmp_path / "results"
    monkeypatch.setattr(sys, "argv", ["e2e_fixture_regression.py",
        "--results-directory", str(results), "--scratch-root", str(tmp_path), "--node", sys.executable])
    case = SimpleNamespace(main=namespace["main"], results=results, phases=[], reconciled=[],
        snapshots=0, phase_error=None, source_error=None, final_snapshot_events=[],
        source={"head": "controller-unit-source", "files": {"fixture-input": "unchanged"}})

    def phase(name, argv, env, directory, journal, run_deadline, supervisor):
        directory.mkdir()
        case.phases.append(name)
        assert run_deadline > 0
        assert callable(supervisor.cleanup)
        if name == "controller":
            assert argv[:6] == [sys.executable, "-B", "-m", "pytest", "-p", "fixture_test_evidence"]
            assert argv[-1] == str(namespace["TESTS"] / "test_fixture_regression_completion.py")
            assert "--junitxml=" + str(directory / "junit.xml") in argv
            assert env["CASEOPS_IP_FIXTURE_PHASE_JOURNAL"] == str(directory / "phases.jsonl")
            assert namespace["PHASE_TIMEOUT_SECONDS"] == 180
            assert namespace["RUN_TIMEOUT_SECONDS"] == 210
            assert namespace["REAP_SECONDS"] == 5
            if case.phase_error is not None:
                raise case.phase_error

    def reconcile_node(directory):
        assert directory.name == "process"
        case.reconciled.append(("process", 19, None))
        return [f"process-{index}" for index in range(19)]

    def reconcile_python(directory, count=51, module=SQLITE_MODULE):
        assert (directory.name, count, module) in {
            ("sqlite", 51, SQLITE_MODULE), ("controller", 6, CONTROLLER_MODULE)}
        case.reconciled.append((directory.name, count, module))
        return [f"{module}::test_case_{index}" for index in range(count)]

    def source_snapshot():
        case.snapshots += 1
        if case.phases == ["process", "sqlite", "controller"]:
            case.final_snapshot_events = read_journal(results / "supervisor.jsonl")
            if case.source_error is not None:
                raise case.source_error
        return case.source

    monkeypatch.setitem(namespace, "run_phase", phase)
    monkeypatch.setitem(namespace, "reconcile_node", reconcile_node)
    monkeypatch.setitem(namespace, "reconcile_sqlite", reconcile_python)
    monkeypatch.setitem(namespace, "snapshot", source_snapshot)
    return case


def assert_incomplete(case, error, *, source_failure=False):
    state = json.loads((case.results / "completion.json").read_text(encoding="utf-8"))
    events = read_journal(case.results / "supervisor.jsonl")
    assert state["complete"] is False
    assert state["passed"] is False
    assert state["expected"] == {"controller": 6, "process": 19, "sqlite": 51}
    assert sum(state["expected"].values()) == 76
    assert events[-1] == {"event": "incomplete_final", "passed": False}
    assert not any(item["event"] == "complete" for item in events)
    assert json.loads((case.results / "source-before.json").read_text(encoding="utf-8")) == case.source
    assert case.phases == ["process", "sqlite", "controller"]
    assert case.snapshots == 4
    assert state["phases"] == (PASSED_PHASES if source_failure else PASSED_PHASES[:2])
    assert case.reconciled == [("process", 19, None), ("sqlite", 51, SQLITE_MODULE)] + (
        [("controller", 6, CONTROLLER_MODULE)] if source_failure else [])
    assert (case.results / "sqlite/reconciled.json").is_file()
    if source_failure:
        assert state["source_error_type"] == type(error).__name__
        assert "error_type" not in state
        assert state.get("source_unchanged") is not True
        assert not (case.results / "source-after.json").exists()
        proof = json.loads((case.results / "controller/reconciled.json").read_text(encoding="utf-8"))
        assert proof == {"complete": True,
                         "ids": [f"{CONTROLLER_MODULE}::test_case_{index}" for index in range(6)]}
        assert [item["phase"] for item in events if item["event"] == "verified"] == case.phases
    else:
        assert state["error_type"] == type(error).__name__
        assert "source_error_type" not in state
        assert state["source_unchanged"] is True
        assert json.loads((case.results / "source-after.json").read_text(encoding="utf-8")) == case.source
        assert {"event": "incomplete", "error_type": type(error).__name__} in case.final_snapshot_events
        assert not (case.results / "controller/reconciled.json").exists()
        assert [item["phase"] for item in events if item["event"] == "verified"] == ["process", "sqlite"]


def test_main_phase_keyboard_interrupt_is_incomplete(controller):
    error = controller.phase_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught:
        controller.main()
    assert caught.value is error
    assert_incomplete(controller, error)


def test_main_phase_system_exit_zero_is_incomplete(controller):
    error = controller.phase_error = SystemExit(0)
    with pytest.raises(SystemExit) as caught:
        controller.main()
    assert caught.value is error
    assert caught.value.code == 0
    assert_incomplete(controller, error)


def test_main_phase_generator_exit_is_incomplete(controller):
    error = controller.phase_error = GeneratorExit()
    with pytest.raises(GeneratorExit) as caught:
        controller.main()
    assert caught.value is error
    assert_incomplete(controller, error)


def test_final_snapshot_keyboard_interrupt_after_success_is_incomplete(controller):
    error = controller.source_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt) as caught:
        controller.main()
    assert caught.value is error
    assert_incomplete(controller, error, source_failure=True)


def test_final_snapshot_system_exit_zero_after_success_is_incomplete(controller):
    error = controller.source_error = SystemExit(0)
    with pytest.raises(SystemExit) as caught:
        controller.main()
    assert caught.value is error
    assert caught.value.code == 0
    assert_incomplete(controller, error, source_failure=True)


def test_main_phase_runtime_error_returns_failure(controller):
    error = controller.phase_error = RuntimeError("deterministic ordinary phase failure")
    assert controller.main() == 1
    assert_incomplete(controller, error)
