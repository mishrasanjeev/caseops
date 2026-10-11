from __future__ import annotations

import copy
import importlib
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
PROJECT = "perfect-period-305406"
REGION = "asia-south1"
PRIOR = "caseops-api-00488-5sd"
CURRENT = "caseops-api-00489-test"
OLD_SHA = "a" * 40
SHA = "b" * 40
OLD_IMAGE = "registry.invalid/caseops-api@sha256:" + "a" * 64
IMAGE = "registry.invalid/caseops-api@sha256:" + "b" * 64


@pytest.fixture(params=["document", "court"])
def harness(monkeypatch, request):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("document_worker_release")
    executor = module.EXECUTORS[request.param]
    state = {
        "current": PRIOR,
        "exists": False,
        "admission": "true",
        "protocol": "1",
        "image": OLD_IMAGE,
        "legacy": True,
        "deleted": False,
        "fail_enable": None,
        "tag": None,
        "traffic": 100,
        "older_age": 60,
        "older_active": "False",
        "older_legacy": True,
        "contract": "valid",
        "calls": [],
    }

    def revision(name):
        new = name == CURRENT
        mode = "cloud_run_job" if new or not state["legacy"] else "local_background"
        if name == "caseops-api-00487-old":
            mode = "local_background" if state["older_legacy"] else "cloud_run_job"
        return {
            "metadata": {"name": name, "labels": {"serving.knative.dev/service": "caseops-api"}},
            "spec": {
                "containers": [
                    {
                        "image": IMAGE if new else OLD_IMAGE,
                        "env": [
                            {"name": "CASEOPS_RELEASE_SHA", "value": SHA if new else OLD_SHA},
                            {"name": executor.mode_key, "value": mode},
                            {"name": executor.target_key, "value": executor.job},
                            {"name": executor.region_key, "value": REGION},
                            {"name": "CASEOPS_GCP_PROJECT_ID", "value": PROJECT},
                        ],
                    }
                ]
            },
        }

    def call(arguments, **kwargs):
        state["calls"].append(arguments)
        if arguments[:3] == ["run", "services", "describe"]:
            current = state["current"]
            return {
                "metadata": {"annotations": state.get("service_annotations", {})},
                "spec": {"traffic": state.get("desired_traffic", [
                    {"latestRevision": True, "percent": 100, "tag": state["tag"]},
                ])},
                "status": {
                    "latestReadyRevisionName": current,
                    "latestCreatedRevisionName": current,
                    "traffic": [
                        {
                            "revisionName": current,
                            "percent": state["traffic"],
                            "latestRevision": True,
                        }
                    ],
                    "conditions": [
                        {"type": key, "status": "True"}
                        for key in ["Ready", "RoutesReady", "ConfigurationsReady"]
                    ],
                },
            }
        if arguments[:3] == ["run", "revisions", "describe"]:
            return revision(arguments[3])
        if arguments[:3] == ["run", "revisions", "list"]:
            if "--filter" in arguments:
                return [] if state["deleted"] else [{"metadata": {"name": PRIOR}}]
            names = [state["current"], "caseops-api-00487-old"]
            if state["current"] != PRIOR and not state["deleted"]:
                names.append(PRIOR)
            retired = state.setdefault(
                "retired_at",
                (datetime.now(UTC) - timedelta(minutes=state["older_age"])).isoformat(),
            )
            return [
                {
                    "metadata": {
                        "name": name,
                        "annotations": state.get("older_annotations", {}),
                    },
                    "spec": {"timeoutSeconds": state.get("older_timeout", 120)},
                    "status": {
                        "conditions": [
                            {
                                "type": "Active",
                                "status": "True"
                                if name == state["current"]
                                else state["older_active"],
                                "reason": "Retired",
                                "lastTransitionTime": retired,
                            }
                        ]
                    },
                }
                for name in names
            ]
        if arguments[:3] == ["run", "revisions", "delete"]:
            assert arguments[3] == PRIOR and PRIOR != state["current"]
            assert state["admission"] == "false"
            state["deleted"] = True
            return ""
        if arguments[:3] == ["run", "jobs", "update"]:
            value = arguments[arguments.index("--update-env-vars") + 1].split("=", 1)[1]
            state["admission"] = value
            if value == "true" and state["fail_enable"] == "transport":
                raise module.inventory.InventoryError("ambiguous update")
            return ""
        if arguments[:3] == ["run", "jobs", "describe"]:
            if state["admission"] == "true" and state["fail_enable"] == "readback":
                raise module.inventory.InventoryError("readback unavailable")
            container = {
                "image": state["image"],
                "command": [executor.command],
                "args": list(executor.args),
                "env": [
                    {"name": executor.protocol, "value": state["protocol"]},
                    {"name": executor.admission, "value": state["admission"]},
                ],
            }
            if state["contract"] == "bad_command":
                container["command"] = ["caseops-migrate"]
            return {
                "spec": {"template": {"spec": {"template": {"spec": {"containers": [container]}}}}}
            }
        raise AssertionError(arguments)

    monkeypatch.setattr(module, "_call", call)

    def prove(revisions, **kwargs):
        if not revisions:
            return {}
        if state.get("stop_error") or state["older_age"] < 3:
            raise module.inventory.InventoryError("positive stopped-instance evidence unavailable")
        state["stop_proof"] = list(revisions)
        return {name: {"active": 0, "idle": 0, "retired_at": at} for name, at in revisions.items()}

    monkeypatch.setattr(module, "prove_stopped", prove)
    monkeypatch.setattr(module.inventory, "run_job_exists", lambda *args, **kwargs: state["exists"])
    monkeypatch.setattr(
        module.inventory,
        "scheduler_exists",
        lambda *args, **kwargs: state.get("scheduler_exists", state["exists"]),
    )
    return SimpleNamespace(
        inventory=module.inventory,
        stop_proof=module._stop_proof,
        preflight=module.preflight,
        prepare=partial(module.prepare, executor=executor),
        activate=partial(module.activate, executor=executor),
    ), state


