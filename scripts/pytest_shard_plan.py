#!/usr/bin/env python3
"""Build deterministic, static-runtime-balanced pytest file shards.

The coverage suite executes whole test files so database fixtures and module
state stay isolated.  A simple alphabetical modulo split is deterministic,
but adding one file shifts every following file and can concentrate several
large suites in a single shard.  Source lines alone also underprice dense test
modules: every collected test can repeat expensive application/database fixture
setup even when its body is only a few lines.  This planner therefore uses a
deterministic largest-processing-time assignment with a portable hybrid cost:
source lines plus a fixed weight for every statically declared test.  It keeps
every file in exactly one shard without importing the test suite.  A small
evidence-backed registry can reserve singleton shards before the remaining
files are balanced.
"""
from __future__ import annotations

import argparse
import ast
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# Hosted-runner evidence on 2026-08-16 showed database-backed test setup taking
# roughly the same time as dozens of source lines.  Keep this static and
# history-independent: it adapts automatically as tests are added, while AST
# parsing avoids importing test modules or depending on a prior CI artifact.
TEST_DEFINITION_WEIGHT = 100

# Hosted run 31942321727 at exact head 9fe3e250 timed out after the next
# collected item entered each file: litigation strategy item 217, matter-file
# QA item 217, and legal-knowledge graph item 145.  Keep this small, reviewable
# registry path-based and fail closed if an entry is duplicated, renamed, or
# removed.  The files run as singleton shards; every other test file continues
# through the deterministic hybrid balancer.
RUNTIME_ISOLATED_TEST_FILES = (
    "test_legal_knowledge_graph.py",
    "test_litigation_strategy.py",
    "test_matter_file_qa.py",
)


@dataclass(frozen=True)
class Shard:
    """One deterministic pytest-file shard and its static workload estimate."""

    number: int
    estimated_lines: int
    estimated_test_definitions: int
    estimated_cost: int
    files: tuple[Path, ...]


def _line_count(path: Path) -> int:
    """Return a stable positive cost estimate without relying on CI history."""
    with path.open(encoding="utf-8") as handle:
        return max(1, sum(1 for _ in handle))


