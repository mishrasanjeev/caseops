"""Lint the alembic migration chain at test time.

Catches three common mistakes that only surface when you run `alembic
upgrade head` in production:

- A new migration reuses a revision id already on disk (duplicate keys).
- A new migration's ``down_revision`` points to a revision that does
  not exist on disk (typo, bad rebase).
- Two migrations share the same ``down_revision`` — the tree has
  branched. Alembic will refuse to upgrade without an explicit merge
  revision, so this is a CI-level regression.

None of these are caught by pytest today because the harness applies
migrations from scratch in dependency order, so a duplicate or branch
can coexist with a passing suite until the first time someone runs
against an existing database.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_REV_RE = re.compile(r"^revision\s*[:=]", re.M)
_DOWN_RE = re.compile(r"^down_revision\s*[:=]", re.M)


def _load_revision(path: Path) -> tuple[str, str | None]:
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec is not None and spec.loader is not None, path
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    rev = getattr(module, "revision", None)
    down = getattr(module, "down_revision", None)
    assert isinstance(rev, str) and rev, (
        f"{path.name}: 'revision' must be a non-empty string."
    )
    assert down is None or isinstance(down, str), (
        f"{path.name}: 'down_revision' must be None or a string."
    )
    return rev, down


def _collect() -> list[tuple[Path, str, str | None]]:
    rows: list[tuple[Path, str, str | None]] = []
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        if path.name.startswith("__"):
            continue
        rev, down = _load_revision(path)
        rows.append((path, rev, down))
    return rows


def test_no_duplicate_revision_ids() -> None:
    seen: dict[str, Path] = {}
    for path, rev, _ in _collect():
        assert rev not in seen, (
            f"Duplicate revision id {rev!r}: {seen[rev].name} and {path.name}."
        )
        seen[rev] = path


def test_every_down_revision_exists() -> None:
    rows = _collect()
    known = {rev for _, rev, _ in rows}
    for path, _, down in rows:
        if down is None:
            continue
        assert down in known, (
            f"{path.name}: down_revision {down!r} does not exist on disk."
        )


def test_no_forked_chain() -> None:
    """Exactly zero down_revisions should be shared between two heads.

    If a branch is intentional (merge migration coming), this test is
    the place to document it — add the exempt revision ids here.
    """
    counts: dict[str, list[str]] = {}
    for path, _, down in _collect():
        if down is None:
            continue
        counts.setdefault(down, []).append(path.name)

    branches = {down: paths for down, paths in counts.items() if len(paths) > 1}
    assert not branches, (
        "Migration chain has branches (two children of the same parent). "
        "Alembic will refuse to `upgrade head` without a merge revision. "
        f"Offenders: {branches}"
    )


def test_single_head() -> None:
    rows = _collect()
    known = {rev for _, rev, _ in rows}
    downs = {down for _, _, down in rows if down is not None}
    heads = known - downs
    assert len(heads) == 1, (
        f"Expected exactly one head revision, got {len(heads)}: {sorted(heads)}. "
        "Alembic needs a single head to upgrade."
    )
