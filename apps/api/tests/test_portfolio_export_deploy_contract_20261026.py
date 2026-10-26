from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_queue_provision_and_verified_runtime_bracket_canonical_api_rollout():
    source = (ROOT / "scripts/deploy-prod.sh").read_text()
    provision = source.index("python scripts/portfolio_export_release.py provision")
    rollout = source.index("gcloud run deploy caseops-api")
    verify = source.index("python scripts/portfolio_export_release.py verify")
    qa = source.index('echo "--- production QA bootstrap exact-generation execution ---"')
    assert provision < rollout < verify < qa
    assert "--cpu-throttling" in source[rollout:verify]
    assert (
        "CASEOPS_PORTFOLIO_EXPORT_WORKER_SECRET=${PORTFOLIO_EXPORT_WORKER_SECRET}:latest" in source
    )
    assert "PORTFOLIO_EXPORT_WORKER_SECRET=caseops-portfolio-export-worker-secret" in source
    assert "CASEOPS_PORTFOLIO_EXPORT_DISPATCH_MODE=cloud_tasks" in source
    assert "CASEOPS_PORTFOLIO_EXPORT_TASK_QUEUE=caseops-portfolio-exports" in source
    assert "${PORTFOLIO_EXPORT_ENV}" in source[rollout:verify]
    guard = source[
        source.index("DIRTY_BUILD_CONTEXT=") : source.index('if [[ -n "${DIRTY_BUILD_CONTEXT}"')
    ]
    assert '"scripts/portfolio_export_release.py"' in guard
    assert '"infra/cloudrun/scheduler-inventory.json"' in guard


def test_recovery_is_release_pinned_finite_and_has_no_model_provider_credentials():
    inventory = json.loads((ROOT / "infra/cloudrun/scheduler-inventory.json").read_text())
    rows = [
        row
        for row in inventory["jobs"]
        if row["run_job_name"] == "caseops-portfolio-export-recovery"
    ]
    assert len(rows) == 1
    job = rows[0]
    assert job["schedule"] == "*/5 * * * *" and job["time_zone"] == "Asia/Kolkata"
    assert job["image_policy"] == "release_digest" and job["task_timeout_seconds"] == 600
    runtime = job["bootstrap"]
    assert runtime["command"] == ["caseops-portfolio-export-worker"]
    assert runtime["args"] == ["--once", "--batch-size=5"]
    assert runtime["max_retries"] == 0
    assert set(runtime["secrets"]) == {"CASEOPS_DATABASE_URL", "CASEOPS_AUTH_SECRET"}
    assert runtime["environment"]["CASEOPS_LLM_PROVIDER"] == "mock"
    assert runtime["environment"]["CASEOPS_EMBEDDING_PROVIDER"] == "mock"


def test_reported_completion_budget_and_single_enqueue_proof_remain_intact():
    completion = (ROOT / "tests/e2e/support/ip-portfolio-export-completion.ts").read_text()
    browser = (ROOT / "tests/e2e/ram-2026-10-17-ip-tracker.spec.ts").read_text()
    assert "PORTFOLIO_EXPORT_COMPLETION_MS = 15_000" in completion
    assert "PORTFOLIO_EXPORT_MAX_READS = 16" in completion
    assert "expect(exportRequests).toBe(1)" in browser
    assert "expect(completed.row_count).toBe(51)" in browser
    assert "for (const width of [1280, 393])" in browser
