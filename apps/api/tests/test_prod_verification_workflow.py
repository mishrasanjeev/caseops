from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_every_playwright_config_blocks_paid_provider_requests() -> None:
    helper = (REPO_ROOT / "tests/e2e/support/cost-controls.ts").read_text(encoding="utf-8")
    assert '"X-CaseOps-Automated-Test": "no-paid-providers"' in helper

    inherited = {
        "playwright.app.self-hosted.config.ts",
        "playwright.docker.config.ts",
    }
    explicitly_nonbillable = {"playwright.provider-nonbillable-live.config.ts"}
    configs = sorted(REPO_ROOT.glob("playwright*.config.ts"))
    assert {path.name for path in configs} >= inherited | explicitly_nonbillable
    for config_path in configs:
        config = config_path.read_text(encoding="utf-8")
        if config_path.name in inherited:
            assert 'from "./playwright.app.config"' in config
            assert "...appConfig" in config
            continue
        assert 'from "./tests/e2e/support/cost-controls"' in config
        assert "extraHTTPHeaders: noPaidProviderHeaders" in config


def test_live_provider_config_is_nonbillable_bounded_and_explicitly_opted_in() -> None:
    config = (REPO_ROOT / "playwright.provider-nonbillable-live.config.ts").read_text(
        encoding="utf-8"
    )
    spec = (
        REPO_ROOT / "tests/e2e/provider-nonbillable-live-2026-09-04-prod.spec.ts"
    ).read_text(encoding="utf-8")

    assert 'CASEOPS_ALLOW_LIVE_PROVIDER_READONLY_TESTS !== "true"' in config
    assert "provider-nonbillable-live-2026-09-04-prod\\.spec\\.ts" in config
    assert "fullyParallel: false" in config
    assert "workers: 1" in config
    assert "noPaidProviderHeaders" in config
    assert "extraHTTPHeaders: noPaidProviderHeaders" in config
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert "`${API_BASE_URL}/api/build`" in spec
    assert "`${BASE_URL}/api/release-identity`" in spec
    assert "/api/admin/provider-operations/readiness" in spec
    assert "/api/authorities/providers/indian-kanoon/health" in spec
    assert "paid_provider_blocked_for_test" in spec
    assert "max_results" not in spec


def test_exact_release_case_tracking_uses_only_stored_evidence() -> None:
    spec = (REPO_ROOT / "tests/e2e/ram-2026-08-05-prod.spec.ts").read_text(encoding="utf-8")

    assert "/api/case-tracking/search" not in spec
    assert 'expect(canaryBody.evidence_mode).toBe("verified_cached")' in spec
    assert "expect(canaryBody.provider_call_performed).toBe(false)" in spec
    assert '"provider-markdown"' in spec
    assert '"live_provider"' not in spec


def test_prod_verification_is_deploy_triggered_not_push_triggered() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")

    trigger_block = workflow.split("on:", 1)[1].split("concurrency:", 1)[0]
    assert "push:" not in trigger_block
    assert "workflow_dispatch:" in trigger_block
    assert "required: true" in trigger_block
    assert "--wait-seconds 180" in workflow
    assert "--wait-seconds 1500" not in workflow


def test_prod_verification_runs_notice_suite_after_ram_failure() -> None:
    """The required Notice signal must not disappear behind another failure."""

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    notice_step = workflow.split("- name: Run prod-Playwright suite (notice module)", 1)[1]
    next_step = notice_step.split("- name: Upload Playwright report on failure", 1)[0]

    assert "if: always()" in next_step
    assert "playwright.notice-prod.config.ts" in next_step


def test_prod_verification_preserves_each_suite_failure_artifact() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")

    for output_directory in ("ram", "ip-a0", "ip-renewal", "ip-cost", "notice"):
        assert f"--output=test-results/{output_directory}" in workflow
    upload_step = workflow.split("- name: Upload Playwright report on failure", 1)[1]
    assert "test-results/" in upload_step
    assert "if-no-files-found: error" in upload_step


def test_historical_a0_acceptance_is_opt_in_not_a_recurring_release_gate() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    trigger_block = workflow.split("on:", 1)[1].split("concurrency:", 1)[0]
    a0_step = workflow.split("- name: Run IPLF-027B A0 quiescence acceptance", 1)[1].split(
        "- name: Check IPLF-037B renewal acceptance configuration", 1
    )[0]

    assert "run_historical_a0_gate:" in trigger_block
    assert "default: false" in trigger_block
    assert "type: boolean" in trigger_block
    assert "inputs.run_historical_a0_gate == true" in a0_step
    assert "CASEOPS_IP_A0_PROD_MODE: verify" in a0_step


def test_ip_cost_acceptance_is_isolated_and_partially_configured_runs_fail_closed() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    broad = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text(encoding="utf-8")
    release = (REPO_ROOT / ".github" / "workflows" / "release-verify.yml").read_text(
        encoding="utf-8"
    )
    dedicated = (REPO_ROOT / "playwright.ip-cost-prod.config.ts").read_text(encoding="utf-8")

    assert "iplf-039f-cost-items-2026-08-30-prod" not in broad
    assert "playwright.ip-cost-prod.config.ts" not in release
    assert "iplf-039f-cost-items-2026-08-30-prod\\.spec\\.ts" in dedicated
    assert "Check IPLF-039F cost acceptance configuration" in workflow
    assert "Run IPLF-039F cost acceptance" in workflow
    for fixture_name in (
        "CASEOPS_IP_COST_PROD_TEST_TENANT_ACK",
        "CASEOPS_IP_COST_PROD_BILLING_MATTER_IDS_JSON",
        "CASEOPS_IP_COST_PROD_COMPANY_SLUG",
        "CASEOPS_IP_COST_PROD_EMAIL",
        "CASEOPS_IP_COST_PROD_PASSWORD",
        "CASEOPS_IP_COST_PROD_DOCKET_ID",
    ):
        assert workflow.count(fixture_name) >= 3
    assert 'if [[ "$configured" -eq 0 ]]' in workflow
    assert 'elif [[ "$configured" -ne 6 ]]' in workflow
    assert "elif [[ ! -f playwright.ip-cost-prod.config.ts ]]" in workflow
    assert "newer workflow control plane will not run unreleased test code" in workflow
    assert "Deploy the current main release before certifying IPLF-039F" in workflow
    assert "generic scheduled production verification continues independently" in workflow
    assert "steps.ip-cost-prerequisites.outputs.configured == 'true'" in workflow
    assert "--config=playwright.ip-cost-prod.config.ts" in workflow


def test_exact_release_dispatch_records_only_the_claim_proven_by_the_suite() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    writer = workflow.split("- name: Record exact-release public-claims evidence", 1)[1].split(
        "- name: Upload Playwright report on failure", 1
    )[0]

    assert "if: success() && github.event_name == 'workflow_dispatch'" in writer
    assert "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET" in writer
    assert "steps.deployed-release.outputs.release_sha" in writer
    assert '--run-id "github-actions:${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT}"' in writer
    assert "--operational public_claims_reviewed=pass" in writer
    assert "--billing" not in writer
    assert "--pine" not in writer
