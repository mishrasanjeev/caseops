from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _assert_playwright_provider_marker(name: str, config: str, helper: str) -> None:
    inherited = {
        "playwright.app.self-hosted.config.ts",
        "playwright.docker.config.ts",
    }
    if name in inherited:
        assert 'from "./playwright.app.config"' in config
        assert "...appConfig" in config
        return
    assert 'from "./tests/e2e/support/cost-controls"' in config
    if name in {"playwright.app.config.ts", "playwright.config.ts"}:
        assert 'import { localTransportHeaders }' in config
        assert "extraHTTPHeaders: localTransportHeaders(webBaseUrl)" in config
        assert '"X-CaseOps-Automated-Test": "no-paid-providers"' in helper
        assert (
            'return { ...noPaidProviderHeaders, ...(local ? { Connection: "close" } : {}) };'
        ) in helper
    else:
        assert "extraHTTPHeaders: noPaidProviderHeaders" in config


def test_every_playwright_config_blocks_paid_provider_requests() -> None:
    helper = (REPO_ROOT / "tests/e2e/support/cost-controls.ts").read_text(encoding="utf-8")
    assert '"X-CaseOps-Automated-Test": "no-paid-providers"' in helper
    inherited = {"playwright.app.self-hosted.config.ts", "playwright.docker.config.ts"}
    explicitly_nonbillable = {"playwright.provider-nonbillable-live.config.ts"}
    configs = sorted(REPO_ROOT.glob("playwright*.config.ts"))
    assert {path.name for path in configs} >= inherited | explicitly_nonbillable
    for config_path in configs:
        config = config_path.read_text(encoding="utf-8")
        _assert_playwright_provider_marker(config_path.name, config, helper)

