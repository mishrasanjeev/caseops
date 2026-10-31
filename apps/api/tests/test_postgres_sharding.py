from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree

import pytest
import yaml

from tests.postgres_sharding import (
    _junit_identity,
    partition,
    pytest_collection_modifyitems,
    verify_reports,
)


def _render_postgres_matrix(value: str, shard: int, total: int) -> str:
    for key, replacement in {"shard": shard, "total_shards": total}.items():
        value = value.replace("${{ matrix." + key + " }}", str(replacement))
    assert "${{" not in value, "Every workflow placeholder must be resolved"
    return value


def test_ci_postgres_capacity_keeps_bounded_complete_acceptance():
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-validation-shards"]
    assert job["timeout-minutes"] == 12
    strategy = job["strategy"]
    assert strategy["fail-fast"] is False
    assert strategy.get("max-parallel") == 4
    assert strategy["matrix"] == {"total_shards": [32], "shard": list(range(1, 33))}
    total = strategy["matrix"]["total_shards"][0]
    assert job["name"] == "Postgres + pgvector shard ${{ matrix.shard }}/${{ matrix.total_shards }}"
    step = next(item for item in job["steps"] if item.get("name") == "Pytest -m postgres")
    # Pytest timing excludes launcher overhead; retain the original whole-job budget.
    assert "timeout-minutes" not in step
    assert shlex.split(step["run"]) == [
        "uv", "run", "python", "-m", "pytest", "-q", "-m", "postgres",
    ]
    assert "--postgres-shards=${{ matrix.total_shards }}" in step["env"]["PYTEST_ADDOPTS"]
    assert step["env"]["CASEOPS_READTHROUGH_EVIDENCE_DIR"] == (
        "${{ github.workspace }}/apps/api/postgres-shard-${{ matrix.shard }}-readthrough"
    )
    for shard in strategy["matrix"]["shard"]:
        options = shlex.split(_render_postgres_matrix(step["env"]["PYTEST_ADDOPTS"], shard, total))
        assert options == [
            "-p", "tests.postgres_sharding", f"--postgres-shard={shard}",
            f"--postgres-shards={total}", f"--postgres-inventory=postgres-shard-{shard}.json",
            f"--junitxml=postgres-shard-{shard}.xml",
            "-o", "faulthandler_timeout=60",
        ]
        journal = _render_postgres_matrix(step["env"]["CASEOPS_TEST_RESULT_JOURNAL"], shard, total)
        assert journal == f"postgres-shard-{shard}.jsonl"
        native = _render_postgres_matrix(
            step["env"]["CASEOPS_FINALIZER_EVIDENCE_DIR"], shard, total,
        )
        assert native == f"postgres-shard-{shard}-native"
    upload = next(item for item in job["steps"]
                  if item.get("name") == "Upload exact PostgreSQL collection and results")
    assert upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"
    assert upload["with"]["path"].splitlines() == [
        f"apps/api/postgres-shard-${{{{ matrix.shard }}}}.{extension}"
        for extension in ("json", "xml", "jsonl")
    ] + [
        "apps/api/postgres-shard-${{ matrix.shard }}-native/*.jsonl",
        "apps/api/postgres-shard-${{ matrix.shard }}-readthrough/",
        "apps/api/postgres-shard-${{ matrix.shard }}-query-plans/",
    ]
    aggregate = workflow["jobs"]["postgres-validation"]
    assert aggregate["needs"] == ["postgres-validation-shards"]
    assert aggregate["if"] == "always() && !cancelled()"
    guard = next(item for item in aggregate["steps"]
                 if item.get("name") == "Require every PostgreSQL shard")
    assert guard["if"] == "needs.postgres-validation-shards.result != 'success'"
    assert guard["run"] == "exit 1"
    reconcile = next(item for item in aggregate["steps"]
                     if item.get("name") == "Reconcile complete PostgreSQL acceptance")
    assert shlex.split(reconcile["run"]) == [
        "uv", "run", "--python", "3.13", "python", "-m", "tests.postgres_sharding",
        "postgres-evidence", "--total", str(total),
    ]
    assert "postgres-validation" in workflow["jobs"]["e2e"]["needs"]