def _test_definition_count(path: Path) -> int:
    """Count declared tests without importing or collecting the test module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"Cannot build shard plan because {path} is invalid Python") from exc
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _resolve_isolated_files(
    *,
    test_root: Path,
    files: Sequence[Path],
    isolated_files: Sequence[str],
) -> tuple[Path, ...]:
    """Resolve a unique, existing set of test-root-relative registry paths."""
    normalized = tuple(PurePosixPath(item).as_posix() for item in isolated_files)
    if len(normalized) != len(set(normalized)):
        raise ValueError("isolated test file registry contains duplicate paths")
    invalid = sorted(item for item in normalized if item in {"", "."} or item.startswith("../"))
    if invalid:
        raise ValueError(f"isolated test file registry contains invalid paths: {invalid}")

    files_by_relative_path = {
        path.relative_to(test_root).as_posix(): path for path in files
    }
    missing = sorted(set(normalized) - files_by_relative_path.keys())
    if missing:
        raise ValueError(f"isolated test file registry paths are missing: {missing}")
    return tuple(files_by_relative_path[item] for item in sorted(normalized))


def build_plan(
    test_root: Path,
    total_shards: int,
    *,
    test_definition_weight: int = TEST_DEFINITION_WEIGHT,
    isolated_files: Sequence[str] = (),
) -> tuple[Shard, ...]:
    """Assign every ``test_*.py`` below *test_root* to one balanced shard.

    Ties are resolved by the shard number and POSIX relative path, making the
    result reproducible across operating systems and runners.
    """
    if total_shards < 1:
        raise ValueError("total_shards must be at least 1")
    if test_definition_weight < 0:
        raise ValueError("test_definition_weight must not be negative")

    files = sorted(
        (path for path in test_root.rglob("test_*.py") if path.is_file()),
        key=lambda path: path.relative_to(test_root).as_posix(),
    )
    if not files:
        raise ValueError(f"No pytest files found below {test_root}")
    if len(files) < total_shards:
        raise ValueError(
            f"{len(files)} test files cannot populate {total_shards} non-empty shards"
        )

    isolated_paths = _resolve_isolated_files(
        test_root=test_root,
        files=files,
        isolated_files=isolated_files,
    )
    if len(isolated_paths) >= total_shards:
        raise ValueError(
            "total_shards must leave at least one regular shard after isolated files"
        )

    weighted_files = sorted(
        (
            (
                path,
                _line_count(path),
                _test_definition_count(path),
            )
            for path in files
        ),
        key=lambda item: (
            -(item[1] + (item[2] * test_definition_weight)),
            item[0].relative_to(test_root).as_posix(),
        ),
    )
    assignments: list[list[Path]] = [[] for _ in range(total_shards)]
    line_loads = [0 for _ in range(total_shards)]
    test_definition_loads = [0 for _ in range(total_shards)]
    cost_loads = [0 for _ in range(total_shards)]

    weighted_by_path = {
        path: (lines, test_definitions)
        for path, lines, test_definitions in weighted_files
    }
    for index, path in enumerate(isolated_paths):
        lines, test_definitions = weighted_by_path[path]
        assignments[index].append(path)
        line_loads[index] = lines
        test_definition_loads[index] = test_definitions
        cost_loads[index] = lines + (test_definitions * test_definition_weight)

    for path, lines, test_definitions in weighted_files:
        if path in isolated_paths:
            continue
        cost = lines + (test_definitions * test_definition_weight)
        index = min(
            range(len(isolated_paths), total_shards),
            key=lambda candidate: (cost_loads[candidate], candidate),
        )
        assignments[index].append(path)
        line_loads[index] += lines
        test_definition_loads[index] += test_definitions
        cost_loads[index] += cost

    return tuple(
        Shard(
            number=index + 1,
            estimated_lines=line_loads[index],
            estimated_test_definitions=test_definition_loads[index],
            estimated_cost=cost_loads[index],
            files=tuple(
                sorted(
                    assignments[index],
                    key=lambda path: path.relative_to(test_root).as_posix(),
                )
            ),
        )
        for index in range(total_shards)
    )


def write_shard_file(
    *,
    test_root: Path,
    total_shards: int,
    shard: int,
    output: Path,
    isolated_files: Sequence[str] = (),
) -> Shard:
    """Write one selected shard as paths relative to the current API root."""
    plan = build_plan(
        test_root,
        total_shards,
        isolated_files=isolated_files,
    )
    if shard < 1 or shard > len(plan):
        raise ValueError(f"shard must be between 1 and {len(plan)}")
    selected = plan[shard - 1]
    if not selected.files:
        raise ValueError(f"Shard {shard}/{total_shards} is empty")

    # The workflow runs pytest from ``apps/api``, so retain the configured
    # test-root directory (``tests/...``) in the written paths.
    output.write_text(
        "\n".join(path.relative_to(test_root.parent).as_posix() for path in selected.files)
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Selected {len(selected.files)} test files for shard {shard}/{total_shards} "
        f"(estimated hybrid cost {selected.estimated_cost}: "
        f"{selected.estimated_lines} source lines + "
        f"{selected.estimated_test_definitions} test definitions x "
        f"{TEST_DEFINITION_WEIGHT}):"
    )
    for path in selected.files:
        print(f"  {path.relative_to(test_root).as_posix()}")
    print(
        "Estimated hybrid loads: "
        + ", ".join(f"{item.number}={item.estimated_cost}" for item in plan)
    )
    return selected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test-root", type=Path, required=True)
    parser.add_argument("--total-shards", type=int, required=True)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_shard_file(
        test_root=args.test_root,
        total_shards=args.total_shards,
        shard=args.shard,
        output=args.output,
        isolated_files=RUNTIME_ISOLATED_TEST_FILES,
    )


if __name__ == "__main__":
    main()