def test_oct13_production_mutations_own_test_legal_credentials_and_release_code() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    selected = [
        step
        for job in workflow["jobs"].values()
        if "test-legal-write-oct13" in job.get("strategy", {}).get("matrix", {}).get("suite", [])
        for step in job.get("steps", [])
        if step.get("name") == "Run release-owned test-legal portfolio and Calendar regressions"
    ]
    assert len(selected) == 1
    step = selected[0]
    assert step["if"] == "matrix.suite == 'test-legal-write-oct13'"
    assert step["env"]["CASEOPS_RAM_PROD_SLUG"] == "test-legal"
    assert "secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD" in step["env"]["CASEOPS_RAM_PROD_PASSWORD"]
    assert (
        "needs.resolve-release.outputs.release_sha" in step["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
    )
    assert (
        "git merge-base --is-ancestor HEAD 30e7229368de013123e9a48db2b19230829ddac2" in step["run"]
    )
    assert "test -f tests/e2e/ram-2026-10-13-ip-portfolio.spec.ts" in step["run"]
    assert "--project=test-legal-write-prod-chromium --workers=1 --retries=0" in step["run"]
    config = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text()
    project = config.split('name: "test-legal-write-prod-chromium"', 1)[1].split("name:", 1)[0]
    assert "testMatch: [OCT13_PORTFOLIO_CALENDAR_SPECS, NOTES22_PROD_SPEC]" in project
    assert "storageState: { cookies: [], origins: [] }" in project
    evidence_step = [step for step in workflow["jobs"]["prod-playwright-shards"]["steps"]
                     if step.get("name") == "Reconcile required native Playwright evidence"]
    assert len(evidence_step) == 1
    assert 'tester|tester-catalog|tester-index|test-legal-write-oct13) required=("$SUITE")' in (
        evidence_step[0]["run"]
    )



def test_notes22_production_case_uses_its_required_tenant_project() -> None:
    import yaml

    config = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text()
    tester = config.split('name: "tester-prod-chromium"', 1)[1].split("name:", 1)[0]
    writer = config.split('name: "test-legal-write-prod-chromium"', 1)[1].split("name:", 1)[0]
    assert "testIgnore: [RETAINED_INDEX_PROD_SPECS, NOTES22_PROD_SPEC]" in tester
    assert "testMatch: [OCT13_PORTFOLIO_CALENDAR_SPECS, NOTES22_PROD_SPEC]" in writer
    source = (REPO_ROOT / "tests/e2e/ram-2026-10-22-prod.spec.ts").read_text()
    assert 'if (!local && credentials.company_slug !== "test-legal")' in source
    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    step = next(
        item for item in workflow["jobs"]["prod-playwright-shards"]["steps"]
        if item.get("name") == "Run release-owned test-legal portfolio and Calendar regressions"
    )
    assert step["env"]["CASEOPS_RAM_PROD_SLUG"] == "test-legal"
    assert step["env"]["CASEOPS_RAM_PROD_EMAIL"] == "ram@testfirm.com"
    assert "secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD" in step["env"]["CASEOPS_RAM_PROD_PASSWORD"]
    assert step["if"] == "matrix.suite == 'test-legal-write-oct13'"
    assert "--project=test-legal-write-prod-chromium --workers=1 --retries=0" in step["run"]


def test_batch3_production_gate_owns_source_credentials_and_all_three_native_roles() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    steps = workflow["jobs"]["prod-playwright-shards"]["steps"]
    name = "Run release-owned Batch3 client and retained drafting acceptance"
    step = next(item for item in steps if item.get("name") == name)
    assert step["if"] == "matrix.suite == 'test-legal-write-oct13'"
    assert step["env"]["CASEOPS_RAM_PROD_SLUG"] == "test-legal"
    assert "secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD" in step["env"]["CASEOPS_RAM_PROD_PASSWORD"]
    assert (
        "needs.resolve-release.outputs.release_sha" in step["env"]["CASEOPS_EXPECTED_RELEASE_SHA"]
    )
    assert "if [ ! -f tests/e2e/ram-2026-10-22-drafting.prod.spec.ts ]" in step["run"]
    ancestor = "git merge-base --is-ancestor HEAD 38b700facbbadc7e730aca09329a436a9008e3ac"
    assert ancestor in step["run"]
    roles = {
        "batch3-clients-desktop": "batch3-clients-prod-chromium",
        "batch3-clients-mobile": "batch3-clients-prod-mobile",
        "batch3-drafts-readonly": "batch3-drafts-readonly-prod-chromium",
    }
    for role, project in roles.items():
        assert f'" {role} --config=playwright.prod-ram.config.ts --project={project}' in step["run"]
    assert step["run"].count("--workers=1 --retries=0 --reporter=list") == 3
    reconcile = next(item for item in steps
                     if item.get("name") == "Reconcile required native Playwright evidence")
    required = "required+=(batch3-clients-desktop batch3-clients-mobile batch3-drafts-readonly)"
    assert required in reconcile["run"]
    config = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text()
    for project in roles.values():
        block = config.split(f'name: "{project}"', 1)[1].split("name:", 1)[0]
        assert "retries: 0" in block and "dependencies: []" in block
        assert "storageState: { cookies: [], origins: [] }" in block
        assert 'trace: "off", screenshot: "off", video: "off"' in block
    tester = config.split('name: "tester-prod-chromium"', 1)[1].split("name:", 1)[0]
    assert "BATCH3_DRAFT_READONLY_SPEC" not in tester
    mobile = config.split('name: "batch3-clients-prod-mobile"', 1)[1].split("name:", 1)[0]
    assert "hasTouch: true" in mobile and "isMobile: true" in mobile
    assert "launchOptions" not in mobile


def test_historical_provider_uat_explicitly_selects_legacy_qa_project() -> None:
    import shlex

    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/release-verify.yml").read_text())
    step = next(item for item in workflow["jobs"]["release-playwright"]["steps"]
                if item.get("name") == "Run release-mode Playwright (CASEOPS_RELEASE_MODE=true)")
    calls = [shlex.split(line.strip()) for line in step["run"].splitlines()
             if line.strip().startswith("npx playwright test ")]
    production = [call for call in calls if "--config=playwright.prod-ram.config.ts" in call]
    assert len(production) == 1
    assert [arg for arg in production[0] if arg.startswith("--project=")] == [
        "--project=prod-chromium"
    ]
    assert any("--config=playwright.app.config.ts" in call for call in calls)
    assert step["env"]["CASEOPS_RELEASE_MODE"] == "true"
    assert "--grep-invert" in production[0]
    assert "Ram 2026-08-16 PR #237 production-safe UX proof" in production[0]


@pytest.mark.parametrize(
    ("name", "target", "old", "replacement"),
    [
        ("playwright.app.config.ts", "config", "localTransportHeaders(webBaseUrl)", "{}"),
        ("playwright.config.ts", "config", "import { localTransportHeaders }", "import {}"),
        ("playwright.docker.config.ts", "config", "...appConfig", "...{}"),
        (
            "playwright.app.self-hosted.config.ts", "config",
            "./playwright.app.config", "./unreviewed",
        ),
        (
            "playwright.prod-ram.config.ts", "config",
            "extraHTTPHeaders: noPaidProviderHeaders", "extraHTTPHeaders: {}",
        ),
        ("playwright.app.config.ts", "helper", "...noPaidProviderHeaders,", ""),
        ("playwright.config.ts", "helper", '"no-paid-providers"', '"paid-providers"'),
    ],
)
def test_provider_marker_guard_rejects_missing_or_unreviewed_headers(
    name: str, target: str, old: str, replacement: str
) -> None:
    config = (REPO_ROOT / name).read_text(encoding="utf-8")
    helper = (REPO_ROOT / "tests/e2e/support/cost-controls.ts").read_text(encoding="utf-8")
    _assert_playwright_provider_marker(name, config, helper)
    original = config if target == "config" else helper
    assert old in original
    changed = original.replace(old, replacement)
    with pytest.raises(AssertionError):
        _assert_playwright_provider_marker(
            name, changed if target == "config" else config,
            changed if target == "helper" else helper,
        )


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
    # Reviewed 15 October: trusted-main admission precedes serving code; no npm cache.
    # Exact statute/source bytes, native capture and four read-only workers remain.
    assert steps_digest == "7667cd82b237b2375ede43fbe0c7e8ed5bbd76f363e3da1a2b023006e70e1b2e"
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
    assert job["needs"] == [
        "resolve-release", "prod-playwright-shards", "prod-tester-index",
        "prod-test-legal-write-oct13",
    ]
    assert "needs.prod-tester-index.result == 'success'" in job["if"]
    assert "needs.prod-test-legal-write-oct13.result == 'success'" in job["if"]
    assert "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET" in writer["env"]
    assert "needs.resolve-release.outputs.release_sha" in writer["env"]["SERVING_RELEASE_SHA"]
    assert '--run-id "github-actions:${GITHUB_RUN_ID}:${GITHUB_RUN_ATTEMPT}"' in writer["run"]
    assert "--operational public_claims_reviewed=pass" in writer["run"]
    assert "--billing" not in writer["run"]
    assert "--pine" not in writer["run"]


def test_tester_capacity_partitions_have_explicit_serial_dependencies_and_union_gate() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    jobs = workflow["jobs"]
    original = jobs["prod-playwright-shards"]
    assert original["strategy"]["matrix"]["suite"] == [
        "tester", "tester-catalog", "test-legal-readonly", "legacy", "supporting",
        "patent-statute", "public-pages",
    ]
    for name, predecessor, suite in (
        ("prod-tester-index", "prod-playwright-shards", "tester-index"),
        ("prod-test-legal-write-oct13", "prod-tester-index", "test-legal-write-oct13"),
    ):
        job = jobs[name]
        assert job["name"] == "Prod Playwright (${{ matrix.suite }})"
        assert job["needs"] == ["resolve-release", predecessor]
        assert "always()" in job["if"] and "!cancelled()" in job["if"]
        assert f"needs.{predecessor}.result == 'failure'" in job["if"]
        assert "needs.resolve-release.result == 'success'" in job["if"]
        assert job["strategy"]["matrix"]["suite"] == [suite]
        assert job["steps"] == original["steps"]
    for name in ("prod-playwright-shards", "prod-tester-index", "prod-test-legal-write-oct13"):
        job = jobs[name]
        assert job["timeout-minutes"] == 38
        assert job["strategy"]["max-parallel"] == 1
        assert job["strategy"]["fail-fast"] is False
    certificate = jobs["record-release-evidence"]
    steps = certificate["steps"]
    union_index = next(
        i for i, step in enumerate(steps)
        if step.get("name") == "Require complete source-bound tester partition union"
    )
    writer_index = next(i for i, step in enumerate(steps)
                        if step.get("name") == "Record exact-release public-claims evidence")
    assert union_index < writer_index
    assert "--tester-partition-union" in steps[union_index]["run"]
    assert (
        "--required tester tester-catalog tester-index test-legal-write-oct13"
        in steps[union_index]["run"]
    )
    downloaded = {
        step["with"]["name"] for step in steps
        if step.get("uses") == "actions/download-artifact@v4"
    }
    assert downloaded == {
        "prod-playwright-report-tester", "prod-playwright-report-tester-index",
        "prod-playwright-report-tester-catalog", "prod-playwright-report-test-legal-write-oct13",
    }


def test_tester_budget_split_requires_release_owned_contract_before_either_partition() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    job = workflow["jobs"]["prod-playwright-shards"]
    assert job["strategy"]["matrix"]["suite"][:2] == ["tester", "tester-catalog"]
    steps = {step.get("name"): step for step in job["steps"]}
    guard = steps["Require release-owned bounded tester partition contract"]
    assert guard["if"] == "matrix.suite == 'tester' || matrix.suite == 'tester-catalog'"
    assert guard["run"].strip() == (
        "python scripts/prod_playwright_evidence.py tester-partition-contract"
    )
    assert job["steps"].index(guard) < job["steps"].index(
        steps["Run canonical tester production regressions"]
    )
    catalog = steps["Run source-bound September 05 catalog regressions"]
    assert job["steps"].index(guard) < job["steps"].index(catalog)
    assert catalog["if"] == "matrix.suite == 'tester-catalog'"
    assert catalog["env"] == steps["Run canonical tester production regressions"]["env"]
    assert catalog["run"] == (
        'bash "$RUNNER_TEMP/caseops-prod-playwright" tester-catalog '
        '--config=playwright.prod-ram.config.ts --project=tester-prod-chromium '
        '--workers=1 --retries=0 --reporter=list --output=test-results/tester-catalog'
    )


@pytest.mark.parametrize("release_contract", ["current", "old", "missing"])
def test_release_owned_tester_split_contract_cli_fails_closed_before_browser(
    tmp_path, release_contract,
):
    script = tmp_path / "scripts/prod_playwright_evidence.py"
    script.parent.mkdir()
    if release_contract == "current":
        script.write_bytes((REPO_ROOT / "scripts/prod_playwright_evidence.py").read_bytes())
    elif release_contract == "old":
        script.write_text(
            "import argparse\n"
            "p=argparse.ArgumentParser(); s=p.add_subparsers(required=True)\n"
            "s.add_parser('run'); s.add_parser('validate'); p.parse_args()\n"
            "raise AssertionError('No browser execution is permitted')\n"
        )
    result = subprocess.run(
        [sys.executable, "-B", str(script), "tester-partition-contract"],
        cwd=tmp_path, capture_output=True, encoding="utf-8", check=False, timeout=15,
    )
    assert not (tmp_path / "test-results").exists()
    if release_contract == "current":
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            "tester_partition_contract": 1,
            "partitions": {"tester": 97, "tester-catalog": 18,
                           "tester-index": 6, "test-legal-write-oct13": 51},
            "catalog_file": "ram-2026-09-05-bugs.spec.ts",
        }
    else:
        assert result.returncode != 0
        assert "No browser execution is permitted" not in result.stderr


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
    public_branch = reconcile.split("public-pages)", 1)[1].split(";;", 1)[0]
    assert " ".join(public_branch.split()) == (
        'required=(public-pages) '
        'if [[ "$PLATFORM_REPORT_READY" == true ]]; then required+=(platform-reports); fi'
    )
    assert steps["Reconcile required native Playwright evidence"]["env"][
        "PLATFORM_REPORT_READY"
    ] == "${{ steps.platform-report-prerequisites.outputs.ready }}"
    config = (REPO_ROOT / "playwright.public-seo.config.ts").read_text()
    assert "public-content\\.spec\\.ts" in config
    assert "seo_demo_20261009\\.spec\\.ts" in config
    assert "marketing\\.spec\\.ts" in config
    assert (
        "public CTA and truthful copy|public read-only prototype source rejection|"
        "FAQ panels expand and collapse"
    ) in config
    assert "globalSetup: undefined" in config and "webServer: undefined" in config
    for policy in ('trace: "off"', 'screenshot: "off"', 'video: "off"',
                   "extraHTTPHeaders: noPaidProviderHeaders"):
        assert policy in config
    assert "public-pages" not in steps.get("Run legacy QA production regressions", {}).get(
        "run", ""
    )