@pytest.mark.parametrize("job", [
    "api-ruff", "api-test-shards", "api", "postgres-validation-shards", "postgres-validation",
])
def test_every_ci_api_consumer_selects_the_supported_python_before_resolution(job):
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    selected = False
    for step in workflow["jobs"][job]["steps"]:
        command = shlex.split(step.get("run", ""))
        if not command or command[0] != "uv":
            continue
        if command == ["uv", "python", "install", "3.13"]:
            selected = True
            continue
        versions = [
            command[index + 1] if argument == "--python" else argument.split("=", 1)[1]
            for index, argument in enumerate(command)
            if argument == "--python" or argument.startswith("--python=")
        ]
        assert all(version == "3.13" for version in versions), f"{job}: conflicting Python selector"
        assert selected or versions, (
            f"{job}: unpinned project resolution can select an unsupported Python"
        )


def test_ci_postgres_launcher_collects_and_executes_without_inherited_pythonpath(tmp_path):
    root = Path(__file__).resolve().parents[3]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["postgres-validation-shards"]
    matrix = job["strategy"]["matrix"]
    total = matrix["total_shards"][0]
    steps = job["steps"]
    assert job["timeout-minutes"] == 12
    assert total == 32 and matrix["shard"] == list(range(1, total + 1))
    step = next(item for item in steps if item.get("name") == "Pytest -m postgres")
    command = shlex.split(step["run"])
    assert command[:2] == ["uv", "run"]
    command = command[2:]
    command[0] = sys.executable if command[0] == "python" else shutil.which(command[0])
    assert command[0], "The workflow's Python entry point must be installed"
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    shutil.copyfile(
        Path(__file__).with_name("postgres_sharding.py"), tests / "postgres_sharding.py"
    )
    shutil.copyfile(
        Path(__file__).with_name("retained_results.py"), tests / "retained_results.py"
    )
    (tests / "conftest.py").write_text('pytest_plugins = ["tests.retained_results"]\n')
    (tests / "test_sample.py").write_text(
        "import pytest\n@pytest.mark.postgres\n@pytest.mark.parametrize('item', range(64))\n"
        "def test_marked(item):\n    assert item >= 0\n"
        "def test_unmarked():\n    raise AssertionError('Non-PostgreSQL test selected')\n"
    )
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers = postgres: PostgreSQL acceptance\n")
    environment = {key: value for key, value in os.environ.items()
                   if key not in {"PYTHONPATH", "PYTEST_ADDOPTS", "COVERAGE_PROCESS_START",
                                  "CASEOPS_TEST_RESULT_JOURNAL",
                                  "CASEOPS_TEST_RESULT_JOURNAL_OWNER_PID"}}
    environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    expected = sorted(f"tests/test_sample.py::test_marked[{item}]" for item in range(64))
    executed = []
    for shard in matrix["shard"]:
        for key in ("PYTEST_ADDOPTS", "CASEOPS_TEST_RESULT_JOURNAL"):
            environment[key] = _render_postgres_matrix(step["env"][key], shard, total)
        result = subprocess.run(command, cwd=tmp_path, env=environment, capture_output=True,
                                text=True, timeout=30, check=False)
        assert result.returncode == 0, result.stdout + result.stderr
        inventory = json.loads((tmp_path / f"postgres-shard-{shard}.json").read_text())
        selected = partition(expected, shard, total)
        assert inventory == {"shard": shard, "total": total, "nodeids": expected,
                             "selected": selected}
        executed.extend(selected)
        journal = [json.loads(line) for line in
                   (tmp_path / environment["CASEOPS_TEST_RESULT_JOURNAL"]).read_text().splitlines()]
        assert sorted(next(row["nodeids"] for row in journal if row["event"] == "collection")) == (
            selected
        )
        assert journal[-1] == {"event": "session_finished", "exitstatus": 0}
        reports = [row for row in journal if row["event"] == "test_report"]
        assert len(reports) == len(selected) * 3
        assert all(row["outcome"] == "passed" for row in reports)
        for phase in ("setup", "call", "teardown"):
            assert sorted(row["nodeid"] for row in reports if row["when"] == phase) == selected
    assert sorted(executed) == expected
    summary = {"status": "passed", "shards": total, "collected": len(expected), "skipped": 0}
    assert verify_reports(tmp_path, total) == summary
    evidence = tmp_path / "postgres-evidence"
    evidence.mkdir()
    for path in tmp_path.glob("postgres-shard-*.*"):
        shutil.copyfile(path, evidence / path.name)
    aggregate = next(item for item in workflow["jobs"]["postgres-validation"]["steps"]
                     if item.get("name") == "Reconcile complete PostgreSQL acceptance")
    aggregate_command = shlex.split(aggregate["run"])
    assert aggregate_command[:5] == ["uv", "run", "--python", "3.13", "python"]
    aggregate_command = [sys.executable, *aggregate_command[5:]]
    result = subprocess.run(aggregate_command, cwd=tmp_path, env=environment, capture_output=True,
                            text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == summary


@pytest.mark.parametrize("total", [4, 8, 16, 32])
def test_postgres_partition_is_complete_disjoint_and_order_independent(total):
    nodes = [f"tests/test_example.py::test_item[{index}]" for index in range(2301)]
    selections = [partition(nodes, shard, total) for shard in range(1, total + 1)]
    assert sorted(node for selected in selections for node in selected) == sorted(nodes)
    assert max(map(len, selections)) - min(map(len, selections)) == 1
    assert selections == [
        partition(list(reversed(nodes)), shard, total) for shard in range(1, total + 1)
    ]
    floor, remainder = divmod(len(nodes), total)
    assert sorted(map(len, selections)) == [floor] * (total - remainder) + [floor + 1] * remainder


def test_sixteen_shards_split_each_previous_shard_without_changing_its_inventory():
    nodes = [f"tests/test_example.py::test_item[{index}]" for index in range(3005)]
    for shard in range(1, 9):
        prior = partition(nodes, shard, 8)
        first, second = partition(nodes, shard, 16), partition(nodes, shard + 8, 16)
        assert set(first).isdisjoint(second)
        assert sorted(first + second) == prior
        assert abs(len(first) - len(second)) <= 1


@pytest.mark.parametrize("nodes,shard,total", [([], 1, 4), (["a", "a"], 1, 1),
    (["a"], 2, 4), (["a"], 0, 1), (["a"], 1, 33),
    (["a"], True, 1), (["a"], 1, True), (["a"], 1.0, 1), (["a"], 1, 1.0),
    ("abc", 1, 1), ({"a": None}, 1, 1), ([None], 1, 1), ([""], 1, 1), (["a", 1], 1, 1)])
def test_postgres_partition_rejects_incomplete_or_invalid_selections(nodes, shard, total):
    with pytest.raises(ValueError):
        partition(nodes, shard, total)


@pytest.mark.parametrize(
    "fault", [None, "missing", "drift", "skipped", "failure", "error", "wrong-node"]
)
@pytest.mark.parametrize("total", [4, 8, 16, 32])
def test_postgres_report_gate_requires_every_actual_success(tmp_path, fault, total):
    nodes = [f"tests/test_example.py::TestCases::test_item[{index}]" for index in range(64)]
    for shard in range(1, total + 1):
        selected = partition(nodes, shard, total)
        inventory = {"shard": shard, "total": total, "nodeids": nodes, "selected": selected}
        if fault == "drift" and shard == 1:
            inventory["nodeids"] = nodes[:-1]
        if fault != "missing" or shard != 1:
            (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            case = ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
            if shard == 1 and fault in ("skipped", "failure", "error"):
                ElementTree.SubElement(case, fault)
            if shard == 1 and fault == "wrong-node":
                case.set("name", "test_unselected")
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
    if fault is None:
        assert verify_reports(tmp_path, total) == {
            "status": "passed", "shards": total, "collected": 64, "skipped": 0
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, total)


# Independent literal source685 job/phase evidence, not imported from selector.
MEASURED_CASES = {
    (
        "tests/test_ip_import_review_gaps_20261013.py::"
        "test_thousand_same_mark_distinct_applicants_commit_has_linear_materialization"
    ): 10,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_pack_items]"
    ): 3,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_packs]"
    ): 6,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[recommendation_decisions]"
    ): 16,
}


