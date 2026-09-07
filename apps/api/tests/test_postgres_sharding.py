from __future__ import annotations

import json
from xml.etree import ElementTree

import pytest

from tests.postgres_sharding import _junit_identity, partition, verify_reports


def test_postgres_partition_is_complete_disjoint_and_order_independent():
    nodes = [f"tests/test_example.py::test_item[{index}]" for index in range(193)]
    selections = [partition(nodes, shard, 4) for shard in range(1, 5)]
    assert sorted(node for selected in selections for node in selected) == sorted(nodes)
    assert max(map(len, selections)) - min(map(len, selections)) == 1
    assert selections == [partition(list(reversed(nodes)), shard, 4) for shard in range(1, 5)]


@pytest.mark.parametrize("nodes,shard,total", [([], 1, 4), (["a", "a"], 1, 1),
    (["a"], 2, 4), (["a"], 0, 1), (["a"], 1, 33)])
def test_postgres_partition_rejects_incomplete_or_invalid_selections(nodes, shard, total):
    with pytest.raises(ValueError):
        partition(nodes, shard, total)


@pytest.mark.parametrize(
    "fault", [None, "missing", "drift", "skipped", "failure", "error", "wrong-node"]
)
def test_postgres_report_gate_requires_every_actual_success(tmp_path, fault):
    nodes = [f"tests/test_example.py::TestCases::test_item[{index}]" for index in range(8)]
    for shard in range(1, 5):
        selected = partition(nodes, shard, 4)
        inventory = {"shard": shard, "total": 4, "nodeids": nodes, "selected": selected}
        if fault == "drift" and shard == 1:
            inventory["nodeids"] = nodes[:-1]
        if fault != "missing" or shard != 1:
            (tmp_path / f"postgres-shard-{shard}.json").write_text(json.dumps(inventory))
        suite = ElementTree.Element("testsuite")
        for node in selected:
            classname, name = _junit_identity(node)
            case = ElementTree.SubElement(suite, "testcase", classname=classname, name=name)
            if shard == 1 and fault in ("skipped", "failure", "error"):
                ElementTree.SubElement(case, fault)
            if shard == 1 and fault == "wrong-node":
                case.set("name", "test_unselected")
        ElementTree.ElementTree(suite).write(tmp_path / f"postgres-shard-{shard}.xml")
    if fault is None:
        assert verify_reports(tmp_path, 4) == {
            "status": "passed", "shards": 4, "collected": 8, "skipped": 0
        }
    else:
        with pytest.raises(ValueError):
            verify_reports(tmp_path, 4)