def prepare(module):
    return module.prepare(project=PROJECT, region=REGION, release_sha=SHA)


def activate(module, state, capture):
    state.update(current=CURRENT, image=IMAGE, admission="false", exists=True)
    return module.activate(capture, project=PROJECT, region=REGION, release_sha=SHA, image=IMAGE)


def test_read_only_preflight_never_changes_admission_or_revisions(harness):
    module, state = harness
    state.update(exists=True, legacy=False)
    receipt = module.preflight(project=PROJECT, region=REGION, release_sha=SHA)
    assert receipt["prior_revision"] == PRIOR and state["admission"] == "true"
    assert not any("update" in call or "delete" in call for call in state["calls"])


@pytest.mark.parametrize("change", [
    {"desired_traffic": []},
    {"desired_traffic": [{"latestRevision": True, "percent": 100},
                         {"revisionName": "caseops-api-00487-old", "percent": 0}]},
    {"desired_traffic": [{"revisionName": PRIOR, "percent": 100}]},
    {"desired_traffic": [{"latestRevision": True, "revisionName": PRIOR, "percent": 100}]},
    {"desired_traffic": [{"latestRevision": True, "percent": 99}]},
    {"desired_traffic": "invalid"},
    {"service_annotations": {"run.googleapis.com/scalingMode": "manual"}},
    {"service_annotations": []},
])
def test_desired_routing_or_service_scaling_drift_rejects_before_mutation(harness, change):
    module, state = harness
    state.update(change)
    with pytest.raises(module.inventory.InventoryError):
        prepare(module)
    assert not any("update" in call or "delete" in call for call in state["calls"])


def test_explicit_service_automatic_scaling_is_valid(harness):
    module, state = harness
    state["service_annotations"] = {"run.googleapis.com/scalingMode": "automatic"}
    assert prepare(module)["prior_revision"] == PRIOR


def test_first_release_preserves_rollback_and_proves_stopped_instances_before_admission(harness):
    module, state = harness
    capture = prepare(module)
    assert capture["rollback_image"] == OLD_IMAGE and capture["legacy_api_executor"] is True
    receipt = activate(module, state, capture)
    writes = [call for call in state["calls"] if "delete" in call or "update" in call]
    assert len(writes) == 1 and writes[0][2] == "update"
    assert PRIOR in state["stop_proof"] and not state["deleted"]
    assert receipt["prior_revision_preserved"] == PRIOR and state["admission"] == "true"


def test_existing_independent_worker_disabled_without_destroying_api_revision(harness):
    module, state = harness
    state.update(exists=True, legacy=False)
    capture = prepare(module)
    assert state["admission"] == "false"
    activate(module, state, capture)
    assert not any("delete" in call for call in state["calls"])


