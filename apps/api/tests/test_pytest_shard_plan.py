from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pytest_shard_plan.py"
SPEC = importlib.util.spec_from_file_location("pytest_shard_plan", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
pytest_shard_plan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pytest_shard_plan
SPEC.loader.exec_module(pytest_shard_plan)

EVIDENCE_ISOLATED_TEST_FILES = (
    "test_legal_knowledge_graph.py",
    "test_litigation_strategy.py",
    "test_matter_file_qa.py",
)


def _test_file(root: Path, name: str, lines: int) -> None:
    (root / name).write_text("\n".join("pass" for _ in range(lines)) + "\n")


def _run_planner_cli(
    *,
    test_root: Path,
    total_shards: int,
    shard: int,
    output: Path,
    isolated_files: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(SCRIPT_PATH),
        "--test-root",
        str(test_root),
        "--total-shards",
        str(total_shards),
        "--shard",
        str(shard),
        "--output",
        str(output),
    ]
    for path in isolated_files:
        command.extend(("--isolated-file", path))
    return subprocess.run(command, check=False, capture_output=True, text=True)


def test_plan_is_deterministic_balanced_and_covers_each_file_once(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    for name, lines in {
        "test_hundred.py": 100,
        "test_ninety.py": 90,
        "test_eighty.py": 80,
        "test_ten_a.py": 10,
        "test_ten_b.py": 10,
        "test_ten_c.py": 10,
    }.items():
        _test_file(root, name, lines)

    first = pytest_shard_plan.build_plan(root, 3)
    second = pytest_shard_plan.build_plan(root, 3)

    assert first == second
    assert [item.estimated_lines for item in first] == [100, 100, 100]
    assert [item.estimated_test_definitions for item in first] == [0, 0, 0]
    assert [item.estimated_cost for item in first] == [100, 100, 100]
    assert sorted(path.name for item in first for path in item.files) == sorted(
        path.name for path in root.glob("test_*.py")
    )


def test_write_shard_file_uses_test_root_relative_paths(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    nested = root / "nested"
    nested.mkdir(parents=True)
    _test_file(root, "test_alpha.py", 4)
    _test_file(nested, "test_beta.py", 3)
    output = tmp_path / "selected.txt"

    selected = pytest_shard_plan.write_shard_file(
        test_root=root,
        total_shards=2,
        shard=2,
        output=output,
    )

    assert selected.number == 2
    assert output.read_text(encoding="utf-8") == "tests/nested/test_beta.py\n"


def test_dense_test_modules_are_balanced_by_static_runtime_cost(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    _test_file(root, "test_long_but_sparse.py", 220)
    for name in ("test_dense_a.py", "test_dense_b.py"):
        (root / name).write_text(
            "\n".join(f"def test_case_{index}(): pass" for index in range(10)) + "\n",
            encoding="utf-8",
        )

    plan = pytest_shard_plan.build_plan(root, 2)

    assert sorted(item.estimated_test_definitions for item in plan) == [10, 10]
    assert all(len(item.files) >= 1 for item in plan)
    assert sorted(path.name for item in plan for path in item.files) == [
        "test_dense_a.py",
        "test_dense_b.py",
        "test_long_but_sparse.py",
    ]


def test_nested_class_and_async_tests_contribute_to_cost(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    (root / "test_shapes.py").write_text(
        "class TestShapes:\n"
        "    def test_method(self): pass\n"
        "\n"
        "async def test_async(): pass\n",
        encoding="utf-8",
    )

    shard = pytest_shard_plan.build_plan(root, 1)[0]

    assert shard.estimated_test_definitions == 2
    assert shard.estimated_cost == (
        shard.estimated_lines + 2 * pytest_shard_plan.TEST_DEFINITION_WEIGHT
    )


def test_registered_runtime_heavy_files_are_singleton_shards(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    for name, lines in {
        "test_heavy_b.py": 40,
        "test_regular_b.py": 30,
        "test_heavy_a.py": 20,
        "test_regular_a.py": 10,
    }.items():
        _test_file(root, name, lines)

    plan = pytest_shard_plan.build_plan(
        root,
        3,
        isolated_files=("test_heavy_b.py", "test_heavy_a.py"),
    )

    assert [[path.name for path in shard.files] for shard in plan] == [
        ["test_heavy_a.py"],
        ["test_heavy_b.py"],
        ["test_regular_a.py", "test_regular_b.py"],
    ]


def test_cli_defaults_to_no_repository_specific_isolation(tmp_path: Path) -> None:
    root = tmp_path / "arbitrary-tests"
    root.mkdir()
    _test_file(root, "test_alpha.py", 5)
    _test_file(root, "test_beta.py", 4)
    output = tmp_path / "default-shard.txt"

    result = _run_planner_cli(
        test_root=root,
        total_shards=2,
        shard=1,
        output=output,
    )

    assert result.returncode == 0, result.stderr
    assert output.read_text(encoding="utf-8") == "arbitrary-tests/test_alpha.py\n"


def test_cli_repeatable_isolated_file_flags_create_singleton_shards(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    for name, lines in {
        "test_heavy_b.py": 40,
        "test_regular_b.py": 30,
        "test_heavy_a.py": 20,
        "test_regular_a.py": 10,
    }.items():
        _test_file(root, name, lines)
    isolated = ("test_heavy_b.py", "test_heavy_a.py")

    for shard, expected in ((1, "test_heavy_a.py"), (2, "test_heavy_b.py")):
        output = tmp_path / f"isolated-shard-{shard}.txt"
        result = _run_planner_cli(
            test_root=root,
            total_shards=3,
            shard=shard,
            output=output,
            isolated_files=isolated,
        )

        assert result.returncode == 0, result.stderr
        assert output.read_text(encoding="utf-8") == f"tests/{expected}\n"


def test_cli_missing_isolated_file_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    _test_file(root, "test_alpha.py", 2)
    _test_file(root, "test_beta.py", 1)

    result = _run_planner_cli(
        test_root=root,
        total_shards=2,
        shard=1,
        output=tmp_path / "missing.txt",
        isolated_files=("test_missing.py",),
    )

    assert result.returncode != 0
    assert "isolated test file registry paths are missing" in result.stderr


def test_repository_runtime_registry_is_exact_once_and_leaves_ten_regular_shards() -> None:
    root = REPO_ROOT / "apps" / "api" / "tests"
    total_shards = 10 + len(EVIDENCE_ISOLATED_TEST_FILES)
    plan = pytest_shard_plan.build_plan(
        root,
        total_shards,
        isolated_files=EVIDENCE_ISOLATED_TEST_FILES,
    )
    expected_files = sorted(path.resolve() for path in root.rglob("test_*.py"))
    planned_files = [path.resolve() for shard in plan for path in shard.files]

    assert tuple(shard.files[0].name for shard in plan[:3]) == tuple(
        sorted(EVIDENCE_ISOLATED_TEST_FILES)
    )
    assert all(len(shard.files) == 1 for shard in plan[:3])
    assert len(plan[3:]) == 10
    assert all(shard.files for shard in plan[3:])
    assert sorted(planned_files) == expected_files
    assert len(planned_files) == len(set(planned_files))


@pytest.mark.parametrize("total_shards", [10, 16])
def test_repository_hybrid_plan_improves_legacy_line_only_peak_cost(
    total_shards: int,
) -> None:
    root = REPO_ROOT / "apps" / "api" / "tests"
    hybrid = pytest_shard_plan.build_plan(root, total_shards)
    legacy = pytest_shard_plan.build_plan(
        root,
        total_shards,
        test_definition_weight=0,
    )

    def hybrid_cost(shard: object) -> int:
        return shard.estimated_lines + (
            shard.estimated_test_definitions
            * pytest_shard_plan.TEST_DEFINITION_WEIGHT
        )

    hybrid_peak_cost = max(map(hybrid_cost, hybrid))
    legacy_peak_cost = max(map(hybrid_cost, legacy))
    hybrid_peak_tests = max(item.estimated_test_definitions for item in hybrid)
    legacy_peak_tests = max(item.estimated_test_definitions for item in legacy)
    expected_files = sorted(path.resolve() for path in root.rglob("test_*.py"))
    planned_files = [path.resolve() for shard in hybrid for path in shard.files]

    # "Materially" is intentional: a cosmetic reshuffle must not replace the
    # observed line-only plan.  The checked-in suite currently improves both
    # peaks by more than ten percent for the old and failed matrix sizes.
    assert hybrid_peak_cost * 100 <= legacy_peak_cost * 90
    assert hybrid_peak_tests * 100 <= legacy_peak_tests * 90
    assert sorted(planned_files) == expected_files
    assert len(planned_files) == len(set(planned_files))


def test_ci_workflow_keeps_coverage_shards_and_aggregation_fail_closed() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    parsed = yaml.safe_load(workflow)
    shard_job = parsed["jobs"]["api-test-shards"]
    aggregate_job = parsed["jobs"]["api"]
    total_shards = 10 + len(EVIDENCE_ISOLATED_TEST_FILES)

    assert shard_job["timeout-minutes"] == 90
    assert shard_job["strategy"]["max-parallel"] == 10
    assert shard_job["strategy"]["matrix"] == {
        "shard": list(range(1, total_shards + 1)),
        "total_shards": [total_shards],
    }
    steps_by_name = {step.get("name"): step for step in shard_job["steps"]}
    selection = steps_by_name["Select deterministic test shard"]
    isolated_flags = tuple(
        line.strip().split()[1]
        for line in selection["run"].splitlines()
        if line.strip().startswith("--isolated-file ")
    )
    assert isolated_flags == EVIDENCE_ISOLATED_TEST_FILES
    prepare = steps_by_name["Prepare coverage shard artifact"]
    upload = steps_by_name["Upload coverage shard data"]
    assert prepare["if"] == "always()"
    assert upload["if"] == "always()"
    assert upload["with"]["name"] == "api-coverage-shard-${{ matrix.shard }}"

    assert aggregate_job["needs"] == ["api-ruff", "api-test-shards"]
    assert aggregate_job["if"] == "always()"
    prerequisite = aggregate_job["steps"][0]
    assert prerequisite["name"] == "Fail if API prerequisites failed"
    assert "needs['api-test-shards'].result != 'success'" in prerequisite["if"]
    combine = next(
        step
        for step in aggregate_job["steps"]
        if step.get("name") == "Combine coverage reports"
    )
    assert "coverage combine coverage-parts/coverage-shard-*" in combine["run"]


@pytest.mark.parametrize(
    ("total_shards", "message"),
    [(0, "at least 1"), (3, "cannot populate")],
)
def test_plan_rejects_invalid_or_empty_shard_shapes(
    tmp_path: Path,
    total_shards: int,
    message: str,
) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    _test_file(root, "test_only.py", 1)

    with pytest.raises(ValueError, match=message):
        pytest_shard_plan.build_plan(root, total_shards)


def test_plan_rejects_negative_weight_and_invalid_python(tmp_path: Path) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    _test_file(root, "test_valid.py", 1)

    with pytest.raises(ValueError, match="must not be negative"):
        pytest_shard_plan.build_plan(root, 1, test_definition_weight=-1)

    (root / "test_invalid.py").write_text("def test_broken(:\n", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid Python"):
        pytest_shard_plan.build_plan(root, 1)


def test_plan_fails_closed_for_invalid_runtime_isolation_registry(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tests"
    root.mkdir()
    _test_file(root, "test_a.py", 2)
    _test_file(root, "test_b.py", 1)

    with pytest.raises(ValueError, match="duplicate paths"):
        pytest_shard_plan.build_plan(
            root,
            2,
            isolated_files=("test_a.py", "test_a.py"),
        )
    with pytest.raises(ValueError, match="paths are missing"):
        pytest_shard_plan.build_plan(
            root,
            2,
            isolated_files=("test_missing.py",),
        )
    with pytest.raises(ValueError, match="leave at least one regular shard"):
        pytest_shard_plan.build_plan(
            root,
            1,
            isolated_files=("test_a.py",),
        )
