#!/usr/bin/env python3
"""Build deterministic, source-size-balanced pytest file shards.

The coverage suite executes whole test files so database fixtures and module
state stay isolated.  A simple alphabetical modulo split is deterministic,
but adding one file shifts every following file and can concentrate several
large suites in a single shard.  This planner uses a deterministic
largest-processing-time assignment with file line count as a portable cost
estimate.  It keeps every file in exactly one shard while avoiding that
avoidable concentration.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Shard:
    """One deterministic pytest-file shard and its estimated source load."""

    number: int
    estimated_lines: int
    files: tuple[Path, ...]


def _line_count(path: Path) -> int:
    """Return a stable positive cost estimate without relying on CI history."""
    with path.open(encoding="utf-8") as handle:
        return max(1, sum(1 for _ in handle))


def build_plan(test_root: Path, total_shards: int) -> tuple[Shard, ...]:
    """Assign every ``test_*.py`` below *test_root* to one balanced shard.

    Ties are resolved by the shard number and POSIX relative path, making the
    result reproducible across operating systems and runners.
    """
    if total_shards < 1:
        raise ValueError("total_shards must be at least 1")

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

    weighted_files = sorted(
        ((path, _line_count(path)) for path in files),
        key=lambda item: (-item[1], item[0].relative_to(test_root).as_posix()),
    )
    assignments: list[list[Path]] = [[] for _ in range(total_shards)]
    loads = [0 for _ in range(total_shards)]

    for path, cost in weighted_files:
        index = min(range(total_shards), key=lambda candidate: (loads[candidate], candidate))
        assignments[index].append(path)
        loads[index] += cost

    return tuple(
        Shard(
            number=index + 1,
            estimated_lines=loads[index],
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
) -> Shard:
    """Write one selected shard as paths relative to the current API root."""
    plan = build_plan(test_root, total_shards)
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
        f"(estimated source-line load {selected.estimated_lines}):"
    )
    for path in selected.files:
        print(f"  {path.relative_to(test_root).as_posix()}")
    print(
        "Estimated source-line loads: "
        + ", ".join(f"{item.number}={item.estimated_lines}" for item in plan)
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
    )


if __name__ == "__main__":
    main()
