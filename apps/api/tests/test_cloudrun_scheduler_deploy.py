from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
DEPLOY_SCRIPT = REPO_ROOT / "infra" / "cloudrun" / "deploy.ps1"


def test_scheduler_deploy_grants_each_managed_job_invoker_access() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert '"run", "jobs", "add-iam-policy-binding", $JobName' in script
    assert '"--role", "roles/run.invoker"' in script
    assert '"--member", $member' in script

    managed_jobs = (
        "caseops-document-worker",
        "caseops-legal-update-sync",
        "caseops-case-tracking-poll",
        "caseops-activity-report",
    )
    for job_name in managed_jobs:
        assert f'"{job_name}"' in script

    grant_call = script.index(
        "Ensure-CloudRunJobInvoker `", script.index("if (-not $SkipScheduler)")
    )
    scheduler_call = script.index("Ensure-SchedulerJob `", grant_call)
    assert grant_call < scheduler_call


def test_scheduler_deploy_fails_when_iam_or_scheduler_update_fails() -> None:
    script = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    assert "Failed to grant '$member' permission" in script
    assert "Failed to $schedulerAction Cloud Scheduler job '$JobName'." in script
