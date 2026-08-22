"""UJ-67 exception paths: an additive migration through mixed revisions and rollback.

Covers two of the four exception paths, and only two:

  UJ-67-EXC-01  lock/table-scan estimate exceeds the deploy window
  UJ-67-EXC-06  a destructive downgrade instead of restore/roll-forward

Both are decidable from the migration source before anything touches a database.

  UJ-67-EXC-03  backfill mismatch
  UJ-67-EXC-04  canary or SLO fails

are runtime conditions of the deploy, not properties of the file, and are NOT
tested here. Naming a test after them and asserting something adjacent would
record coverage that does not exist - which is the failure this programme's own
DATA-GOV-18 language is written against.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "migration_preflight.py"
SPEC = importlib.util.spec_from_file_location("migration_preflight", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
migration_preflight = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration_preflight
SPEC.loader.exec_module(migration_preflight)


def _migration(tmp_path: Path, body: str, name: str = "20260818_0001_probe.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _codes(findings: list) -> set[str]:
    return {finding.code for finding in findings}


class TestLockAndScanWindow:
    """UJ-67-EXC-01."""

    def test_non_concurrent_index_is_flagged(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            'def upgrade():\n    op.create_index("ix_a", "big_table", ["col"])\n'
            "\n\ndef downgrade():\n    pass\n",
        )

        findings = migration_preflight.analyze(path)

        assert "UJ-67-EXC-01" in _codes(findings)
        # The message has to name the escape hatch, or the author has no route
        # forward except deleting the check.
        assert "postgresql_concurrently" in findings[0].detail

    def test_concurrent_index_is_accepted(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            "def upgrade():\n"
            '    op.create_index("ix_a", "big_table", ["col"], postgresql_concurrently=True)\n'
            "\n\ndef downgrade():\n    pass\n",
        )

        assert migration_preflight.analyze(path) == []

    def test_column_type_change_is_flagged_as_a_rewrite(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            "def upgrade():\n"
            '    op.alter_column("big_table", "col", type_=sa.String(200))\n'
            "\n\ndef downgrade():\n    pass\n",
        )

        assert "UJ-67-EXC-01" in _codes(migration_preflight.analyze(path))

    def test_an_acknowledged_lock_risk_passes(self, tmp_path: Path) -> None:
        # The gate cannot know table sizes. An author who states the reason in
        # the file has satisfied it; a reviewer still sees the claim.
        path = _migration(
            tmp_path,
            "# MIGRATION-LOCK-RISK: acknowledged - ip_watch_rules has under 50 rows\n"
            'def upgrade():\n    op.create_index("ix_a", "ip_watch_rules", ["col"])\n'
            "\n\ndef downgrade():\n    pass\n",
        )

        assert migration_preflight.analyze(path) == []


class TestDestructiveDowngrade:
    """UJ-67-EXC-06."""

    def test_dropping_a_column_in_downgrade_is_flagged(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            "def upgrade():\n    pass\n"
            "\n\ndef downgrade():\n"
            '    op.drop_column("ip_dockets", "renewal_due_on")\n',
        )

        findings = migration_preflight.analyze(path)

        assert "UJ-67-EXC-06" in _codes(findings)
        assert "roll-forward" in findings[0].detail

    def test_dropping_a_table_in_downgrade_is_flagged(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            "def upgrade():\n    pass\n"
            '\n\ndef downgrade():\n    op.drop_table("ip_cost_items")\n',
        )

        assert "UJ-67-EXC-06" in _codes(migration_preflight.analyze(path))

    def test_the_same_operation_in_upgrade_is_not_a_rollback_finding(
        self, tmp_path: Path
    ) -> None:
        # Dropping a column on the way FORWARD is an ordinary schema change with
        # its own review. EXC-06 is about the rollback path specifically, so the
        # check must be scoped to downgrade() or it becomes noise.
        path = _migration(
            tmp_path,
            'def upgrade():\n    op.drop_column("ip_dockets", "legacy_col")\n'
            "\n\ndef downgrade():\n    pass\n",
        )

        assert "UJ-67-EXC-06" not in _codes(migration_preflight.analyze(path))

    def test_an_acknowledged_rollback_passes(self, tmp_path: Path) -> None:
        path = _migration(
            tmp_path,
            "# MIGRATION-ROLLBACK: restore-forward - revision never shipped beyond CI\n"
            "def upgrade():\n    pass\n"
            '\n\ndef downgrade():\n    op.drop_column("ip_dockets", "col")\n',
        )

        assert migration_preflight.analyze(path) == []


def _revision(
    tmp_path: Path,
    revision: str,
    down_revision: str | None,
    name: str | None = None,
) -> Path:
    literal = "None" if down_revision is None else f'"{down_revision}"'
    return _migration(
        tmp_path,
        f'revision = "{revision}"\ndown_revision = {literal}\n\n'
        "def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n",
        name=name or f"{revision}_probe.py",
    )


class TestRevisionGraphShape:
    """Not a UJ-67 exception path — a defect in the graph itself.

    This check exists because of a real collision: two lanes each added a
    migration whose ``down_revision`` was ``20260820_0002``. Neither branch
    could show the problem, because each held only its own file.
    """

    def test_a_linear_chain_has_one_head(self, tmp_path: Path) -> None:
        paths = [
            _revision(tmp_path, "0001", None),
            _revision(tmp_path, "0002", "0001"),
            _revision(tmp_path, "0003", "0002"),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == ["0003"]
        assert findings == []

    def test_two_migrations_from_one_parent_are_flagged(self, tmp_path: Path) -> None:
        # The exact shape of the 2026-08-20 collision.
        paths = [
            _revision(tmp_path, "20260820_0002", None),
            _revision(tmp_path, "20260821_0001", "20260820_0002"),
            _revision(tmp_path, "20260821_0002", "20260820_0002"),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == ["20260821_0001", "20260821_0002"]
        assert _codes(findings) == {migration_preflight.MULTIPLE_HEADS_CODE}
        detail = findings[0].detail
        # Both heads must be named, or the author cannot tell which two collided.
        assert "20260821_0001" in detail and "20260821_0002" in detail
        # And the message has to name the way out.
        assert "merge revision" in detail

    def test_an_explicit_merge_revision_resolves_the_split(self, tmp_path: Path) -> None:
        paths = [
            _revision(tmp_path, "20260820_0002", None),
            _revision(tmp_path, "20260821_0001", "20260820_0002"),
            _revision(tmp_path, "20260821_0002", "20260820_0002"),
            _migration(
                tmp_path,
                'revision = "20260822_0001"\n'
                'down_revision = ("20260821_0001", "20260821_0002")\n\n'
                "def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n",
                name="20260822_0001_merge.py",
            ),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == ["20260822_0001"]
        assert findings == []

    def test_a_duplicate_revision_id_is_flagged(self, tmp_path: Path) -> None:
        paths = [
            _revision(tmp_path, "0001", None),
            _revision(tmp_path, "0002", "0001", name="0002_a.py"),
            _revision(tmp_path, "0002", "0001", name="0002_b.py"),
        ]

        _revisions, _heads, findings = migration_preflight.revision_graph(paths)

        assert migration_preflight.DUPLICATE_REVISION_CODE in _codes(findings)

    def test_a_graph_that_is_only_a_cycle_is_flagged(self, tmp_path: Path) -> None:
        # Two migrations naming each other. Every revision is someone's parent,
        # so the head set is EMPTY - which a "more than one head" check reads as
        # fine. Nothing here can ever be upgraded.
        paths = [
            _revision(tmp_path, "0001", "0002", name="0001_a.py"),
            _revision(tmp_path, "0002", "0001", name="0002_b.py"),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == [], "the premise of this test is that the head set is empty"
        assert migration_preflight.REVISION_CYCLE_CODE in _codes(findings)

    def test_a_cycle_beside_a_healthy_chain_is_flagged(self, tmp_path: Path) -> None:
        # The harder shape, and the reason this check is not folded into the
        # head count: a sound chain plus a disconnected cycle yields EXACTLY
        # ONE head, so neither "more than one head" nor "exactly one head"
        # notices the cycle. Only walking down_revision to a base does.
        paths = [
            _revision(tmp_path, "aaa1", None, name="aaa1.py"),
            _revision(tmp_path, "aaa2", "aaa1", name="aaa2.py"),
            _revision(tmp_path, "bbb1", "bbb2", name="bbb1.py"),
            _revision(tmp_path, "bbb2", "bbb1", name="bbb2.py"),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == ["aaa2"], "the premise is that the head count looks healthy"
        assert migration_preflight.REVISION_CYCLE_CODE in _codes(findings)
        detail = next(
            f for f in findings if f.code == migration_preflight.REVISION_CYCLE_CODE
        ).detail
        # Only the cycle members, never the sound chain beside them.
        assert "bbb1" in detail and "bbb2" in detail
        assert "aaa1" not in detail and "aaa2" not in detail

    def test_a_merge_revision_behind_a_cycle_is_not_grounded(self, tmp_path: Path) -> None:
        # A merge revision is grounded only if EVERY parent is. One poisoned
        # branch is enough to make the merge unreachable, so `all` and not `any`.
        paths = [
            _revision(tmp_path, "ok1", None, name="ok1.py"),
            _revision(tmp_path, "bad1", "bad2", name="bad1.py"),
            _revision(tmp_path, "bad2", "bad1", name="bad2.py"),
            _migration(
                tmp_path,
                'revision = "merge1"\ndown_revision = ("ok1", "bad1")\n\n'
                "def upgrade():\n    pass\n\n\ndef downgrade():\n    pass\n",
                name="merge1.py",
            ),
        ]

        _revisions, _heads, findings = migration_preflight.revision_graph(paths)

        detail = next(
            f for f in findings if f.code == migration_preflight.REVISION_CYCLE_CODE
        ).detail
        assert "merge1" in detail, "a merge with one poisoned parent is not grounded"

    def test_a_healthy_chain_reports_no_cycle(self, tmp_path: Path) -> None:
        paths = [
            _revision(tmp_path, "c1", None, name="c1.py"),
            _revision(tmp_path, "c2", "c1", name="c2.py"),
            _revision(tmp_path, "c3", "c2", name="c3.py"),
        ]

        _revisions, heads, findings = migration_preflight.revision_graph(paths)

        assert heads == ["c3"]
        assert findings == []

    def test_the_committed_graph_has_exactly_one_head(self) -> None:
        versions = sorted(migration_preflight.VERSIONS_DIR.glob("*.py"))

        _revisions, heads, findings = migration_preflight.revision_graph(versions)

        assert len(heads) == 1, f"the committed migrations have {len(heads)} heads: {heads}"
        assert findings == []


class TestGateBehaviour:
    def test_unparseable_migration_fails_loudly(self, tmp_path: Path) -> None:
        # A migration that cannot be parsed must not be silently treated as safe.
        path = _migration(tmp_path, "def upgrade(:\n")

        with pytest.raises(SyntaxError):
            migration_preflight.analyze(path)

    def test_committed_migrations_are_all_parseable(self) -> None:
        versions = sorted(migration_preflight.VERSIONS_DIR.glob("*.py"))

        assert versions, "expected committed migrations to analyse"
        for path in versions:
            migration_preflight.analyze(path)

    def test_historical_debt_is_reported_not_enforced(self) -> None:
        # 148 migrations predate this gate. check-change scopes enforcement to
        # what a branch actually touches, so the backlog is visible without
        # blocking every unrelated change - the same shape as the data-governance
        # change gate. A gate that fails on arrival gets deleted.
        versions = sorted(migration_preflight.VERSIONS_DIR.glob("*.py"))
        findings = [f for path in versions for f in migration_preflight.analyze(path)]

        assert findings, (
            "expected pre-existing risks in committed migrations; if this is now "
            "empty the backlog was cleared and this test should be retired"
        )
        # Still 0: the risk backlog stays advisory. `validate` now also fails on
        # a broken revision graph, which is a different thing - not a judgement
        # to record but a deploy that cannot run - and the committed graph is
        # single-headed, so this stays green.
        assert migration_preflight.main(["validate"]) == 0
