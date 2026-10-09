from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

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


def test_prod_verification_cancels_superseded_runs() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")

    concurrency = workflow.split("concurrency:", 1)[1].split("permissions:", 1)[0]
    assert "group: prod-verify-${{ github.event_name }}" in concurrency
    assert "cancel-in-progress: true" in concurrency


def test_scheduled_prod_verification_is_read_only() -> None:
    import yaml

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(
        encoding="utf-8"
    )
    parsed = yaml.safe_load(workflow)
    jobs = parsed["jobs"]
    dispatch = jobs["prod-playwright-shards"]
    scheduled = jobs["scheduled-statute-verification"]

    assert dispatch["if"] == "github.event_name == 'workflow_dispatch'"
    assert scheduled["if"] == "github.event_name == 'schedule'"
    scheduled_names = {step.get("name") for step in scheduled["steps"]}
    assert "Verify every release-owned statute source record" in scheduled_names
    assert "Run IPLF-037B renewal acceptance" not in scheduled_names
    assert "Run IPLF-039F cost acceptance" not in scheduled_names
    assert "Run prod-Playwright suite (notice module)" not in scheduled_names
    assert "Run exact-release patent and domain journeys" not in scheduled_names

    # A new or edited scheduled step needs explicit read-only review. Named
    # deny-lists alone missed the 22 September mutating-QA/projection overlap.
    steps_digest = hashlib.sha256(
        json.dumps(scheduled["steps"], sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    # Reviewed 10 October: capture requires the before-disk safe native reporter.
    # The exact statute project, source-spec bytes and four read-only workers remain.
    assert steps_digest == "3475f5a0418cc20b4f95c721b62c642f44263a5bbe6bb366c2febdc5daee4dd4"
    config = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text(encoding="utf-8")
    assert (
        'name: "statute-source-prod-chromium",\n'
        '      testMatch: /ram-2026-09-07-statute-source-data\\.spec\\.ts$/,'
    ) in config
    statute_spec = (
        REPO_ROOT / "tests/e2e/ram-2026-09-07-statute-source-data.spec.ts"
    ).read_text(encoding="utf-8")
    spec_digest = hashlib.sha256(statute_spec.replace("\r\n", "\n").encode()).hexdigest()
    assert spec_digest == "60f2583d845e5ee8092777f3db4a551acbfe30419d14b65faff509dc101bdb41"


def test_prod_verification_runs_notice_suite_after_ram_failure() -> None:
    """The required Notice signal must not disappear behind another failure."""

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    notice_step = workflow.split("- name: Run prod-Playwright suite (notice module)", 1)[1]
    next_step = notice_step.split("- name: Check release-owned patent and statute acceptance", 1)[0]

    assert "if: always()" in next_step
    assert "playwright.notice-prod.config.ts" in next_step
    assert "fail-fast: false" in workflow


def test_prod_verification_preserves_each_suite_failure_artifact() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")

    for output_directory in (
        "tester",
        "legacy",
        "test-legal-readonly",
        "ip-a0",
        "ip-renewal",
        "ip-cost",
        "notice",
        "patent",
        "statute-sources",
    ):
        assert f"--output=test-results/{output_directory}" in workflow
    upload_step = workflow.split("- name: Upload native Playwright evidence", 1)[1].split(
        "  scheduled-statute-verification:", 1
    )[0]
    assert "if: always()" in upload_step
    assert "test-results/prod-native-evidence/" in upload_step
    assert (
        "steps.prod-playwright-prerequisites.outputs.ready == 'true' && 'error' || 'warn'"
        in upload_step
    )
    assert "prod-playwright-report-${{ matrix.suite }}" in upload_step


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
    import yaml

    workflow = (REPO_ROOT / ".github" / "workflows" / "prod-verify.yml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(workflow)
    job = parsed["jobs"]["record-release-evidence"]
    writer = next(
        step
        for step in job["steps"]
        if step.get("name") == "Record exact-release public-claims evidence"
    )

    assert "needs.prod-playwright-shards.result == 'success'" in job["if"]
    assert job["needs"] == ["resolve-release", "prod-playwright-shards"]
    assert "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET" in writer["env"]
    assert "needs.resolve-release.outputs.release_sha" in writer["env"]["SERVING_RELEASE_SHA"]
    assert '--run-id "github-actions:${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT}"' in writer["run"]
    assert "--operational public_claims_reviewed=pass" in writer["run"]
    assert "--billing" not in writer["run"]
    assert "--pine" not in writer["run"]


def test_public_claims_attestation_requires_exact_release_nonmutating_browser_evidence() -> None:
    import yaml

    parsed = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    job = parsed["jobs"]["prod-playwright-shards"]
    assert "public-pages" in job["strategy"]["matrix"]["suite"]
    steps = {step.get("name"): step for step in job["steps"]}
    selected = steps["Run exact-release public SEO read-only acceptance"]
    assert "matrix.suite == 'public-pages'" in selected["if"]
    assert 'test "${{ steps.native-evidence.outputs.mode }}" = native' in selected["run"]
    assert "test -f playwright.public-seo.config.ts" in selected["run"]
    assert '--invocation' not in selected["run"]
    assert 'caseops-prod-playwright" public-pages --config=playwright.public-seo.config.ts' in (
        selected["run"]
    )
    assert "--workers=1 --retries=0 --reporter=list" in selected["run"]
    assert selected["env"]["CASEOPS_WEB_BASE_URL"] == "https://caseops.ai"
    reconcile = steps["Reconcile required native Playwright evidence"]["run"]
    assert "public-pages) required=(public-pages)" in reconcile
    config = (REPO_ROOT / "playwright.public-seo.config.ts").read_text()
    assert "public-content\\.spec\\.ts" in config
    assert "seo_demo_20261009\\.spec\\.ts" in config
    assert "public CTA and truthful copy|public read-only prototype source rejection" in config
    assert "globalSetup: undefined" in config and "webServer: undefined" in config
    for policy in ('trace: "off"', 'screenshot: "off"', 'video: "off"',
                   "extraHTTPHeaders: noPaidProviderHeaders"):
        assert policy in config
    assert "public-pages" not in steps.get("Run legacy QA production regressions", {}).get(
        "run", ""
    )


@pytest.mark.parametrize("mode", ["missing-native", "missing-config", "ready", "failed-wrapper"])
def test_public_claims_shell_cannot_run_unreleased_tests_or_hide_native_failure(tmp_path, mode):
    import yaml

    parsed = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    step = next(
        step for step in parsed["jobs"]["prod-playwright-shards"]["steps"]
        if step.get("name") == "Run exact-release public SEO read-only acceptance"
    )
    native_mode = "legacy" if mode == "missing-native" else "native"
    script = step["run"].replace("${{ steps.native-evidence.outputs.mode }}", native_mode)
    if mode != "missing-config":
        (tmp_path / "playwright.public-seo.config.ts").write_text(
            "// Offline shell fixture only.\n"
        )
    (tmp_path / "caseops-prod-playwright").write_text(
        'printf "%s\\n" "$@" > wrapper-called\nexit "$OFFLINE_EXIT"\n'
    )
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file()
    result = subprocess.run(
        [bash, "-e", "-c", script], cwd=tmp_path, capture_output=True, encoding="utf-8",
        env={**os.environ, "RUNNER_TEMP": tmp_path.as_posix(),
             "OFFLINE_EXIT": "7" if mode == "failed-wrapper" else "0"},
    )
    called = tmp_path / "wrapper-called"
    assert (result.returncode == 0) is (mode == "ready")
    assert called.exists() is (mode in {"ready", "failed-wrapper"})
    if called.exists():
        assert called.read_text().splitlines() == [
            "public-pages", "--config=playwright.public-seo.config.ts", "--workers=1",
            "--retries=0", "--reporter=list", "--output=test-results/public-pages",
        ]


def test_exact_release_verification_is_serialized_into_bounded_jobs() -> None:
    import yaml

    workflow = yaml.safe_load(
        (REPO_ROOT / ".github/workflows/prod-verify.yml").read_text(encoding="utf-8")
    )
    shard_job = workflow["jobs"]["prod-playwright-shards"]
    assert shard_job["timeout-minutes"] < 40
    assert shard_job["strategy"]["fail-fast"] is False
    assert shard_job["strategy"]["max-parallel"] == 1
    assert shard_job["strategy"]["matrix"]["suite"] == [
        "tester",
        "test-legal-readonly",
        "legacy",
        "supporting",
        "patent-statute",
        "public-pages",
    ]

    by_name = {step.get("name"): step for step in shard_job["steps"]}
    boundary = by_name["Recheck exact serving identity at shard boundary"]
    assert "--expected-sha" in boundary["run"]
    assert "needs.resolve-release.outputs.release_sha" in boundary["run"]
    tester = by_name["Run canonical tester production regressions"]["run"]
    test_legal = by_name["Run test-legal read-only hearing acceptance"]
    legacy = by_name["Run legacy QA production regressions"]["run"]
    assert "--project=tester-prod-chromium" in tester
    assert "--project=prod-chromium" not in tester
    assert "matrix.suite == 'test-legal-readonly'" in test_legal["if"]
    assert "--project=test-legal-readonly-prod-chromium" in test_legal["run"]
    assert (
        "secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD"
        in test_legal["env"]["CASEOPS_RAM_PROD_PASSWORD"]
    )
    assert "--project=prod-chromium" in legacy
    assert "--project=tester-prod-chromium" not in legacy


def test_patent_and_statute_production_phases_are_release_owned_and_bounded() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    steps = workflow["jobs"]["prod-playwright-shards"]["steps"]
    by_name = {step.get("name"): step for step in steps}
    check = by_name["Check release-owned patent and statute acceptance"]
    assert "-f tests/e2e/support/patent-acceptance.ts" in check["run"]
    assert "test -f tests/e2e/ram-2026-09-07-statute-source-data.spec.ts" in check["run"]
    patent = by_name["Run exact-release patent and domain journeys"]
    statutes = by_name["Verify every release-owned statute source record"]
    for step in (patent, statutes):
        assert "always() && !cancelled()" in step["if"]
        assert "steps.patent-statute-prerequisites.outputs.ready == 'true'" in step["if"]
        assert "--retries=0" in step["run"]
        assert "CASEOPS_EXPECTED_RELEASE_SHA" in step["env"]
    assert "--project=patent-prod-chromium --workers=1" in patent["run"]
    assert "--project=statute-source-prod-chromium --workers=4" in statutes["run"]
    tester = by_name["Run canonical tester production regressions"]["run"]
    legacy = by_name["Run legacy QA production regressions"]["run"]
    assert "--project=tester-prod-chromium" in tester
    assert "--project=prod-chromium" in legacy
    assert steps.index(by_name["Run prod-Playwright suite (notice module)"]) < steps.index(check)
    assert steps.index(check) < steps.index(patent) < steps.index(statutes)


def test_notice_acceptance_is_in_the_exact_release_tester_inventory() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    steps = workflow["jobs"]["prod-playwright-shards"]["steps"]
    tester = next(
        step for step in steps
        if step.get("name") == "Run canonical tester production regressions"
    )
    assert tester["env"]["CASEOPS_NOTICE_QA_SLUG"] == "test-legal"
    assert tester["env"]["CASEOPS_NOTICE_OWNER_EMAIL"] == "ram@testfirm.com"
    assert (
        "secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD"
        in tester["env"]["CASEOPS_NOTICE_OWNER_PASSWORD"]
    )
    assert tester["env"]["CASEOPS_NOTICE_CREATE_TEST_LEGAL_MEMBER"] == "true"
    assert (
        "needs.resolve-release.outputs.release_sha"
        in tester["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
    )
    assert "--project=tester-prod-chromium --workers=1 --retries=0" in tester["run"]
    for name in ("playwright.app.config.ts", "playwright.prod-ram.config.ts"):
        config = (REPO_ROOT / name).read_text()
        assert r"/ram-2026-10-08-notices\.spec\.ts$/" in config
    spec = (REPO_ROOT / "tests/e2e/ram-2026-10-08-notices.spec.ts").read_text()
    assert "noPaidProviderHeaders" in spec
    assert "for (const width of [1280, 393])" in spec
    assert "test.skip" not in spec


def test_existing_patent_qa_helper_does_not_rewrite_live_configuration() -> None:
    helper = (REPO_ROOT / "tests/e2e/support/patent-acceptance.ts").read_text()
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in helper
    assert "`${apiBaseUrl}/api/build`" in helper
    assert '/api/release-identity`' in helper
    assert 'expect(session.company.slug).toBe(slug)' in helper
    assert 'other ? "caseops-qa" : "caseops-ip-qa"' in helper
    assert 'if (!existingQa) return bootstrapIntelligentReviewTenant(api)' in helper
    assert 'if (!existingQa) return enableIntelligentReviewIpWorkspace(api, tenant)' in helper
    assert 'api.get(`${apiBaseUrl}/api/ip/workspace/configuration`' in helper
    for forbidden in (
        "spawnSync", "DATABASE_URL", "api.put(",
        "/api/bootstrap/company", "/api/ip/workspace/enable",
    ):
        assert forbidden not in helper
    assert "noPaidProviderHeaders" in helper
    assert "patentScreenshot" in helper
    assert 'new URL(apiBaseUrl).hostname' in helper


def test_parallel_statute_source_audit_authenticates_once_per_worker() -> None:
    spec = (REPO_ROOT / "tests/e2e/ram-2026-09-07-statute-source-data.spec.ts").read_text()
    assert 'scope: "worker"' in spec
    assert "async ({ sourceApi: api })" in spec
    assert "test.beforeAll" not in spec
    assert "await use(api)" in spec
    assert "await api?.dispose()" in spec
    assert "await setup.dispose()" in spec
    assert "noPaidProviderHeaders" in spec
