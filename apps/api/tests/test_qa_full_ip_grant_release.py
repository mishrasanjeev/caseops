"""The guarded release control carries a schema-2 ``full_ip`` approval end to end.

The original ``ip_workspace`` behaviour stays covered by
``test_qa_manual_ip_grant_release.py`` unchanged. These tests drive the same
offline cloud harness with a schema-2 input and prove the full set is named in
both the grant and the read-only inspection argv, the receipts are checked
against schema 2 and the exact key set, and malformed approvals never reach
the cloud.
"""

from __future__ import annotations

import copy
import json

import pytest

from tests import test_qa_manual_ip_grant_release as release_tests
from tests.test_qa_manual_ip_grant_release import (  # noqa: F401 - fixture import
    _args_value,
    harness,
    run,
)

FULL_REQUEST = {**release_tests.REQUEST, "schema_version": 2, "entitlement_set": "full_ip"}


@pytest.fixture
def full(harness, monkeypatch):  # noqa: F811 - the shared offline cloud harness
    """The shared harness, approved for the full_ip set."""

    monkeypatch.setattr(release_tests, "REQUEST", copy.deepcopy(FULL_REQUEST))
    harness.source.write_text(json.dumps(FULL_REQUEST), encoding="utf-8")
    keys = list(harness.module.FULL_IP_ENTITLEMENT_KEYS)

    def schema_two(data: dict) -> None:
        if data["mode"] == "inspect":
            data.update(schema_version=2, entitlement_set="full_ip")
        else:
            data["entitlement_keys"] = keys

    harness.state["mutate_receipt"] = schema_two
    return harness


def test_full_ip_release_names_the_set_in_grant_and_inspection(full) -> None:
    evidence = run(full)
    assert evidence["status"] == "verified"
    assert evidence["request"]["entitlement_set"] == "full_ip"
    assert evidence["receipt"]["entitlement_keys"] == list(full.module.FULL_IP_ENTITLEMENT_KEYS)
    assert evidence["inspection"]["entitlement_set"] == "full_ip"
    assert [args[2] for _, args in full.state["runs"]] == ["grant", "inspect"]
    for _, args in full.state["runs"]:
        assert args[-2:] == ["--entitlement-set", "full_ip"], args
    deploy = next(argv for argv in full.state["calls"] if argv[:3] == ["run", "jobs", "deploy"])
    assert _args_value(deploy).endswith(",--entitlement-set,full_ip")


def test_schema_one_argv_is_unchanged(harness) -> None:  # noqa: F811
    assert "--entitlement-set" not in harness.module._args(release_tests.REQUEST)
    assert "--entitlement-set" not in harness.module._inspect_args(release_tests.REQUEST)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: receipt.update(entitlement_keys=["ip_workspace"]),
        lambda receipt: receipt.pop("entitlement_keys"),
        lambda receipt: receipt.update(schema_version=1),
        lambda receipt: receipt.update(entitlement_set="ip_workspace"),
    ],
)
def test_full_ip_grant_receipt_must_match_schema_two_and_the_exact_keys(full, mutate) -> None:
    original = full.state["mutate_receipt"]

    def drift(data: dict) -> None:
        original(data)
        if data["mode"] == "grant":
            mutate(data)

    full.state["mutate_receipt"] = drift
    with pytest.raises(full.module.ReleaseError, match="grant_receipt_mismatch"):
        run(full)
    assert [args[2] for _, args in full.state["runs"]] == ["grant"]


def test_full_ip_inspection_must_name_the_set(full) -> None:
    original = full.state["mutate_receipt"]

    def drift(data: dict) -> None:
        original(data)
        if data["mode"] == "inspect":
            data.pop("entitlement_set")

    full.state["mutate_receipt"] = drift
    with pytest.raises(full.module.ReleaseError, match="inspection_state_mismatch"):
        run(full)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update(entitlement_set="everything"),
        lambda value: value.pop("entitlement_set"),
        lambda value: value.update(schema_version=3),
        lambda value: value.update(entitlement_keys=["ip_workspace"]),
    ],
)
def test_invalid_full_ip_approval_never_reaches_cloud(full, mutation) -> None:
    value = copy.deepcopy(FULL_REQUEST)
    mutation(value)
    full.source.write_text(json.dumps(value))
    with pytest.raises(full.module.ReleaseError):
        run(full)
    assert full.state["calls"] == [] and not full.output.exists()


def test_schema_one_input_cannot_name_a_set(harness) -> None:  # noqa: F811
    value = {**release_tests.REQUEST, "entitlement_set": "full_ip"}
    harness.source.write_text(json.dumps(value))
    with pytest.raises(harness.module.ReleaseError, match="invalid_input_fields"):
        run(harness)
    assert harness.state["calls"] == []
