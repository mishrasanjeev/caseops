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
        assert migration_preflight.main(["validate"]) == 0
