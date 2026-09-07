"""Partition the complete marked collection and reconcile every executed node."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.etree import ElementTree

import pytest


def partition(nodeids: list[str], shard: int, total: int) -> list[str]:
    if not 1 <= shard <= total <= 32:
        raise ValueError("Require 1 <= shard <= total <= 32")
    if not nodeids or len(set(nodeids)) != len(nodeids):
        raise ValueError("The complete PostgreSQL collection must be nonempty and unique")
    selected = sorted(nodeids)[shard - 1::total]
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


def verify_reports(folder: Path, total: int) -> dict:
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
    if seen_shards != set(range(1, total + 1)) or executed != set(complete or []):
        raise ValueError("PostgreSQL acceptance did not execute the entire collection")
    return {"status": "passed", "shards": total, "collected": len(executed), "skipped": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--total", type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(verify_reports(args.folder, args.total)))
