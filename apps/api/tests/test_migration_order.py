"""Validate Alembic's revision graph, including explicit merge nodes.

Intentional branches must rejoin at one upgrade head. Duplicate revisions or
parent edges, missing parents and cycles remain errors even when a separate
component has an apparently valid head.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
RevisionRow = tuple[Path, str, tuple[str, ...]]


def _load_revision(path: Path) -> tuple[str, tuple[str, ...]]:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    rev = getattr(module, "revision", None)
    down = getattr(module, "down_revision", None)
    assert isinstance(rev, str) and rev, (
        f"{path.name}: 'revision' must be a non-empty string."
    )
    if down is None:
        parents = ()
    elif isinstance(down, str):
        assert down, f"{path.name}: parent revision must be a non-empty string."
        parents = (down,)
    else:
        assert isinstance(down, tuple) and down, (
            f"{path.name}: 'down_revision' must be None, a non-empty string "
            "or a non-empty tuple of parent revision strings."
        )
        assert all(isinstance(parent, str) and parent for parent in down), (
            f"{path.name}: each parent revision must be a non-empty string."
        )
        parents = down
    assert len(parents) == len(set(parents)), (
        f"{path.name}: duplicate parent revisions are not allowed."
    )
    return rev, parents


def _collect() -> list[RevisionRow]:
    rows = []
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        rev, parents = _load_revision(path)
        rows.append((path, rev, parents))
    return rows


def _require_unique_revisions(rows: list[RevisionRow]) -> None:
    seen: dict[str, Path] = {}
    for path, rev, _ in rows:
        assert rev not in seen, (
            f"Duplicate revision id {rev!r}: {seen[rev].name} and {path.name}."
        )
        seen[rev] = path


def _require_known_parents(rows: list[RevisionRow]) -> None:
    known = {rev for _, rev, _ in rows}
    for path, _, parents in rows:
        for parent in parents:
            assert parent in known, (
                f"{path.name}: down_revision {parent!r} does not exist on disk."
            )


def _require_acyclic(rows: list[RevisionRow]) -> None:
    # Consume all components: a head in one must not hide a cycle in another.
    remaining = {rev: len(parents) for _, rev, parents in rows}
    children: dict[str, list[str]] = {rev: [] for rev in remaining}
    for _, rev, parents in rows:
        for parent in parents:
            children[parent].append(rev)
    ready = [rev for rev, count in remaining.items() if count == 0]
    visited = 0
    while ready:
        parent = ready.pop()
        visited += 1
        for child in children[parent]:
            remaining[child] -= 1
            if remaining[child] == 0:
                ready.append(child)
    assert visited == len(rows), (
        "Migration graph contains a cycle: "
        f"{sorted(rev for rev, count in remaining.items() if count)}."
    )


def _require_single_head(rows: list[RevisionRow]) -> str:
    known = {rev for _, rev, _ in rows}
    parents = {parent for _, _, edges in rows for parent in edges}
    heads = known - parents
    assert len(heads) == 1, (
        f"Expected exactly one head revision, got {len(heads)}: {sorted(heads)}. "
        "Alembic needs a single head to upgrade."
    )
    return heads.pop()


def _validate_graph(rows: list[RevisionRow]) -> str:
    _require_unique_revisions(rows)
    _require_known_parents(rows)
    _require_acyclic(rows)
    return _require_single_head(rows)


def test_no_duplicate_revision_ids() -> None:
    _require_unique_revisions(_collect())


def test_every_down_revision_exists() -> None:
    _require_known_parents(_collect())


def test_no_forked_chain() -> None:
    """Reject unresolved branches while allowing an explicit acyclic join."""
    _validate_graph(_collect())


def test_single_head() -> None:
    _require_single_head(_collect())


def _graph(*definitions: tuple[str, tuple[str, ...]]) -> list[RevisionRow]:
    return [(Path(rev + ".py"), rev, parents) for rev, parents in definitions]


def test_explicit_merge_joins_both_histories_into_exact_single_head() -> None:
    rows = _graph(
        ("base", ()), ("native", ("base",)), ("worker", ("base",)),
        ("join", ("native", "worker")), ("next", ("join",)),
    )
    assert _validate_graph(rows) == "next"


def test_unmerged_branch_is_still_rejected() -> None:
    rows = _graph(("base", ()), ("native", ("base",)), ("worker", ("base",)))
    with pytest.raises(AssertionError, match="exactly one head"):
        _validate_graph(rows)


def test_cycle_cannot_hide_behind_a_separate_valid_head() -> None:
    rows = _graph(("base", ()), ("head", ("base",)), ("a", ("b",)), ("b", ("a",)))
    with pytest.raises(AssertionError, match="contains a cycle"):
        _validate_graph(rows)


def test_merge_requires_every_parent_to_exist() -> None:
    rows = _graph(("base", ()), ("join", ("base", "missing")))
    with pytest.raises(AssertionError, match="missing.*does not exist"):
        _validate_graph(rows)


def test_duplicate_revision_is_still_rejected() -> None:
    rows = _graph(("base", ()), ("base", ()), ("head", ("base",)))
    with pytest.raises(AssertionError, match="Duplicate revision id"):
        _validate_graph(rows)


@pytest.mark.parametrize("parents", [(), ("base", "base"), ("base", None),
                                   ("base", 1), [], {}, 1, False, ""])
def test_revision_loader_rejects_malformed_or_duplicate_parents(tmp_path, parents) -> None:
    path = tmp_path / "revision.py"
    path.write_text(f"revision = 'child'\ndown_revision = {parents!r}\n")
    with pytest.raises(AssertionError):
        _load_revision(path)


@pytest.mark.parametrize("revision", [None, "", [], 123])
def test_revision_loader_rejects_invalid_revision_identity(tmp_path, revision) -> None:
    path = tmp_path / "revision.py"
    path.write_text(f"revision = {revision!r}\ndown_revision = None\n")
    with pytest.raises(AssertionError, match="revision.*non-empty string"):
        _load_revision(path)


@pytest.mark.parametrize(("declared", "expected"), [
    (None, ()), ("base", ("base",)), (("native", "worker"), ("native", "worker")),
])
def test_revision_loader_preserves_all_supported_parent_edges(tmp_path, declared, expected) -> None:
    path = tmp_path / "revision.py"
    path.write_text(f"revision = 'child'\ndown_revision = {declared!r}\n")
    assert _load_revision(path) == ("child", expected)
