from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "pytest_shard_plan.py"
SPEC = importlib.util.spec_from_file_location("pytest_shard_plan", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
pytest_shard_plan = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pytest_shard_plan
SPEC.loader.exec_module(pytest_shard_plan)


def _test_file(root: Path, name: str, lines: int) -> None:
    (root / name).write_text("\n".join("pass" for _ in range(lines)) + "\n")


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