def _measured_fixture_nodes():
    return sorted(
        [
            *(f"tests/test_sample.py::test_item[{i}]" for i in range(130)),
            *MEASURED_CASES,
            *(node + "-near-match" for node in MEASURED_CASES),
        ]
    )


@pytest.mark.parametrize("node,target", list(MEASURED_CASES.items()))
def test_measured_cases_use_only_the_reviewed_literal_target(node, target):
    nodes = _measured_fixture_nodes()
    locations = [shard for shard in range(1, 17) if node in partition(nodes, shard, 16)]
    assert locations == [target]


@pytest.mark.parametrize("total", [1, 2, 4, 8, 16, 32])
def test_measured_routing_keeps_the_complete_union_and_every_other_assignment(total):
    nodes = _measured_fixture_nodes()
    result = [partition(nodes, shard, total) for shard in range(1, total + 1)]
    flat = [node for group in result for node in group]
    assert len(flat) == len(set(flat)) == len(nodes)
    assert sorted(flat) == nodes
    actual = {node: shard for shard, group in enumerate(result, 1) for node in group}
    for index, node in enumerate(nodes):
        if total == 32:
            expected = _independent_child_assignments(nodes)[node]
        else:
            expected = (
                MEASURED_CASES[node] if total == 16 and node in MEASURED_CASES
                else index % total + 1
            )
        assert actual[node] == expected
    assert result == [
        partition(list(reversed(nodes)), shard, total) for shard in range(1, total + 1)
    ]