@pytest.mark.parametrize(
    "change", [{"protocol": "0"}, {"contract": "bad_command"}, {"scheduler_exists": False}]
)
def test_unknown_protocol_or_partial_install_fails_before_mutation(harness, change):
    module, state = harness
    state.update(exists=True, **change)
    with pytest.raises(module.inventory.InventoryError):
        prepare(module)
    assert not any("update" in call or "delete" in call for call in state["calls"])


@pytest.mark.parametrize(
    "change", [{"tag": "rollback"}, {"traffic": 99}, {"older_active": "True"}, {"older_age": 1}]
)
def test_unverified_legacy_executor_never_passes_prepare(harness, change):
    module, state = harness
    state.update(change)
    with pytest.raises(module.inventory.InventoryError):
        prepare(module)
    assert not any("update" in call for call in state["calls"])


def test_independent_older_revision_still_requires_positive_instance_stop_proof(harness):
    module, state = harness
    state.update(older_age=1, older_legacy=False)
    with pytest.raises(module.inventory.InventoryError, match="stopped-instance"):
        prepare(module)
    assert not any("update" in call for call in state["calls"])


def test_retired_metadata_with_a_surviving_legacy_process_cannot_enable(harness):
    module, state = harness
    capture = prepare(module)
    state["stop_error"] = True
    with pytest.raises(module.inventory.InventoryError, match="stopped-instance"):
        activate(module, state, capture)
    assert state["admission"] == "false"
    assert not any("update" in call or "delete" in call for call in state["calls"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("release_sha", "c" * 40),
        ("executor", "another-queue"),
        ("project", "other-project"),
        ("admission_disabled", False),
        ("rollback_image", "tagged:image"),
    ],
)
def test_stale_capture_cannot_retire_or_enable(harness, field, value):
    module, state = harness
    capture = copy.deepcopy(prepare(module))
    capture[field] = value
    with pytest.raises(module.inventory.InventoryError):
        activate(module, state, capture)
    assert not any("delete" in call or "update" in call for call in state["calls"])


@pytest.mark.parametrize("failure", ["readback", "transport"])
def test_ambiguous_enable_or_readback_disables_again(harness, failure):
    module, state = harness
    capture = prepare(module)
    state["fail_enable"] = failure
    with pytest.raises(module.inventory.InventoryError):
        activate(module, state, capture)
    assert state["admission"] == "false"


def test_cannot_delete_current_revision(harness):
    module, state = harness
    capture = prepare(module)
    capture["prior_revision"] = CURRENT
    capture["prior_release_sha"] = SHA
    capture["rollback_image"] = IMAGE
    with pytest.raises(module.inventory.InventoryError, match="serving"):
        activate(module, state, capture)
    assert not any("delete" in call or "update" in call for call in state["calls"])


def test_expired_history_uses_operational_autoscale_inference_not_stop_deadline(harness):
    module, state = harness
    state["older_age"] = 60 * 24 * 60
    state["older_annotations"] = {"autoscaling.knative.dev/minScale": "1"}
    state["stop_error"] = True
    # No native series is required for the expired history. The prior serving
    # revision is not historical; activation below must still measure it.
    receipt = prepare(module)
    historical = receipt["older_instance_stop_proof"]["caseops-api-00487-old"]
    assert historical["minimum_allocation"] == 0
    assert historical["basis"] == "historical_autoscale_inference"
    assert historical["verdict"] == "operational_retirement_inference_not_physical_stop_proof"
    assert historical["limits"] == [
        "not_native_instance_measurement_or_physical_termination_proof",
        "does_not_release_prior_locks_or_cancel_already_issued_provider_work",
    ]
    assert "drain_bound_seconds" not in historical
    assert "active" not in historical and "zero_samples" not in historical
    with pytest.raises(module.inventory.InventoryError, match="stopped-instance"):
        activate(module, state, receipt)
    assert state["admission"] == "false"


@pytest.mark.parametrize(
    "change", [
        {"older_timeout": None}, {"older_timeout": True}, {"older_timeout": 0},
        {"older_timeout": 3601}, {"older_annotations": []},
        {"older_annotations": {"run.googleapis.com/cpu-throttling": "false"}},
        {"older_annotations": {"run.googleapis.com/scalingMode": "manual"}},
    ],
)
def test_expired_history_requires_actual_request_based_runtime_bounds(harness, change):
    module, state = harness
    state.update(older_age=60 * 24 * 60, **change)
    with pytest.raises(module.inventory.InventoryError, match="runtime bounds"):
        prepare(module)
    assert not any("update" in call or "delete" in call for call in state["calls"])
