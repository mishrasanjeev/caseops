"""Partition the complete marked collection and reconcile every executed node."""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

import pytest

# Source685 hosted run40634043720 measured complete phase costs. Retain this
# sixteen-parent inventory, including these four routes, when splitting32 jobs.
_MEASURED_SIXTEEN_SHARD_DESTINATIONS = {
    (
        "tests/test_ip_import_review_gaps_20261013.py::"
        "test_thousand_same_mark_distinct_applicants_commit_has_linear_materialization"
    ): 10,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_pack_items]"
    ): 3,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[hearing_packs]"
    ): 6,
    (
        "tests/test_matter_readthrough_page_worker_20261028_postgres.py::"
        "test_named_0008_waits_for_acknowledged_historical_source_writer_"
        "before_current_head[recommendation_decisions]"
    ): 16,
}


def partition(nodeids: list[str], shard: int, total: int) -> list[str]:
    if type(shard) is not int or type(total) is not int or not 1 <= shard <= total <= 32:
        raise ValueError("Require 1 <= shard <= total <= 32")
    if (
        type(nodeids) is not list
        or not nodeids
        or any(type(node) is not str or not node for node in nodeids)
        or len(set(nodeids)) != len(nodeids)
    ):
        raise ValueError("The complete PostgreSQL collection must be nonempty and unique")
    ordered = sorted(nodeids)
    if total == 32:
        parent = (shard - 1) % 16 + 1
        parent_nodes = partition(nodeids, parent, 16)
        child = int(shard > 16)
        # Balanced ABBA prefixes split each frozen parent without new case routes.
        selected = [
            node for index, node in enumerate(parent_nodes)
            if (index + 1) // 2 % 2 == child
        ]
    elif total == 16:
        selected = [
            node
            for index, node in enumerate(ordered)
            if _MEASURED_SIXTEEN_SHARD_DESTINATIONS.get(node, index % total + 1) == shard
        ]
    else:
        selected = ordered[shard - 1 :: total]
    if not selected:
        raise ValueError("A PostgreSQL shard may not be empty")
    return selected


def pytest_addoption(parser):
    group = parser.getgroup("postgres-sharding")
    group.addoption("--postgres-shard", type=int, required=True)
    group.addoption("--postgres-shards", type=int, required=True)
    group.addoption("--postgres-inventory", required=True)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    if any(item.get_closest_marker("postgres") is None for item in items):
        raise pytest.UsageError("PostgreSQL sharding requires the complete -m postgres selection")
    nodeids = sorted(item.nodeid for item in items)
    shard, total = config.getoption("--postgres-shard"), config.getoption("--postgres-shards")
    try:
        selected = partition(nodeids, shard, total)
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
    target = Path(config.getoption("--postgres-inventory"))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"shard": shard, "total": total, "nodeids": nodeids,
                                  "selected": selected}, indent=2), encoding="utf-8")
    selected_set = set(selected)
    config.hook.pytest_deselected(items=[item for item in items if item.nodeid not in selected_set])
    items[:] = [item for item in items if item.nodeid in selected_set]


def _junit_identity(nodeid: str) -> tuple[str, str]:
    module, *parts = nodeid.split("::")
    return ".".join([module.removesuffix(".py").replace("/", "."), *parts[:-1]]), parts[-1]


