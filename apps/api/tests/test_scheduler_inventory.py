from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from scripts import scheduler_inventory

REPO_ROOT = Path(__file__).resolve().parents[3]
INVENTORY_PATH = REPO_ROOT / "infra" / "cloudrun" / "scheduler-inventory.json"


def test_checked_in_inventory_is_complete_and_valid() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)

    assert scheduler_inventory.validate_inventory(inventory) == []
    assert len(inventory["jobs"]) == 6
    assert {job["run_job_name"] for job in inventory["jobs"]} == {
        "caseops-legal-update-sync",
        "caseops-case-tracking-poll",
        "caseops-activity-report",
        "caseops-reminders-job",
        "caseops-extract-authority-metadata",
        "caseops-db-index-health",
    }
    assert inventory["legacy_schedulers_to_pause"] == [
        "caseops-case-tracking-poll-midnight"
    ]


def test_inventory_rejects_duplicate_owners_and_mutable_image_policy() -> None:
    inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    inventory["jobs"][1]["scheduler_name"] = inventory["jobs"][0]["scheduler_name"]
    inventory["jobs"][1]["image_policy"] = "mutable_tag"

    errors = scheduler_inventory.validate_inventory(inventory)

    assert any("duplicate scheduler_name" in error for error in errors)
    assert any("image_policy must be release_digest" in error for error in errors)


def test_reconcile_requires_an_immutable_release_image() -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)

    with pytest.raises(scheduler_inventory.InventoryError, match="immutable"):
        scheduler_inventory.reconcile(
            inventory,
            project=inventory["production_project"],
            region=inventory["location"],
            image="registry.example/caseops-api:latest",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows gcloud uses a .CMD shim")
def test_gcloud_runner_resolves_windows_command_shim(monkeypatch) -> None:
    calls: list[list[str]] = []

    class _Completed:
        returncode = 0
        stdout = "ok"
        stderr = ""

    monkeypatch.setattr(
        scheduler_inventory.shutil,
        "which",
        lambda _name: r"C:\Cloud SDK\bin\gcloud.CMD",
    )
    monkeypatch.setattr(
        scheduler_inventory.subprocess,
        "run",
        lambda arguments, **_kwargs: calls.append(arguments) or _Completed(),
    )

    assert scheduler_inventory.run_gcloud(["--version"]) == "ok"
    assert calls == [[r"C:\Cloud SDK\bin\gcloud.CMD", "--version"]]


def test_live_inspection_detects_identity_and_image_drift(monkeypatch) -> None:
    inventory = scheduler_inventory.load_inventory(INVENTORY_PATH)
    inventory["jobs"] = [inventory["jobs"][0]]
    expected_image = "registry.example/caseops-api@sha256:" + "a" * 64

    def fake_gcloud(arguments: list[str], *, expect_json: bool = False):
        assert expect_json
        if arguments[:3] == ["scheduler", "jobs", "describe"]:
            return {
                "state": "ENABLED",
                "schedule": "0 0 * * *",
                "timeZone": "Asia/Kolkata",
                "httpTarget": {
                    "uri": scheduler_inventory.scheduler_uri(
                        inventory["production_project"],
                        inventory["location"],
                        "caseops-legal-update-sync",
                    ),
                    "oauthToken": {"serviceAccountEmail": "wrong@example.test"},
                },
            }
        if arguments[:3] == ["run", "jobs", "describe"]:
            return {
                "spec": {
                    "template": {
                        "spec": {
                            "template": {
                                "spec": {"containers": [{"image": "registry/image:mutable"}]}
                            }
                        }
                    }
                }
            }
        return {"bindings": []}

    monkeypatch.setattr(scheduler_inventory, "run_gcloud", fake_gcloud)
    errors, summary = scheduler_inventory.inspect_live(
        inventory,
        project=inventory["production_project"],
        region=inventory["location"],
        expected_image=expected_image,
    )

    assert "caseops-legal-update-sync-midnight: identity drift" in errors
    assert "caseops-legal-update-sync-midnight: image drift" in errors
    assert "caseops-legal-update-sync-midnight: invoker_iam drift" in errors
    assert summary["result"] == "fail"
