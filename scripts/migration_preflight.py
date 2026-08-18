#!/usr/bin/env python3
"""Static preflight for Alembic migrations (UJ-67).

UJ-67 deploys an additive migration through mixed revisions and rollback. Its
exception paths are the ways that goes wrong, and none of them had a check:

  UJ-67-EXC-01  lock/table-scan estimate exceeds the deploy window
  UJ-67-EXC-06  a destructive downgrade instead of restore/roll-forward

Both are decidable from the migration source before anything touches a database,
which is the only moment they are cheap to find. The other two exception paths
are runtime conditions - EXC-03 backfill mismatch and EXC-04 canary/SLO failure -
and belong to the deploy path. This module does not pretend to cover them.

Why a marker rather than a blanket refusal. Some of these operations are correct
and necessary: a unique index on a table that is still small, a column drop on a
revision that never reached an environment holding real rows. This gate cannot
know table sizes, so it asks the author to say so explicitly and leaves that
statement in the file where a reviewer will see it. An unacknowledged risky
operation fails; an acknowledged one passes. The goal is not to forbid the
operation, it is to make it impossible to perform one by accident.

Usage:
    python scripts/migration_preflight.py validate
    python scripts/migration_preflight.py check-change --base origin/main
"""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = REPO_ROOT / "apps" / "api" / "alembic" / "versions"

LOCK_RISK_MARKER = "MIGRATION-LOCK-RISK: acknowledged"
ROLLBACK_MARKER = "MIGRATION-ROLLBACK: restore-forward"

# Operations that hold a lock for the duration of a full table scan. CREATE
# INDEX without CONCURRENTLY blocks writes for the whole build.
_SCAN_OPS = {"create_index", "create_unique_constraint"}
# Operations that can rewrite every row while holding an exclusive lock.
_REWRITE_OPS = {"alter_column"}
# Operations in downgrade() that destroy committed data. UJ-67-EXC-06 exists
# because the answer to a bad migration is roll forward or restore, not a
# downgrade that deletes the rows the incident is about.
_DESTRUCTIVE_OPS = {"drop_column", "drop_table"}


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    code: str
    operation: str
    detail: str


def _display_path(path: Path) -> str:
    """Repo-relative where possible, absolute otherwise.

    ``Path.relative_to`` raises for anything outside the repository, which made
    the analyser crash on any path a caller passed from elsewhere - including a
    temporary file, which is how it is tested.
    """
    try:
        return path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _op_name(node: ast.Call) -> str | None:
    """Return the alembic operation name for an ``op.<name>(...)`` call."""
    func = node.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        if func.value.id == "op":
            return func.attr
    return None


def _is_concurrent(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg in {"postgresql_concurrently", "concurrently"}:
            return isinstance(keyword.value, ast.Constant) and keyword.value.value is True
    return False


def _function_spans(tree: ast.Module) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"upgrade", "downgrade"}:
            spans[node.name] = (node.lineno, node.end_lineno or node.lineno)
    return spans


def analyze(path: Path) -> list[Finding]:
    """Report unacknowledged lock and rollback risks in one migration."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    spans = _function_spans(tree)
    lock_acknowledged = LOCK_RISK_MARKER in source
    rollback_acknowledged = ROLLBACK_MARKER in source
    relative = _display_path(path)

    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _op_name(node)
        if name is None:
            continue
        downgrade_span = spans.get("downgrade")
        in_downgrade = bool(
            downgrade_span and downgrade_span[0] <= node.lineno <= downgrade_span[1]
        )

        if name in _SCAN_OPS and not _is_concurrent(node) and not lock_acknowledged:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "UJ-67-EXC-01",
                    name,
                    (
                        f"{name} builds under a write-blocking lock for a full table "
                        f"scan. Pass postgresql_concurrently=True, or record why the "
                        f"table is small enough with a '{LOCK_RISK_MARKER}: <reason>' "
                        f"comment."
                    ),
                )
            )
        if name in _REWRITE_OPS and not lock_acknowledged:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "UJ-67-EXC-01",
                    name,
                    (
                        f"{name} can rewrite every row while holding an exclusive lock. "
                        f"Record why the window is acceptable with a "
                        f"'{LOCK_RISK_MARKER}: <reason>' comment."
                    ),
                )
            )
        if in_downgrade and name in _DESTRUCTIVE_OPS and not rollback_acknowledged:
            findings.append(
                Finding(
                    relative,
                    node.lineno,
                    "UJ-67-EXC-06",
                    name,
                    (
                        f"downgrade() calls {name}, which destroys committed data. The "
                        f"rollback path for a shipped migration is roll-forward or "
                        f"restore. If this revision never reached an environment holding "
                        f"real rows, record that with a '{ROLLBACK_MARKER}: <reason>' "
                        f"comment."
                    ),
                )
            )
    return findings


def _changed_migrations(base: str) -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base}...HEAD"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git diff against {base} failed: {result.stderr.strip()}")
    paths: list[Path] = []
    for line in result.stdout.splitlines():
        candidate = REPO_ROOT / line.strip()
        if candidate.suffix == ".py" and candidate.parent == VERSIONS_DIR and candidate.exists():
            paths.append(candidate)
    return sorted(paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Alembic migration preflight (UJ-67)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate", help="report risk across every migration")
    changed = sub.add_parser("check-change", help="gate migrations changed against a base ref")
    changed.add_argument("--base", default="origin/main")
    args = parser.parse_args(argv)

    if args.command == "validate":
        paths = sorted(VERSIONS_DIR.glob("*.py"))
        findings = [finding for path in paths for finding in analyze(path)]
        by_code: dict[str, int] = {}
        for finding in findings:
            by_code[finding.code] = by_code.get(finding.code, 0) + 1
        print(
            f"migration preflight: {len(paths)} migrations, "
            f"{len(findings)} unacknowledged risks {by_code or ''}"
        )
        return 0

    targets = _changed_migrations(args.base)
    if not targets:
        print("migration preflight: no migration changed")
        return 0
    findings = [finding for path in targets for finding in analyze(path)]
    if not findings:
        print(f"migration preflight valid: {len(targets)} changed migration(s)")
        return 0
    for finding in findings:
        print(f"ERROR [{finding.code}] {finding.path}:{finding.line} {finding.detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
