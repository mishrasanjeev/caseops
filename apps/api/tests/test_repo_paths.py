"""The repo root must be locatable without assuming it exists.

``Path(__file__).resolve().parents[5]`` is correct in the checkout and raises
IndexError in the container, where a module at
``/app/src/caseops_api/services/x.py`` has exactly five parents. Two properties
make that worse than an ordinary wrong path:

* it raises at IMPORT time, so it lands above any try/except a caller wrote for
  the file being missing - the "unavailable" answer becomes unreachable exactly
  where it was needed
* it cannot fail in a test run, because in the repo the expression resolves

So these tests exercise container depth explicitly. A fixed parent count cannot
pass them.
"""

from __future__ import annotations

from pathlib import Path

from caseops_api.core.repo_paths import repo_root_or_none


class TestContainerDepth:
    def test_a_path_with_fewer_parents_than_the_old_count_returns_none(
        self, tmp_path: Path
    ) -> None:
        # /app/src/caseops_api/services/x.py has five parents. parents[5]
        # raises here; the marker search answers None.
        deployed = tmp_path / "app" / "src" / "caseops_api" / "services"
        deployed.mkdir(parents=True)
        module = deployed / "governance_integrity_scan.py"
        module.write_text("", encoding="utf-8")

        assert repo_root_or_none(module) is None

    def test_it_does_not_raise_where_the_old_expression_did(
        self, tmp_path: Path
    ) -> None:
        # The property that matters: no exception. An IndexError at import time
        # is what stopped the guard below it from ever running.
        shallow = tmp_path / "x.py"
        shallow.write_text("", encoding="utf-8")

        assert repo_root_or_none(shallow) is None


class TestRepositoryDepth:
    def test_a_checkout_is_found_by_marker(self, tmp_path: Path) -> None:
        root = tmp_path / "checkout"
        (root / "docs" / "ip-implementation").mkdir(parents=True)
        nested = root / "apps" / "api" / "src" / "caseops_api" / "services"
        nested.mkdir(parents=True)
        module = nested / "governance_integrity_scan.py"
        module.write_text("", encoding="utf-8")

        assert repo_root_or_none(module) == root

    def test_the_nearest_root_wins_not_a_fixed_depth(self, tmp_path: Path) -> None:
        # A worktree under a checkout: counting levels picks whichever happens
        # to be N up, which is how the same expression can be right in one
        # clone layout and wrong in another.
        outer = tmp_path / "caseops"
        (outer / ".git").mkdir(parents=True)
        inner = outer / ".worktrees" / "feature"
        (inner / "docs" / "ip-implementation").mkdir(parents=True)
        nested = inner / "apps" / "api" / "src" / "caseops_api"
        nested.mkdir(parents=True)
        module = nested / "thing.py"
        module.write_text("", encoding="utf-8")

        assert repo_root_or_none(module) == inner

    def test_this_repo_resolves_to_something_holding_the_map(self) -> None:
        root = repo_root_or_none(Path(__file__))

        assert root is not None
        assert (root / "docs" / "ip-implementation").is_dir()