@pytest.mark.parametrize(
    "fault", [None, "old-allocation", "missing-relocated-case", "duplicate-relocated-case"]
)
def test_measured_routing_report_gate_rejects_old_or_incomplete_allocation(tmp_path, fault):
    nodes = _measured_fixture_nodes()
    ordinal = {node: index % 16 + 1 for index, node in enumerate(nodes)}
    expected = {node: MEASURED_CASES.get(node, ordinal[node]) for node in nodes}
    chosen = next(iter(MEASURED_CASES))
    for shard in range(1, 17):
        # Build expected artifacts independently of partition() under test.
        assignment = ordinal if fault == "old-allocation" else expected
        selected = [node for node in nodes if assignment[node] == shard]
        if shard == expected[chosen]:
            if fault == "missing-relocated-case":
                selected.remove(chosen)
            elif fault == "duplicate-relocated-case":
                selected.append(chosen)
        inventory = {"shard": shard, "total": 16, "nodeids": nodes, "selected": selected}
        (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
    if fault is None:
        assert verify_reports(tmp_path, 16) == {
            "status": "passed",
            "shards": 16,
            "collected": len(nodes),
            "skipped": 0,
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, 16)


def test_measured_collection_hook_keeps_selected_items_in_declaration_order(tmp_path):
    original = list(reversed(_measured_fixture_nodes()))
    ordered = sorted(original)
    destinations = {node: MEASURED_CASES.get(node, i % 16 + 1) for i, node in enumerate(ordered)}
    observed_targets = []
    for shard in (3, 6, 10, 16):
        inventory = tmp_path / f"postgres-shard-{shard}.json"
        options = {
            "--postgres-shard": shard,
            "--postgres-shards": 16,
            "--postgres-inventory": str(inventory),
        }
        deselected = []
        config = SimpleNamespace(
            getoption=options.__getitem__,
            hook=SimpleNamespace(
                pytest_deselected=lambda *, items, recorded=deselected: recorded.extend(
                    item.nodeid for item in items
                )
            ),
        )
        items = [
            SimpleNamespace(
                nodeid=node,
                get_closest_marker=lambda name: object() if name == "postgres" else None,
            )
            for node in original
        ]
        pytest_collection_modifyitems(config, items)
        assert [item.nodeid for item in items] == [
            node for node in original if destinations[node] == shard
        ]
        assert deselected == [node for node in original if destinations[node] != shard]
        assert json.loads(inventory.read_text())["selected"] == [
            node for node in ordered if destinations[node] == shard
        ]
        observed_targets.append(shard)
    assert observed_targets == [3, 6, 10, 16]


def _independent_child_assignments(nodes):
    ordered = sorted(nodes)
    parent = {node: MEASURED_CASES.get(node, i % 16 + 1) for i, node in enumerate(ordered)}
    assignment = {}
    for number in range(1, 17):
        members = [node for node in ordered if parent[node] == number]
        # Independent literal ABBA oracle; no partition() call or imported routing map.
        for index, node in enumerate(members):
            assignment[node] = number + (16 if index % 4 in (1, 2) else 0)
    return assignment


@pytest.mark.parametrize("size", [32, 33, 64, 65, 3005])
def test_thirty_two_children_keep_every_measured_parent_and_balance_its_prefix(size):
    nodes = [f"tests/test_sample.py::test_case[{i}]" for i in range(size)] + list(MEASURED_CASES)
    expected = _independent_child_assignments(nodes)
    actual = {}
    for parent in range(1, 17):
        previous = partition(nodes, parent, 16)
        first = partition(nodes, parent, 32)
        second = partition(nodes, parent + 16, 32)
        assert set(first).isdisjoint(second)
        assert sorted(first + second) == previous
        assert abs(len(first) - len(second)) <= 1
        actual.update({node: parent for node in first})
        actual.update({node: parent + 16 for node in second})
    assert actual == expected
    assert len(actual) == len(nodes)


@pytest.mark.parametrize(
    "fault", [None, "old-ordinal32", "old16", "missing-child", "duplicate-child",
              "wrong-parent", "duplicate-case"]
)
def test_thirty_two_report_gate_requires_the_exact_children_and_complete_union(tmp_path, fault):
    nodes = _measured_fixture_nodes()
    expected = _independent_child_assignments(nodes)
    assignment = dict(expected)
    if fault == "old-ordinal32":
        assignment = {node: i % 32 + 1 for i, node in enumerate(nodes)}
    elif fault == "old16":
        assignment = {node: MEASURED_CASES.get(node, i % 16 + 1)
                      for i, node in enumerate(nodes)}
    elif fault == "wrong-parent":
        chosen = next(iter(MEASURED_CASES))
        assignment[chosen] = (expected[chosen] % 16) + 1
    total = 16 if fault == "old16" else 32
    for child in range(1, total + 1):
        if fault == "missing-child" and child == 32:
            continue
        selected = [node for node in nodes if assignment[node] == child]
        if fault == "duplicate-case" and child == expected[nodes[0]]:
            selected.append(nodes[0])
        identity = 1 if fault == "duplicate-child" and child == 32 else child
        inventory = {"shard": identity, "total": total, "nodeids": nodes,
                     "selected": selected}
        (tmp_path / f"postgres-shard-{child}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{child}.xml")
    if fault is None:
        assert verify_reports(tmp_path, 32) == {
            "status": "passed", "shards": 32, "collected": len(nodes), "skipped": 0,
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, 32)


def test_child_collection_keeps_the_original_declaration_order(tmp_path):
    original = list(reversed(_measured_fixture_nodes()))
    expected = _independent_child_assignments(original)
    for child in range(1, 33):
        inventory = tmp_path / f"postgres-shard-{child}.json"
        options = {"--postgres-shard": child, "--postgres-shards": 32,
                   "--postgres-inventory": str(inventory)}
        deselected = []
        config = SimpleNamespace(
            getoption=options.__getitem__,
            hook=SimpleNamespace(
                pytest_deselected=lambda *, items, recorded=deselected: recorded.extend(
                    item.nodeid for item in items
                )
            ),
        )
        items = [SimpleNamespace(nodeid=node, get_closest_marker=lambda name: object())
                 for node in original]
        pytest_collection_modifyitems(config, items)
        assert [item.nodeid for item in items] == [
            node for node in original if expected[node] == child
        ]
        assert deselected == [node for node in original if expected[node] != child]
        assert json.loads(inventory.read_text())["selected"] == sorted(
            node for node in original if expected[node] == child
        )