def _verify_native_exit(folder: Path, shard: int, source_sha: str) -> None:
    row = json.loads((folder / f"postgres-native-exit-{shard}.json").read_text(encoding="utf-8"))
    if type(row) is not dict or set(row) != {
        "schema_version", "stage", "source_sha", "launcher_pid", "child_pid", "planned_at",
        "started_at", "finished_at", "native_returncode", "native_signal", "exit_code",
        "publication_errors", "runtime",
    }:
        raise ValueError("PostgreSQL native exit receipt schema is not current")
    runtime = row.get("runtime", {})
    if (
        type(row.get("schema_version")) is not int or row["schema_version"] != 1
        or row.get("stage") != "exited" or row.get("source_sha") != source_sha
        or type(row.get("launcher_pid")) is not int or row["launcher_pid"] <= 0
        or type(row.get("child_pid")) is not int or row["child_pid"] <= 0
        or row["child_pid"] == row["launcher_pid"]
        or type(row.get("native_returncode")) is not int or row["native_returncode"] != 0
        or row.get("native_signal", "missing") is not None
        or type(row.get("exit_code")) is not int or row["exit_code"] != 0
        or row.get("publication_errors") != []
        or type(runtime) is not dict or set(runtime) != {
            "executable", "resolved", "sha256", "bytes", "device", "inode",
        }
        or type(runtime.get("bytes")) is not int or runtime["bytes"] <= 0
        or type(runtime.get("sha256")) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", runtime["sha256"])
        or any(type(runtime.get(key)) is not int or runtime[key] < 0
               for key in ("device", "inode"))
        or any(type(runtime.get(key)) is not str or not Path(runtime[key]).is_absolute()
               for key in ("executable", "resolved"))
    ):
        raise ValueError("PostgreSQL native exit receipt is incomplete or unsuccessful")
    try:
        values = [row[key] for key in ("planned_at", "started_at", "finished_at")]
        if any(type(value) is not str or not value.endswith("+00:00") for value in values):
            raise ValueError("Require explicit UTC observations")
        times = [datetime.fromisoformat(value) for value in values]
        if not times[0] <= times[1] <= times[2]:
            raise ValueError("Native observations are not ordered")
        journal = [json.loads(line) for line in
                   (folder / f"postgres-shard-{shard}.jsonl").read_text().splitlines()]
        if journal[0] != {"event": "session_started", "pid": row["child_pid"]}:
            raise ValueError("Native child does not own the recorded pytest session")
        if (type(journal[-1]) is not dict or type(journal[-1].get("exitstatus")) is not int
                or journal[-1] != {"event": "session_finished", "exitstatus": 0}):
            raise ValueError("The native pytest session did not complete")
    except (OSError, KeyError, IndexError, TypeError, ValueError) as error:
        raise ValueError("PostgreSQL native exit observations do not reconcile") from error


def verify_reports(
    folder: Path, total: int, *, require_native_exit: bool = False, source_sha: str | None = None,
) -> dict:
    if require_native_exit:
        source_sha = os.getenv("GITHUB_SHA") if source_sha is None else source_sha
        expected = {folder / f"postgres-native-exit-{shard}.json"
                    for shard in range(1, total + 1)}
        if (type(source_sha) is not str or not re.fullmatch(r"[0-9a-f]{40}", source_sha)
                or set(folder.glob("postgres-native-exit-*.json")) != expected):
            raise ValueError("Missing, unexpected or unbound PostgreSQL native exit receipts")
    inventories = sorted(folder.glob("postgres-shard-*.json"))
    reports = sorted(folder.glob("postgres-shard-*.xml"))
    if len(inventories) != total or len(reports) != total:
        raise ValueError("Missing or unexpected PostgreSQL shard artifacts")
    complete = None
    seen_shards: set[int] = set()
    executed: set[str] = set()
    for path in inventories:
        row = json.loads(path.read_text(encoding="utf-8"))
        shard = row["shard"]
        if row["total"] != total or shard in seen_shards:
            raise ValueError("Conflicting or duplicate PostgreSQL shard identity")
        seen_shards.add(shard)
        if complete is None:
            complete = row["nodeids"]
        if row["nodeids"] != complete or row["selected"] != partition(complete, shard, total):
            raise ValueError("PostgreSQL shard collection or partition drifted")
        report = folder / f"postgres-shard-{shard}.xml"
        cases = list(ElementTree.parse(report).iter("testcase"))
        expected = {_junit_identity(nodeid) for nodeid in row["selected"]}
        actual = {(case.get("classname"), case.get("name")) for case in cases}
        if len(cases) != len(expected) or actual != expected:
            raise ValueError("Executed PostgreSQL identities do not match the shard inventory")
        if any(
            case.find(tag) is not None
            for case in cases for tag in ("skipped", "failure", "error")
        ):
            raise ValueError("PostgreSQL acceptance contains a skipped, failed or errored node")
        executed.update(row["selected"])
        if require_native_exit:
            _verify_native_exit(folder, shard, source_sha)
    if seen_shards != set(range(1, total + 1)) or executed != set(complete or []):
        raise ValueError("PostgreSQL acceptance did not execute the entire collection")
    result = {"status": "passed", "shards": total, "collected": len(executed), "skipped": 0}
    if require_native_exit:
        result.update(native_exit_receipts=total, source_sha=source_sha)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--total", type=int, required=True)
    parser.add_argument("--require-native-exit", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify_reports(args.folder, args.total,
                                    require_native_exit=args.require_native_exit)))