def test_app_ci_retains_the_complete_native_browser_inventory() -> None:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    steps = {step.get("name"): step for step in workflow["jobs"]["e2e"]["steps"]}
    execute = steps["Playwright (app config)"]
    assert execute["id"] == "app-playwright"
    assert execute["env"]["CASEOPS_EXPECTED_RELEASE_SHA"] == "${{ github.sha }}"
    assert execute["env"]["CASEOPS_RELEASE_SHA"] == "${{ github.sha }}"
    assert execute["env"]["CASEOPS_WEB_BASE_URL"] == "http://127.0.0.1:3100"
    assert execute["run"].strip() == (
        "uv run --project apps/api --python 3.13 python "
        "scripts/prod_playwright_evidence.py run --invocation ci-app -- "
        "--config=playwright.app.config.ts --workers=1 --retries=0 "
        "--reporter=list --output=test-results/app"
    )
    reconcile = steps["Reconcile app native Playwright evidence"]
    assert reconcile["if"] == (
        "always() && steps.app-playwright.outcome != 'skipped'"
    )
    assert reconcile["env"]["CASEOPS_EXPECTED_RELEASE_SHA"] == "${{ github.sha }}"
    assert reconcile["run"].strip() == (
        "uv run --project apps/api --python 3.13 python "
        "scripts/prod_playwright_evidence.py validate --required ci-app"
    )
    upload = steps["Upload Playwright report"]
    assert upload["if"] == "always()"
    assert "test-results/" in upload["with"]["path"]
    assert "test-results/prod-native-evidence/ci-app/" in upload["with"]["path"]


@pytest.mark.parametrize("stage", ["execute", "reconcile"])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_app_ci_native_commands_preserve_failures_offline(tmp_path, stage, exit_code):
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text())
    name = (
        "Playwright (app config)" if stage == "execute"
        else "Reconcile app native Playwright evidence"
    )
    step = next(step for step in workflow["jobs"]["e2e"]["steps"]
                if step.get("name") == name)
    assert step["run"].startswith("uv run --project apps/api --python 3.13 python ")
    # A shell function cannot fall through to a real uv or external service.
    script = (
        'uv() { printf "%s\\n" "$@" > native-arguments; return "$OFFLINE_EXIT"; }\n'
        + step["run"]
    )
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file()
    result = subprocess.run(
        [bash, "-e", "-c", script], cwd=tmp_path, capture_output=True, encoding="utf-8",
        env={**os.environ, "OFFLINE_EXIT": str(exit_code)},
    )
    assert result.returncode == exit_code
    arguments = (tmp_path / "native-arguments").read_text().splitlines()
    assert arguments[:7] == [
        "run", "--project", "apps/api", "--python", "3.13", "python",
        "scripts/prod_playwright_evidence.py",
    ]
    assert arguments[7:] == (
        ["run", "--invocation", "ci-app", "--", "--config=playwright.app.config.ts",
         "--workers=1", "--retries=0", "--reporter=list", "--output=test-results/app"]
        if stage == "execute" else ["validate", "--required", "ci-app"]
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
        "tester-catalog",
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


_INDEX_FIXTURE_KEYS = (
    "CASEOPS_NOTICE_QA_SLUG",
    "CASEOPS_NOTICE_OWNER_EMAIL",
    "CASEOPS_NOTICE_OWNER_PASSWORD",
)


def _index_fixture_step() -> dict:
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/prod-verify.yml").read_text())
    matches = [
        step for step in workflow["jobs"]["prod-tester-index"]["steps"]
        if step.get("name") == "Run retained indexing and Contract AI production regressions"
    ]
    assert len(matches) == 1
    assert matches[0]["if"] == "matrix.suite == 'tester-index'"
    return matches[0]


def _assert_index_fixture_environment(step: dict) -> None:
    assert step["env"]["CASEOPS_NOTICE_QA_SLUG"] == "test-legal"
    assert step["env"]["CASEOPS_NOTICE_OWNER_EMAIL"] == "ram@testfirm.com"
    assert step["env"]["CASEOPS_NOTICE_OWNER_PASSWORD"] == (
        "${{ secrets.CASEOPS_TEST_LEGAL_PROD_PASSWORD }}"
    )
    assert "CASEOPS_NOTICE_CREATE_TEST_LEGAL_MEMBER" not in step["env"]


def test_every_selected_index_dated_consumer_has_its_required_fixture_keys() -> None:
    import re

    step = _index_fixture_step()
    _assert_index_fixture_environment(step)
    config = (REPO_ROOT / "playwright.prod-ram.config.ts").read_text()
    declaration = re.search(r"const RETAINED_INDEX_PROD_SPECS = /(.+)/;", config)
    assert declaration is not None
    pattern = re.compile(declaration.group(1))
    consumers = {
        path.name: path.read_text()
        for path in (REPO_ROOT / "tests/e2e").glob("*.spec.ts")
        if pattern.fullmatch(path.name)
    }
    assert set(consumers) == {
        "ram-2026-10-10-prod.spec.ts", "ram-2026-10-12-prod.spec.ts"
    }
    project = config.split('name: "tester-index-prod-chromium"', 1)[1].split("name:", 1)[0]
    assert "testMatch: RETAINED_INDEX_PROD_SPECS" in project
    for name, source in consumers.items():
        consumed = set(re.findall(r'required\("(CASEOPS_NOTICE_[A-Z_]+)"\)', source))
        assert consumed == set(_INDEX_FIXTURE_KEYS), name
        assert consumed <= step["env"].keys(), name
        assert "noPaidProviderHeaders" in source, name
    assert step["env"]["CASEOPS_EXPECTED_RELEASE_SHA"] == (
        "${{ needs.resolve-release.outputs.release_sha }}"
    )
    assert "--project=tester-index-prod-chromium --workers=1 --retries=0" in step["run"]


@pytest.mark.parametrize("key", _INDEX_FIXTURE_KEYS)
def test_index_fixture_contract_rejects_a_missing_step_local_key(key: str) -> None:
    step = _index_fixture_step()
    step["env"].pop(key)
    with pytest.raises((AssertionError, KeyError)):
        _assert_index_fixture_environment(step)


def _run_index_fixture_guard(overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash and Path(bash).is_file()
    guard, invocation = _index_fixture_step()["run"].strip().rsplit("\n", 1)
    assert invocation == (
        'bash "$RUNNER_TEMP/caseops-prod-playwright" tester-index '
        "--config=playwright.prod-ram.config.ts --project=tester-index-prod-chromium "
        "--workers=1 --retries=0 --reporter=list --output=test-results/tester-index"
    )
    environment = dict(os.environ)
    environment.update({key: "offline" for key in _INDEX_FIXTURE_KEYS})
    for key, value in overrides.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    # Only the actual presence guard and a shell builtin run, never Playwright or a CLI.
    return subprocess.run(
        [bash, "-c", guard + "\nprintf '%s\\n' fixture-guard-passed\n"],
        env=environment, capture_output=True, text=True, timeout=5, check=False,
    )


@pytest.mark.parametrize("key", _INDEX_FIXTURE_KEYS)
@pytest.mark.parametrize("value", [None, "", " \t"])
def test_index_fixture_guard_fails_before_runner_without_printing_values(
    key: str, value: str | None,
) -> None:
    result = _run_index_fixture_guard({key: value})
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr == f"::error::Missing required tester-index fixture key: {key}\n"


def test_index_fixture_guard_admits_all_present_keys_without_printing_values() -> None:
    result = _run_index_fixture_guard({})
    assert result.returncode == 0
    assert result.stdout == "fixture-guard-passed\n"
    assert result.stderr == ""


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


BROWSER_WORKFLOW_JOBS = {
    "ci.yml": ("e2e",),
    "prod-verify.yml": (
        "prod-playwright-shards", "prod-tester-index", "prod-test-legal-write-oct13",
        "scheduled-statute-verification",
    ),
    "release-verify.yml": ("release-playwright",),
    "mobile-source.yml": ("source", "browser-handoff"),
}


def _browser_command(command: str, scripts: dict[str, str], seen: tuple[str, ...] = ()) -> bool:
    import re

    if re.search(
        r"\bplaywright\s+(?:install(?:-deps)?|test)\b|"
        r"\b(?:chromium|firefox|webkit)\.launch\s*\(|"
        r"scripts/(?:run-public-content-e2e\.mjs|run-functional-qa-e2e\.mjs|verify-docker\.ps1)|"
        r"scripts/prod_playwright_evidence\.py\s+run\b",
        command,
    ):
        return True
    for name, body in scripts.items():
        if name not in seen and re.search(
            r"\b(?:npm\s+run|pnpm(?:\s+run)?)\s+" + re.escape(name) + r"(?=\s|$)",
            command,
        ) and _browser_command(body, scripts, (*seen, name)):
            return True
    return False


def _browser_workflows() -> tuple[dict, dict]:
    import yaml

    directory = REPO_ROOT / ".github/workflows"
    workflows = {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted((*directory.glob("*.yml"), *directory.glob("*.yaml")))
    }
    scripts = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
    return workflows, scripts


def _assert_browser_workflow_runners(workflows: dict, scripts: dict) -> None:
    expected = {(name, job) for name, jobs in BROWSER_WORKFLOW_JOBS.items() for job in jobs}
    actual = {
        (name, job_id): job
        for name, workflow in workflows.items()
        for job_id, job in workflow["jobs"].items()
        if any(_browser_command(step.get("run", ""), scripts) for step in job.get("steps", []))
    }
    assert set(actual) == expected, "Complete browser-job inventory changed; review every caller"
    invalid = [(name, job, value.get("runs-on")) for (name, job), value in actual.items()
               if value.get("runs-on") != "ubuntu-24.04"]
    assert not invalid, f"Locked Playwright browser jobs require literal ubuntu-24.04: {invalid}"


def test_browser_workflow_jobs_pin_the_locked_playwright_supported_runner() -> None:
    workflows, scripts = _browser_workflows()
    _assert_browser_workflow_runners(workflows, scripts)


@pytest.mark.parametrize("workflow,job", [
    (name, job) for name, jobs in BROWSER_WORKFLOW_JOBS.items() for job in jobs
])
@pytest.mark.parametrize("runner", ["ubuntu-latest", "ubuntu-26.04", "${{ matrix.os }}"])
def test_browser_runner_contract_rejects_floating_unsupported_or_dynamic_labels(
    workflow: str, job: str, runner: str,
) -> None:
    workflows, scripts = _browser_workflows()
    for name, jobs in BROWSER_WORKFLOW_JOBS.items():
        for job_id in jobs:
            workflows[name]["jobs"][job_id]["runs-on"] = "ubuntu-24.04"
    workflows[workflow]["jobs"][job]["runs-on"] = runner
    with pytest.raises(AssertionError, match="literal ubuntu-24.04"):
        _assert_browser_workflow_runners(workflows, scripts)


@pytest.mark.parametrize("command", [
    "npx playwright install chromium", "pnpm exec playwright test",
    "npm run test:e2e:app", "pnpm run test:e2e:public-content",
    "pwsh -File scripts/verify-docker.ps1",
])
def test_browser_runner_inventory_rejects_unreviewed_direct_or_script_callers(command: str) -> None:
    workflows, scripts = _browser_workflows()
    workflows["ci.yml"]["jobs"]["unreviewed-browser"] = {
        "runs-on": "ubuntu-24.04", "steps": [{"run": command}],
    }
    with pytest.raises(AssertionError, match="Complete browser-job inventory"):
        _assert_browser_workflow_runners(workflows, scripts)


@pytest.mark.parametrize("job", ["prod-tester-index", "prod-test-legal-write-oct13"])
def test_browser_runner_inventory_keeps_both_yaml_anchor_consumers(job: str) -> None:
    workflows, scripts = _browser_workflows()
    del workflows["prod-verify.yml"]["jobs"][job]
    with pytest.raises(AssertionError, match="Complete browser-job inventory"):
        _assert_browser_workflow_runners(workflows, scripts)


@pytest.mark.parametrize("suffix", ["yml", "yaml"])
def test_browser_runner_inventory_discovers_a_new_workflow_file(tmp_path, monkeypatch, suffix):
    import yaml

    original_root = REPO_ROOT
    directory = tmp_path / ".github/workflows"
    directory.mkdir(parents=True)
    for name in BROWSER_WORKFLOW_JOBS:
        shutil.copyfile(REPO_ROOT / ".github/workflows" / name, directory / name)
    shutil.copyfile(REPO_ROOT / "package.json", tmp_path / "package.json")
    new_name = f"unreviewed-browser.{suffix}"
    (directory / new_name).write_text(yaml.safe_dump({"jobs": {
        "browser": {"runs-on": "ubuntu-24.04", "steps": [{"run": "pnpm exec playwright test"}]}
    }}), encoding="utf-8")
    with monkeypatch.context() as override:
        override.setattr(sys.modules[__name__], "REPO_ROOT", tmp_path)
        workflows, scripts = _browser_workflows()
        assert new_name in workflows
        with pytest.raises(AssertionError, match="Complete browser-job inventory"):
            _assert_browser_workflow_runners(workflows, scripts)
    assert REPO_ROOT is original_root
