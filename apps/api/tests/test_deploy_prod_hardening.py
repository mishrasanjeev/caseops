from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from functools import cache
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]


def _read_repo_text(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_shell_scripts_are_checked_out_with_lf_line_endings() -> None:
    attributes = _read_repo_text(".gitattributes").splitlines()

    assert "*.sh text eol=lf" in attributes


def test_web_gcloudignore_blocks_local_build_artifacts() -> None:
    """Regression for the 2026-06-26 Windows deploy archive failure.

    Docker's .dockerignore is applied after gcloud has already staged
    the source archive. The web Cloud Build context needs its own
    .gcloudignore so local node_modules/.next never get uploaded.
    """
    ignore_text = _read_repo_text("apps/web/.gcloudignore")

    required_patterns = {
        "node_modules/",
        ".next/",
        ".env.local",
        ".env*.local",
        "tsconfig.tsbuildinfo",
        "test-results/",
        "playwright-report/",
    }
    for pattern in required_patterns:
        assert pattern in ignore_text


def test_local_playwright_api_does_not_reuse_idle_mutation_connections() -> None:
    config = _read_repo_text("playwright.app.config.ts")
    cost_spec = _read_repo_text("tests/e2e/iplf-039f-cost-items-2026-08-21.spec.ts")

    assert config.count("--timeout-keep-alive 0") == 2
    assert "BOOTSTRAP_TRANSPORT_ATTEMPTS" not in cost_spec
    assert "isConnectionReset" not in cost_spec


def test_production_deploy_seeds_verified_statutes_before_routing_traffic() -> None:
    deploy = _read_repo_text("scripts/deploy-prod.sh")

    seed_update = 'gcloud run jobs "${STATUTE_SEED_ACTION}" "${STATUTE_SEED_JOB}"'
    seed_execute = 'gcloud run jobs execute "${STATUTE_SEED_JOB}"'
    api_deploy = "gcloud run deploy caseops-api"
    assert "caseops_api.scripts.seed_statutes" in deploy
    assert "STATUTE_SEED_JOB=caseops-seed-statutes" in deploy
    assert '--image "${API_IMMUTABLE_IMAGE}"' in deploy
    assert seed_update in deploy
    assert seed_execute in deploy
    assert deploy.index(seed_update) < deploy.index(seed_execute) < deploy.index(api_deploy)


def test_production_deploy_owns_indian_kanoon_activation_without_manual_data_entry() -> None:
    deploy = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/api-service.yaml")

    seed_update = (
        'gcloud run jobs "${INDIAN_KANOON_COST_SEED_ACTION}" "${INDIAN_KANOON_COST_SEED_JOB}"'
    )
    seed_execute = 'gcloud run jobs execute "${INDIAN_KANOON_COST_SEED_JOB}"'
    api_deploy = "gcloud run deploy caseops-api"
    assert "caseops_api.scripts.seed_indian_kanoon_costs" in deploy
    assert "INDIAN_KANOON_COST_SEED_JOB=caseops-seed-indian-kanoon-costs" in deploy
    assert deploy.index(seed_update) < deploy.index(seed_execute) < deploy.index(api_deploy)
    assert "CASEOPS_INDIAN_KANOON_API_TOKEN=${INDIAN_KANOON_API_TOKEN_SECRET}:latest" in deploy
    assert "CASEOPS_INDIAN_KANOON_ENABLED=true" in deploy
    assert '--update-env-vars "^|^CASEOPS_RELEASE_SHA=${HEAD_SHA}|' in deploy
    assert "|CASEOPS_INDIAN_KANOON_PERMITTED_USES=${INDIAN_KANOON_PERMITTED_USES}|" in deploy
    assert 'env.get("CASEOPS_INDIAN_KANOON_API_TOKEN")' in deploy
    assert "expected_indian_kanoon_env" in deploy
    assert 'value: "Orchestrum Technologies LLP"' in manifest
    assert 'name: "caseops-indian-kanoon-api-token"' in manifest


def test_production_deploy_pins_openai_and_verifies_runtime_readback() -> None:
    deploy = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/api-service.yaml")

    assert "LLM_API_KEY_SECRET=caseops-openai-api-key" in deploy
    assert "CASEOPS_LLM_API_KEY=${LLM_API_KEY_SECRET}:latest" in deploy
    assert "CASEOPS_LLM_PROVIDER=${LLM_PROVIDER}" in deploy
    assert "CASEOPS_LLM_MODEL=${LLM_MODEL}" in deploy
    assert "CASEOPS_LLM_MODEL_RECOMMENDATIONS=${LLM_RECOMMENDATIONS_MODEL}" in deploy
    assert 'env.get("CASEOPS_LLM_API_KEY")' in deploy
    assert '"CASEOPS_LLM_PROVIDER": "openai"' in deploy
    assert '"CASEOPS_LLM_MODEL": "gpt-5.1"' in deploy
    assert '"CASEOPS_LLM_MODEL_RECOMMENDATIONS": "gpt-5-mini"' in deploy
    assert 'name: CASEOPS_LLM_PROVIDER\n              value: "openai"' in manifest
    assert 'name: CASEOPS_LLM_API_KEY' in manifest
    assert 'name: "caseops-openai-api-key"' in manifest
    assert "CASEOPS_OPENAI_API_KEY" not in manifest


def test_production_manifests_block_paid_providers_for_test_tenants() -> None:
    blocked_slugs = "caseops-qa;caseops-ip-qa;test-legal"
    expected = f'"{blocked_slugs}"'
    api_manifest = _read_repo_text("infra/cloudrun/api-service.yaml")
    poll_manifest = _read_repo_text("infra/cloudrun/case-tracking-poll-job.yaml")
    deploy = _read_repo_text("scripts/deploy-prod.sh")

    for manifest in (api_manifest, poll_manifest):
        assert "CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS" in manifest
        assert expected in manifest
    assert f'PAID_PROVIDER_BLOCKED_COMPANY_SLUGS="{blocked_slugs}"' in deploy
    assert (
        "CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS="
        "${PAID_PROVIDER_BLOCKED_COMPANY_SLUGS}" in deploy
    )
    assert 'env.get("CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS")' in deploy


def test_live_paid_provider_probe_is_explicit_and_excluded_from_regular_e2e() -> None:
    config = _read_repo_text("playwright.paid-provider-live.config.ts")
    regular_config = _read_repo_text("playwright.config.ts")
    spec = _read_repo_text("tests/e2e/paid-provider-live-2026-09-03-prod.spec.ts")

    assert "CASEOPS_ALLOW_LIVE_PAID_PROVIDER_TESTS" in config
    assert "noPaidProviderHeaders" not in config
    assert "paid-provider-live-2026-09-03-prod" in regular_config
    assert "max_results: 1" in spec
    assert "bulk-refresh" not in spec


@pytest.mark.parametrize(
    "config_path",
    [
        "playwright.prod-ram.config.ts",
        "playwright.notice-prod.config.ts",
        "playwright.ip-a0-prod.config.ts",
        "playwright.ip-cost-prod.config.ts",
        "playwright.ip-guard-first-prod.config.ts",
    ],
)
def test_production_playwright_does_not_retain_authenticated_media(
    config_path: str,
) -> None:
    config = _read_repo_text(config_path)

    for setting in ('trace: "off"', 'screenshot: "off"', 'video: "off"'):
        assert setting in config
    assert "retain-on-failure" not in config
    assert "only-on-failure" not in config


def test_private_retrieval_production_acceptance_is_exact_and_release_owned() -> None:
    config = _read_repo_text("playwright.prod-ram.config.ts")
    workflow = _read_repo_text(".github/workflows/prod-verify.yml")
    deploy = _read_repo_text("scripts/deploy-prod.sh")
    bootstrap = _read_repo_text("apps/api/src/caseops_api/scripts/bootstrap_ip_production_qa.py")
    spec = _read_repo_text("tests/e2e/iplf-066b-private-retrieval-2026-08-31-prod.spec.ts")

    assert config.count("iplf-066b-private-retrieval-2026-08-31-prod") == 2
    assert "playwright.prod-ram.config.ts" in workflow
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert 'required("CASEOPS_IP_QA_PASSWORD")' in spec
    assert "`${API}/api/build`" in spec
    assert "`${WEB}/api/release-identity`" in spec
    assert spec.count("/api/private-retrieval/search") == 2
    assert "/lifecycle/status" in spec
    assert "expected_updated_at: current.updated_at" in spec
    assert "This answer is hidden because access" in spec
    assert "spawnSync" not in spec
    assert "DATABASE_URL" not in spec
    assert '_required_env("CASEOPS_QA_RELEASE_SHA")' in bootstrap
    assert "fixture_pattern = re.compile" in bootstrap
    assert 'candidate.status == "active"' in bootstrap
    assert 'candidate.status not in {"closed", "disposed"}' in bootstrap
    assert "max(iterations.values(), default=0) + 1" in bootstrap
    assert '--update-env-vars "CASEOPS_QA_RELEASE_SHA=${HEAD_SHA}"' in deploy
    assert deploy.index("run deploy caseops-web") < deploy.index(
        "run jobs execute caseops-ip-qa-bootstrap"
    )
    assert deploy.index("run jobs execute caseops-ip-qa-bootstrap") < deploy.index(
        "gh workflow run prod-verify.yml"
    )


def test_a0_production_acceptance_is_an_isolated_verify_only_gate() -> None:
    workflow = _read_repo_text(".github/workflows/prod-verify.yml")
    config = _read_repo_text("playwright.ip-a0-prod.config.ts")
    app_config = _read_repo_text("playwright.app.config.ts")
    root_config = _read_repo_text("playwright.config.ts")
    broad_config = _read_repo_text("playwright.prod-ram.config.ts")
    spec = _read_repo_text("tests/e2e/iplf-027b-a0-quiescence-2026-08-14-prod.spec.ts")

    assert "Run IPLF-027B A0 quiescence acceptance" in workflow
    prerequisite_gate = (
        "if: always() && !cancelled() && "
        "steps.prod-playwright-prerequisites.outputs.ready == 'true'"
    )
    assert "id: prod-playwright-prerequisites" in workflow
    # Renewal preflight, renewal acceptance, and Notice remain visible
    # independently after the broad RAM batch. The historical A0 transition
    # gate additionally requires an explicit manual opt-in.
    assert workflow.count(prerequisite_gate) == 6
    assert (prerequisite_gate + " && inputs.run_historical_a0_gate == true") in workflow
    assert "CASEOPS_IP_A0_PROD_MODE: verify" in workflow
    assert (
        "npx playwright test --config=playwright.ip-a0-prod.config.ts --reporter=list" in workflow
    )
    assert (
        workflow.index("Run prod-Playwright suite (ram-batch)")
        < workflow.index("Run IPLF-027B A0 quiescence acceptance")
        < workflow.index("Run prod-Playwright suite (notice module)")
    )
    assert "testMatch: /iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in config
    assert "testIgnore: /iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in app_config
    assert "/iplf-027b-a0-quiescence-2026-08-14-prod\\.spec\\.ts$/" in root_config
    assert "iplf-027b-a0-quiescence-2026-08-14-prod" not in broad_config
    assert 'process.env.CASEOPS_IP_A0_PROD_MODE ?? "verify"' in spec
    assert 'const PROD_BASE_URL = "https://caseops.ai"' in spec
    assert 'const PROD_API_BASE_URL = "https://api.caseops.ai"' in spec
    assert 'const IP_QA_SLUG = "caseops-ip-qa"' in spec
    assert 'const IP_QA_EMAIL = "ip-qa-bot@caseops.ai"' in spec
    assert "process.env.PROD_BASE_URL" not in spec
    assert "process.env.PROD_API_BASE_URL" not in spec
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert "`${PROD_API_BASE_URL}/api/build`" in spec
    assert "`${PROD_BASE_URL}/api/release-identity`" in spec
    assert spec.count("await expectQuiesced(") == 3
    assert spec.count("newContext({ maxRedirects: 0 })") == 2
    test_body = spec.rsplit(
        'test("IPLF-027B A0 production quiescence and legal-deadline continuity"',
        maxsplit=1,
    )[1]
    assert (
        test_body.index("assertCanonicalProductionOrigins();")
        < test_body.index("newContext({ maxRedirects: 0 })")
        < test_body.index("assertExactRelease(api)")
    )
    for endpoint in (
        "/api/ip/deadline-rules",
        "/activate",
        "/transition",
        "/api/ip/dockets/${docket.id}/deadlines",
        "/deadlines/${proposed.id}/confirm",
        "/deadlines/${proposed.id}/recalculate",
        "/deadlines/${confirmed.id}/override",
        "/deadlines/${overridden.id}/complete",
    ):
        assert endpoint in spec
    assert "caseops-ip-qa-password --project perfect-period-305406" in spec
    assert "$LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace" in spec
    assert "Remove-Item Env:CASEOPS_IP_QA_PASSWORD" in spec
    assert "isReservedPreparationAdmin" in spec
    assert 'user.role === "admin"' in spec
    assert "iplf-027b-a0-(?:reviewer|legal-approver)-" in spec
    assert "@example\\.com$" in spec
    assert spec.index("await reconcilePreparationAdmins") < spec.index(
        "if (calendar && rule && selected)"
    )
    assert 'right_kind: "trademark"' in spec
    assert 'right_kind: "patent"' in spec
    assert "await reconcilePriorSyntheticMatters" in spec
    assert "/api/matters/${matterId}/lifecycle/status" in spec
    assert "expected_from_status: current.status" in spec
    assert "notification_intent_ids: []" in spec
    verify_body = spec.split("async function verifyQuiescenceAndDeadlineWriters", maxsplit=1)[
        1
    ].split("/**\n * One-time fixture preparation", maxsplit=1)[0]
    assert verify_body.index("createFreshMatter") < verify_body.index("try {")
    assert (
        verify_body.index("persistedRecalculation")
        < verify_body.index("finally {")
        < verify_body.index("disposeSyntheticMatter")
    )
    assert "test.skip" not in spec
    a0_step = workflow.split("Run IPLF-027B A0 quiescence acceptance", maxsplit=1)[1].split(
        "Run prod-Playwright suite (notice module)", maxsplit=1
    )[0]
    assert "timeout-minutes: 5" in a0_step
    assert "PROD_BASE_URL:" not in a0_step
    assert "PROD_API_BASE_URL:" not in a0_step
    assert "CASEOPS_IP_QA_EMAIL:" not in a0_step
    assert "CASEOPS_IP_QA_SLUG:" not in a0_step


def test_renewal_production_acceptance_is_exact_release_and_fail_closed() -> None:
    workflow = _read_repo_text(".github/workflows/prod-verify.yml")
    config = _read_repo_text("playwright.ip-renewal-prod.config.ts")
    broad_config = _read_repo_text("playwright.prod-ram.config.ts")
    spec = _read_repo_text("tests/e2e/iplf-037b-renewal-2026-08-22-prod.spec.ts")

    assert "Run IPLF-037B renewal acceptance" in workflow
    assert "Check IPLF-037B renewal acceptance configuration" in workflow
    assert "playwright.ip-renewal-prod.config.ts" in workflow
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert 'required("CASEOPS_IP_QA_PASSWORD")' in spec
    for fixture_id in (
        "CASEOPS_IP_RENEWAL_CALENDAR_VERSION_ID",
        "CASEOPS_IP_RENEWAL_RULE_VERSION_ID",
        "CASEOPS_IP_RENEWAL_GRACE_RULE_VERSION_ID",
        "CASEOPS_IP_RENEWAL_NEXT_TERM_RULE_VERSION_ID",
    ):
        assert fixture_id in workflow
        assert fixture_id in spec
    assert 'if [[ "$configured" -eq 0 ]]' in workflow
    assert 'elif [[ "$configured" -ne 4 ]]' in workflow
    assert "the external legal-governance activation blocker remains open" in workflow
    assert "steps.renewal-prerequisites.outputs.configured == 'true'" in workflow
    assert 'const WEB = "https://caseops.ai"' in spec
    assert 'const API = "https://api.caseops.ai"' in spec
    assert 'const SLUG = "caseops-ip-qa"' in spec
    assert "process.env.PROD_BASE_URL" not in spec
    assert "process.env.PROD_API_BASE_URL" not in spec
    assert "cleanup refuses non-reserved Matter shapes" in spec
    assert "await disposeMatter(matter)" in spec
    assert "await deactivateSupervisor()" in spec
    assert 'trace: "off"' in config
    assert 'screenshot: "off"' in config
    assert 'video: "off"' in config
    assert "iplf-037b-renewal-2026-08-22-prod" not in broad_config


def test_guard_first_production_acceptance_is_isolated_and_recoverable() -> None:
    root_config = _read_repo_text("playwright.config.ts")
    config = _read_repo_text("playwright.ip-guard-first-prod.config.ts")
    spec = _read_repo_text("tests/e2e/iplf-039c-guard-first-2026-08-16-prod.spec.ts")
    plan = _read_repo_text(
        "docs/ip-implementation/evidence/m3/IPLF-039C/"
        "guard-first-production-acceptance-plan-2026-08-16.md"
    )

    guard_pattern = "/iplf-039c-guard-first-2026-08-16-prod\\.spec\\.ts$/"
    assert guard_pattern in root_config
    assert f"testMatch: {guard_pattern}" in config
    assert "retries: 0" in config
    for setting in ('trace: "off"', 'screenshot: "off"', 'video: "off"'):
        assert setting in config

    assert 'required("CASEOPS_IP_GUARD_RUN_ID")' in spec
    assert 'required("CASEOPS_EXPECTED_RELEASE_SHA")' in spec
    assert 'required("CASEOPS_IP_GUARD_QA_ACK")' in spec
    assert 'const PROD_BASE_URL = "https://caseops.ai"' in spec
    assert 'const PROD_API_BASE_URL = "https://api.caseops.ai"' in spec
    assert "process.env.PROD_BASE_URL" not in spec
    assert "process.env.PROD_API_BASE_URL" not in spec
    assert "playwrightRequest.newContext({ maxRedirects: 0 })" in spec
    assert spec.count("await newNoRedirectContext()") == 2
    assert "request: api" not in spec
    test_body = spec.rsplit(
        'test("guard-first writers reject role collapse and preserve disposable QA state"',
        maxsplit=1,
    )[1]
    assert (
        test_body.index("assertCanonicalProductionOrigins();")
        < test_body.index("await newNoRedirectContext()")
        < test_body.index("await authenticateOwner(api, run)")
    )
    assert "ownerApi: api" in test_body
    assert "await cleanupReservedRun(state.ownerApi, state)" in spec
    assert "const replacementApi = await newNoRedirectContext()" in test_body
    assert "authenticateUser(\n      replacementApi," in test_body
    assert "await assertCurrentActor(api, run, owner)" in test_body
    assert "await replacementApi.post(" in test_body
    assert "authHeaders(replacementAuth)" in test_body
    assert "`${run.apiBaseUrl}/api/companies/current`" in spec
    assert "await assertCurrentActor(api, run, auth)" in spec
    assert 'expect(auth.membership.role).toBe("member")' in spec
    assert 'expect(auth.capabilities).not.toContain("ip:approve")' in spec
    assert 'expect(auth.capabilities).not.toContain("company:manage_users")' in spec
    assert 'randomBytes(24).toString("base64url")' in spec
    assert "QaGuard-${runId}" not in spec
    assert "JSON.stringify(await body(response))" not in spec
    assert "await response.text()" not in spec
    assert "unexpected HTTP status" in spec
    assert "async function assertDeadlineGovernancePrerequisites" in spec
    assert (
        test_body.index("await assertDeadlineGovernancePrerequisites(")
        < test_body.index("const conflictDeadline = await createOperationalDeadline(")
        < test_body.index("const collapsedCreate = await api.post(")
    )
    assert spec.count("await assertExactRelease(api, run)") == 2
    assert "test.afterEach" in spec
    assert "testInfo.setTimeout(CLEANUP_TIMEOUT_MS)" in spec
    assert "recoverReservedUsers" in spec
    assert "recoverReservedMatters" in spec
    assert "recoverReservedDockets" in spec
    assert "CLEANUP_REQUEST_TIMEOUT_MS" in spec
    assert "cleanup_failure_${index + 1}; phase=${failure.phase}; target=${failure.target}" in spec
    assert "error.message" not in spec
    assert "new AggregateError" not in spec
    assert "/lifecycle/status" in spec
    assert "randomUUID" not in spec
    assert "## Manual recovery" in plan
    assert "Do not reuse the recovered run id" in plan


def test_local_playwright_enables_rule_governance_journey_explicitly() -> None:
    e2e_env = _read_repo_text("tests/e2e/support/env.ts")

    assert 'CASEOPS_IP_RULE_GOVERNANCE_ENABLED: "true"' in e2e_env


def test_deploy_prod_uses_web_gcloudignore_explicitly() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "WEB_GCLOUDIGNORE_FILE=.gcloudignore" in script
    assert "WEB_GCLOUDIGNORE_PATH=.gcloudignore" in script
    assert "WEB_CLOUD_BUILD_CONFIG=apps/web/cloudbuild.yaml" in script
    assert '--ignore-file "${WEB_GCLOUDIGNORE_FILE}"' in script
    assert '--config "${WEB_CLOUD_BUILD_CONFIG}"' in script
    assert '"_WEB_IMAGE=${WEB_IMAGE},_RELEASE_SHA=${HEAD_SHA}"' in script
    assert '[[ ! -f "${WEB_GCLOUDIGNORE_PATH}" ]]' in script


def test_web_image_uses_committed_workspace_lockfile() -> None:
    dockerfile = _read_repo_text("apps/web/Dockerfile")
    compose = _read_repo_text("docker-compose.yml")
    cloudbuild = _read_repo_text("apps/web/cloudbuild.yaml")
    dockerignore = _read_repo_text(".dockerignore")
    gcloudignore = _read_repo_text(".gcloudignore")

    assert "COPY package.json package-lock.json ./" in dockerfile
    assert "RUN npm ci --no-audit --no-fund" in dockerfile
    assert "npm install" not in dockerfile
    assert "npm prune --omit=dev" in dockerfile
    assert "context: ." in compose
    assert "dockerfile: apps/web/Dockerfile" in compose
    assert "apps/web/Dockerfile" in cloudbuild
    assert "CASEOPS_RELEASE_SHA=${_RELEASE_SHA}" in cloudbuild
    for ignore in (dockerignore, gcloudignore):
        assert "!package-lock.json" in ignore
        assert "!apps/web/**" in ignore
        assert "apps/web/node_modules/" in ignore


def test_workstation_docker_gate_is_migration_first_and_exact_release() -> None:
    compose = _read_repo_text("docker-compose.yml")
    docker_script = _read_repo_text("scripts/verify-docker.ps1")
    playwright_config = _read_repo_text("playwright.docker.config.ts")
    e2e_env = _read_repo_text("tests/e2e/support/env.ts")
    e2e_helpers = _read_repo_text("tests/e2e/support/helpers.ts")

    assert "NEXT_PUBLIC_API_BASE_URL: ${CASEOPS_DOCKER_PUBLIC_API_URL" in compose
    assert 'command: ["alembic", "upgrade", "head"]' in compose
    assert compose.count("condition: service_completed_successfully") == 2
    assert compose.count('CASEOPS_AUTO_MIGRATE: "false"') == 3
    assert compose.count("org.opencontainers.image.revision") == 0
    assert "condition: service_healthy" in compose
    assert "${CASEOPS_DOCKER_VALKEY_PORT:-16379}:6379" in compose

    assert '$ComposeProject = "caseops-acceptance-$($ReleaseSha.Substring(0, 12))"' in docker_script
    assert (
        "$PortBlock = [Convert]::ToInt32($ReleaseSha.Substring(0, 6), 16) % 6000" in docker_script
    )
    assert "$PreferredPortBase = 20000 + ($PortBlock * 5)" in docker_script
    assert "function Test-TcpPortBlockAvailable" in docker_script
    assert "foreach ($Offset in 0..4)" in docker_script
    assert "$Listener.ExclusiveAddressUse = $true" in docker_script
    assert "function Get-AvailablePortBase" in docker_script
    assert "foreach ($ProbeOffset in 0..5999)" in docker_script
    assert "$PortBase = Get-AvailablePortBase -InitialBlock $PortBlock" in docker_script
    assert "is reserved or occupied" in docker_script
    assert 'CASEOPS_DOCKER_PUBLIC_API_URL = "http://127.0.0.1:$TestApiPort"' in docker_script
    assert "CASEOPS_E2E_API_PORT = $TestApiPort" in docker_script
    assert (
        '$TestApiProxyScript = Join-Path $RepoRoot "scripts\\docker-acceptance-api-proxy.mjs"'
        in docker_script
    )
    assert '-ArgumentList @("`"$TestApiProxyScript`"", $TestApiPort, $ApiPort)' in docker_script
    assert "if ($PlaywrightArgs.Count -eq 0)" in docker_script
    assert 'Get-Content -LiteralPath (Join-Path $RepoRoot ".nvmrc")' in docker_script
    assert "$ActualNodeVersion -ne $PinnedNodeVersion" in docker_script
    assert "Activate the pinned runtime before retrying" in docker_script
    assert "& $NpmPath ci --no-audit --no-fund" in docker_script
    assert docker_script.count("& $NpxPath playwright test") == 4
    assert "--project=app-chromium --shard=1/2" in docker_script
    assert "--project=app-chromium --shard=2/2" in docker_script
    assert "--project=app-mobile" in docker_script
    assert "Docker Playwright focused acceptance failed" in docker_script
    assert "--retries" not in docker_script
    assert "git -C $RepoRoot status" in docker_script
    assert "| Out-String).Trim()" in docker_script
    assert "$SourceFingerprint.Substring(0, 40)" in docker_script
    assert 'SourceFingerprint -notmatch "^[0-9a-f]{64}$"' in docker_script
    assert 'Write-Host "[docker-acceptance] derived runtime revision $ReleaseSha"' in docker_script
    assert "down --volumes --remove-orphans" in docker_script
    assert "if (-not $KeepRunning)" in docker_script
    assert "building API and web production images" in docker_script
    assert "MigrationExitCode" in docker_script
    assert "org.opencontainers.image.revision" in docker_script
    assert "docker image inspect $ImageId | ConvertFrom-Json" in docker_script
    assert "ApiIdentity.release_sha" in docker_script
    assert "WebIdentity.release_sha" in docker_script
    assert "PostTestHealth" in docker_script
    assert "CASEOPS_E2E_DATABASE_URL" in docker_script
    assert "CASEOPS_E2E_DOCKER_PROJECT" in docker_script
    assert "CASEOPS_E2E_DOCKER_COMPOSE_FILE" in docker_script
    assert "exec --no-TTY api caseops-db-index-health" in docker_script
    assert "PostgreSQL index health gate failed" in docker_script
    assert "--memory 512m" in docker_script
    assert "--memory-swap 512m" in docker_script
    assert "label=com.docker.compose.network=default" in docker_script
    assert "exceeded its 512 MiB production job ceiling" in docker_script
    assert "function Get-ComposeServiceState" in docker_script
    assert "stop --timeout 30 worker" in docker_script
    assert "start worker" in docker_script
    assert '$WorkerStateAfterRestart -ne "running"' in docker_script
    assert '$WorkerStateAfterPlaywright -ne "running"' in docker_script
    assert docker_script.index("stop --timeout 30 worker") < docker_script.index("-m postgres")
    assert docker_script.index("-m postgres") < docker_script.index("start worker")
    assert docker_script.index("start worker") < docker_script.index(
        "$WorkerStateAfterPlaywright = Get-ComposeServiceState"
    )

    assert "globalSetup: undefined" in playwright_config
    assert "webServer: undefined" in playwright_config
    assert "CASEOPS_WEB_BASE_URL" in playwright_config
    assert "process.env.CASEOPS_E2E_DATABASE_URL" in e2e_env
    assert "process.env.CASEOPS_WEB_BASE_URL" in e2e_env
    assert "CASEOPS_E2E_DOCKER_PROJECT" in e2e_helpers
    assert '"caseops-document-worker"' in e2e_helpers
    assert '"--skip-migrations"' in e2e_helpers


@pytest.mark.parametrize("dockerfile", ["apps/api/Dockerfile", "apps/web/Dockerfile"])
def test_release_images_carry_exact_revision_label(dockerfile: str) -> None:
    image = _read_repo_text(dockerfile)

    assert "ARG CASEOPS_RELEASE_SHA=unavailable" in image
    assert "LABEL org.opencontainers.image.revision=$CASEOPS_RELEASE_SHA" in image


def test_api_release_image_uses_frozen_dependencies_before_source_layers() -> None:
    image = _read_repo_text("apps/api/Dockerfile")

    assert "COPY pyproject.toml uv.lock README.md ./" in image
    assert "uv export \\" in image
    assert "--frozen" in image
    assert "--no-emit-project" in image
    assert "uv pip install --system --requirements /tmp/requirements.lock" in image
    assert "uv pip install --system --no-deps ." in image
    assert image.index("--frozen") < image.index("COPY src ./src")
    assert image.index("Tokenizer.from_pretrained") < image.index("COPY src ./src")
    assert image.index("TextCrossEncoder") < image.index("COPY src ./src")


def test_api_release_declares_cross_platform_timezone_data() -> None:
    project = tomllib.loads(_read_repo_text("apps/api/pyproject.toml"))["project"]

    assert "tzdata==2026.1" in project["dependencies"]


def test_deploy_prod_uses_api_gcloudignore_explicitly() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")
    cloudbuild = _read_repo_text("apps/api/cloudbuild.yaml")

    assert "API_GCLOUDIGNORE_FILE=.gcloudignore" in script
    assert 'API_GCLOUDIGNORE_PATH="${API_SOURCE_DIR}/${API_GCLOUDIGNORE_FILE}"' in script
    assert "API_CLOUD_BUILD_CONFIG=apps/api/cloudbuild.yaml" in script
    assert '--ignore-file "${API_GCLOUDIGNORE_FILE}"' in script
    assert '--config "${API_CLOUD_BUILD_CONFIG}"' in script
    assert '"_API_IMAGE=${API_IMAGE},_RELEASE_SHA=${HEAD_SHA}"' in script
    assert '[[ ! -f "${API_GCLOUDIGNORE_PATH}" ]]' in script
    assert "CASEOPS_RELEASE_SHA=${_RELEASE_SHA}" in cloudbuild
    assert "${_API_IMAGE}" in cloudbuild


def test_deploy_prod_uses_service_minimums_and_clears_stale_revision_tags() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert '--min "${API_MIN_INSTANCES}"' in script
    assert '--min "${WEB_MIN_INSTANCES}"' in script
    assert script.count("--min-instances default") == 2
    assert "--to-latest --clear-tags --quiet" in script
    assert '--min-instances "${API_MIN_INSTANCES}"' not in script
    assert '--min-instances "${WEB_MIN_INSTANCES}"' not in script
    assert "API_MIN_INSTANCES=4" in script
    assert "49.758s queued request" in script
    assert 'annotations.get("run.googleapis.com/minScale")' in script
    assert "MIGRATION_TASK_TIMEOUT=30m" in script
    assert '--task-timeout "${MIGRATION_TASK_TIMEOUT}"' in script


def test_migration_job_binds_and_verifies_dedicated_database_timeouts() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/migrate-job.yaml")
    expected = {
        "CASEOPS_MIGRATION_DB_CONNECT_TIMEOUT_SECONDS": "10",
        "CASEOPS_MIGRATION_DB_STATEMENT_TIMEOUT_MS": "900000",
        "CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS": "5000",
        "CASEOPS_MIGRATION_DB_IDLE_TRANSACTION_TIMEOUT_MS": "60000",
    }

    assert "timeoutSeconds: 1800" in manifest
    for name, value in expected.items():
        assert f'- name: {name}\n                  value: "{value}"' in manifest
        shell_name = name.removeprefix("CASEOPS_")
        assert f"{shell_name}={value}" in script
        assert f"{name}=${{{shell_name}}}" in script

    update_index = script.index("gcloud run jobs update caseops-migrate-job")
    verify_index = script.index("MIGRATION_JOB_JSON=$(gcloud run jobs describe")
    execute_index = script.index("gcloud run jobs execute caseops-migrate-job")
    assert update_index < verify_index < execute_index
    assert "caseops-migrate-job database timeout drift" in script
    assert "actual != expected" in script


def test_deploy_prod_fences_rule_governance_and_verifies_exact_traffic() -> None:
    script = _read_repo_text("scripts/deploy-prod.sh")

    assert "CASEOPS_IP_RULE_GOVERNANCE_ENABLED=false" in script
    assert ("MACHINE_READINESS_EVIDENCE_SECRET=caseops-machine-readiness-evidence-secret") in script
    assert (
        '--update-secrets "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET='
        "${MACHINE_READINESS_EVIDENCE_SECRET}:latest,"
    ) in script
    assert "LIVE_API_SERVICE_JSON=$(gcloud run services describe caseops-api" in script
    assert 'str(metadata.get("generation")) != str(status.get("observedGeneration"))' in script
    assert "len(status_traffic) != 1" in script
    assert 'env.get("CASEOPS_RELEASE_SHA") or {}' in script
    assert 'env.get("CASEOPS_IP_RULE_GOVERNANCE_ENABLED") or {}' in script
    assert 'env.get("CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET")' in script
    assert 'str(machine_secret_ref.get("name")) != expected_machine_readiness_secret' in script
    assert 'str(machine_secret_ref.get("key")) != "latest"' in script
    assert "LIVE_API_REVISION_IMAGE=$(gcloud run revisions describe" in script
    assert '"${LIVE_API_REVISION_IMAGE}" != "${API_IMMUTABLE_IMAGE}"' in script


def test_deploy_prod_preserves_single_request_instances_with_scale_headroom() -> None:
    """A stalled request must leave a warm slot while handlers stay sync."""

    script = _read_repo_text("scripts/deploy-prod.sh")
    manifest = _read_repo_text("infra/cloudrun/api-service.yaml")
    runbook = _read_repo_text("docs/GCP_DEPLOY.md")

    assert "API_CONCURRENCY=1" in script
    assert 'API_MAX_INSTANCES="${API_MAX_INSTANCES:-20}"' in script
    assert '--max "${API_MAX_INSTANCES}"' in script
    assert '--max-instances "${API_MAX_INSTANCES}"' in script
    assert 'run.googleapis.com/minScale: "4"' in manifest
    assert "autoscaling.knative.dev/minScale" not in manifest
    assert 'autoscaling.knative.dev/maxScale: "20"' in manifest
    assert "--min=4" in runbook
    assert "--min-instances=default" in runbook
    assert "--min-instances=0" not in runbook


def _ignore_matches(ignore_text: str, relative_path: str) -> bool:
    """Evaluate the root-level canary subset used by these ignore files."""
    ignored = False
    for raw_pattern in ignore_text.splitlines():
        pattern = raw_pattern.strip()
        if not pattern or pattern.startswith("#"):
            continue
        negated = pattern.startswith("!")
        if negated:
            pattern = pattern[1:]
        if pattern.endswith("/"):
            directory = pattern.rstrip("/")
            matches = relative_path == directory or relative_path.startswith(f"{directory}/")
        else:
            matches = fnmatch.fnmatchcase(relative_path, pattern)
        if matches:
            ignored = not negated
    return ignored


@pytest.mark.parametrize("ignore_path", ["apps/api/.gcloudignore", "apps/api/.dockerignore"])
def test_api_build_context_excludes_secret_and_cache_canaries(ignore_path: str) -> None:
    ignore_text = _read_repo_text(ignore_path)

    excluded_canaries = {
        ".env",
        ".env.cloud",
        ".env.production.local",
        ".venv/Scripts/python.exe",
        ".uv-cache/archive-v0/package.whl",
        "__pycache__/settings.cpython-313.pyc",
        ".pytest_cache/v/cache/nodeids",
        ".pytest-tmp/session/data",
        ".mypy_cache/3.13/cache.json",
        ".ruff_cache/content",
    }
    for canary in excluded_canaries:
        assert _ignore_matches(ignore_text, canary), (
            f"{ignore_path} would include sensitive/cache canary {canary}"
        )

    assert not _ignore_matches(ignore_text, ".env.example")


@cache
def _find_working_bash() -> str:
    candidates: list[str | None]
    if os.name == "nt":
        git = shutil.which("git")
        discovered_git_bash = (
            str(Path(git).resolve().parents[1] / "bin" / "bash.exe") if git else None
        )
        candidates = [
            discovered_git_bash,
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            shutil.which("bash"),
        ]
    else:
        candidates = [shutil.which("bash")]
    for candidate in candidates:
        if not candidate or not Path(candidate).is_file():
            continue
        try:
            result = subprocess.run(
                [candidate, "--version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and "GNU bash" in result.stdout:
            return candidate
    return pytest.skip("GNU bash is unavailable")


def _bash_path(path: Path) -> str:
    resolved = path.resolve()
    if os.name != "nt":
        return resolved.as_posix()
    drive = resolved.drive.rstrip(":").lower()
    return f"/{drive}{resolved.as_posix()[2:]}"


def _write_fake_executable(path: Path, source: str) -> None:
    path.write_text(source, encoding="utf-8", newline="\n")
    path.chmod(0o755)


def _a0_fingerprint_json() -> str:
    datasets = {
        "ip_rule_sets": {
            "content_sha256": "1" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None},
        },
        "ip_rule_versions": {
            "content_sha256": "2" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {
                "activated_at": None,
                "created_at": None,
                "disabled_at": None,
                "fixtures_passed_at": None,
            },
        },
        "company_ip_rule_policies": {
            "content_sha256": "3" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None, "updated_at": None},
        },
        "audit_events_ip_rule_governance": {
            "content_sha256": "4" * 64,
            "count": 0,
            "max_timestamp": None,
            "max_timestamps": {"created_at": None},
        },
    }
    body = {
        "database_context": {
            "alembic_heads": ["20260813_0002"],
            "database_schema": "public",
            "dialect": "postgresql",
        },
        "datasets": datasets,
        "schema_version": 1,
        "scope": {
            "audit_filter": {
                "action_prefix": "ip.rule_version.",
                "match": "action_prefix_or_target_type",
                "target_types": [
                    "company_ip_rule_policy",
                    "ip_rule_set",
                    "ip_rule_version",
                ],
            },
            "datasets": [
                "ip_rule_sets",
                "ip_rule_versions",
                "company_ip_rule_policies",
                "audit_events_ip_rule_governance",
            ],
            "read_control": {
                "statement_timeout_ms": 60_000,
                "stream_batch_size": 500,
            },
        },
    }
    canonical = json.dumps(body, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    snapshot = {
        **body,
        "captured_at": "2026-08-14T16:00:00.000000Z",
        "overall_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
    }
    return json.dumps(snapshot, separators=(",", ":"), sort_keys=True)


def _a0_qa_job_json(
    image: str,
    generation: int,
    *,
    execution_count: int = 9,
    release_sha: str | None = None,
    latest_execution: str = "caseops-ip-qa-bootstrap-old",
) -> str:
    environment = [
        {
            "name": "CASEOPS_AUTO_MIGRATE",
            "value": "false",
        }
    ]
    if release_sha is not None:
        environment.append(
            {
                "name": "CASEOPS_QA_RELEASE_SHA",
                "value": release_sha,
            }
        )
    return json.dumps(
        {
            "metadata": {"generation": generation},
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "client.knative.dev/nonce": f"nonce-{generation}",
                            "run.googleapis.com/execution-environment": "gen2",
                            "run.googleapis.com/cloudsql-instances": (
                                "perfect-period-305406:asia-south1:caseops-db"
                            ),
                        }
                    },
                    "spec": {
                        "taskCount": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "args": [],
                                        "command": ["caseops-bootstrap-ip-production-qa"],
                                        "env": environment,
                                        "image": image,
                                    }
                                ],
                                "maxRetries": 0,
                                "serviceAccountName": (
                                    "caseops-runtime@perfect-period-305406.iam.gserviceaccount.com"
                                ),
                                "timeoutSeconds": 600,
                            }
                        },
                    },
                }
            },
            "status": {
                "conditions": [{"status": "True", "type": "Ready"}],
                "executionCount": execution_count,
                "latestCreatedExecution": {"name": latest_execution},
                "observedGeneration": generation,
            },
        },
        separators=(",", ":"),
    )


def _qa_execution_json(*, job_generation: int, succeeded: bool = True) -> str:
    return json.dumps(
        {
            "metadata": {
                "labels": {
                    "run.googleapis.com/job": "caseops-ip-qa-bootstrap",
                    "run.googleapis.com/jobGeneration": str(job_generation),
                },
                "name": (
                    "caseops-ip-qa-bootstrap-new"
                    if job_generation == 5
                    else "caseops-ip-qa-bootstrap-old"
                ),
            },
            "status": {
                "conditions": [
                    {
                        "status": "True" if succeeded else "False",
                        "type": "Completed",
                    }
                ]
            },
        },
        separators=(",", ":"),
    )


def _a0_fingerprint_job_json(image: str) -> str:
    return json.dumps(
        {
            "metadata": {
                "generation": 2,
                "labels": {
                    "caseops-control": "ip-rule-fingerprint",
                    "caseops-release": "abcdef1234567890abcdef1234567890abcdef12",
                },
            },
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {
                            "run.googleapis.com/cloudsql-instances": (
                                "perfect-period-305406:asia-south1:caseops-db"
                            )
                        }
                    },
                    "spec": {
                        "taskCount": 1,
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "args": [
                                            "-m",
                                            "caseops_api.scripts.ip_rule_governance_fingerprint",
                                        ],
                                        "command": ["python"],
                                        "env": [
                                            {"name": "CASEOPS_ENV", "value": "cloud"},
                                            {
                                                "name": "CASEOPS_AUTO_MIGRATE",
                                                "value": "false",
                                            },
                                            {
                                                "name": "CASEOPS_AUTH_SECRET",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "key": "latest",
                                                        "name": "caseops-auth-secret",
                                                    }
                                                },
                                            },
                                            {
                                                "name": "CASEOPS_DATABASE_URL",
                                                "valueFrom": {
                                                    "secretKeyRef": {
                                                        "key": "latest",
                                                        "name": "caseops-database-url",
                                                    }
                                                },
                                            },
                                        ],
                                        "image": image,
                                    }
                                ],
                                "maxRetries": 0,
                                "serviceAccountName": (
                                    "caseops-runtime@perfect-period-305406.iam.gserviceaccount.com"
                                ),
                                "timeoutSeconds": 600,
                            }
                        },
                    },
                }
            },
            "status": {
                "conditions": [{"status": "True", "type": "Ready"}],
                "observedGeneration": 2,
            },
        },
        separators=(",", ":"),
    )


def _a0_execution_json(
    image: str,
    *,
    succeeded: bool = True,
    expected_sha: str | None = None,
    execution_name: str = "caseops-ip-rule-governance-fingerprint-a0-test",
) -> str:
    arguments = ["-m", "caseops_api.scripts.ip_rule_governance_fingerprint"]
    if expected_sha is not None:
        arguments.append(f"--expect-sha256={expected_sha}")
    return json.dumps(
        {
            "metadata": {"name": execution_name},
            "spec": {
                "taskCount": 1,
                "template": {
                    "spec": {
                        "containers": [
                            {
                                "args": arguments,
                                "command": ["python"],
                                "image": image,
                            }
                        ]
                    }
                },
            },
            "status": {
                "completionTime": "2026-08-14T16:00:02Z",
                "conditions": [{"status": "True" if succeeded else "False", "type": "Completed"}],
                "failedCount": 0 if succeeded else 1,
                "startTime": "2026-08-14T16:00:01Z",
                "succeededCount": 1 if succeeded else 0,
            },
        },
        separators=(",", ":"),
    )


def _a0_pending_execution_json(image: str) -> str:
    value = json.loads(_a0_execution_json(image))
    value["status"] = {
        "conditions": [{"status": "Unknown", "type": "Completed"}],
        "startTime": "2026-08-14T16:00:01Z",
    }
    return json.dumps(value, separators=(",", ":"))


def _run_deploy_with_fakes(
    tmp_path: Path,
    *arguments: str,
    git_status: str = "",
    curl_mode: str = "ok",
    traffic_mode: str = "ok",
    expected_tag: str = "abcdef1",
    a0_mode: str | None = None,
    gh_mode: str = "ok",
    index_health_mode: str = "ok",
    qa_execution_drift: bool = False,
    qa_already_completed: bool = False,
    qa_already_failed: bool = False,
    migration_timeout_drift: bool = False,
    python_crlf: bool = False,
    main_drift_after_fetches: int | None = None,
    private_projection_scheduler_hold: str | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    gcloud_log = tmp_path / "gcloud.log"

    _write_fake_executable(
        fake_bin / "git",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == "fetch" ]]; then
  fetch_count=0
  if [[ -f "${FAKE_GIT_FETCH_COUNT}" ]]; then
    fetch_count=$(cat "${FAKE_GIT_FETCH_COUNT}")
  fi
  fetch_count=$((fetch_count + 1))
  printf '%s\n' "${fetch_count}" > "${FAKE_GIT_FETCH_COUNT}"
  exit 0
fi
if [[ "$1" == "status" ]]; then
  if [[ -n "${FAKE_GIT_STATUS:-}" ]]; then
    printf '%s\n' "${FAKE_GIT_STATUS}"
  fi
  exit 0
fi
if [[ "$1" == "rev-parse" && "$*" == *"--short=7"* ]]; then
  printf '%s\n' "abcdef1"
  exit 0
fi
if [[ "$1" == "rev-parse" && "$*" == *"1111111"* ]]; then
  printf '%s\n' "1111111111111111111111111111111111111111"
  exit 0
fi
if [[ "$1" == "rev-parse" && "$*" == *"refs/remotes/origin/main"* ]]; then
  fetch_count=0
  if [[ -f "${FAKE_GIT_FETCH_COUNT}" ]]; then
    fetch_count=$(cat "${FAKE_GIT_FETCH_COUNT}")
  fi
  if [[ "${FAKE_MAIN_DRIFT_AFTER_FETCHES}" -gt 0 && \
    "${fetch_count}" -ge "${FAKE_MAIN_DRIFT_AFTER_FETCHES}" ]]; then
    printf '%s\n' "dddddddddddddddddddddddddddddddddddddddd"
  else
    printf '%s\n' "abcdef1234567890abcdef1234567890abcdef12"
  fi
  exit 0
fi
if [[ "$1" == "rev-parse" ]]; then
  printf '%s\n' "abcdef1234567890abcdef1234567890abcdef12"
  exit 0
fi
exit 91
""",
    )
    _write_fake_executable(
        fake_bin / "gcloud",
        """#!/usr/bin/env bash
set -euo pipefail
for argument in "$@"; do
  if [[ "${argument}" == caseops-ip-qa-bootstrap-* && \
    "${argument}" == *$'\\r'* ]]; then
    printf 'carriage return reached QA execution name: %q\n' "${argument}" >&2
    exit 97
  fi
done
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"run jobs execute caseops-db-index-health"* && \
  "${FAKE_INDEX_HEALTH_MODE}" == "fail" ]]; then
  exit 56
elif [[ "$*" == *"artifacts docker images describe"* ]]; then
  printf '%s\n' 'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
elif [[ "$*" == *"run jobs describe caseops-migrate-job"* && "$*" == *"--format=json"* ]]; then
  printf '%s\n' "${FAKE_MIGRATION_JOB_JSON}"
elif [[ "$*" == *"run jobs update caseops-ip-qa-bootstrap"* ]]; then
  touch "${FAKE_QA_UPDATED}"
elif [[ "$*" == *"run jobs execute caseops-ip-qa-bootstrap"* ]]; then
  touch "${FAKE_QA_EXECUTED}"
elif [[ "$*" == *"run jobs describe caseops-ip-qa-bootstrap"* && "$*" == *"--format=json"* ]]; then
  if [[ -f "${FAKE_QA_EXECUTED}" ]]; then
    printf '%s\n' "${FAKE_QA_EXECUTED_JSON}"
  elif [[ -f "${FAKE_QA_UPDATED}" ]]; then
    printf '%s\n' "${FAKE_QA_AFTER_JSON}"
  else
    printf '%s\n' "${FAKE_QA_BEFORE_JSON}"
  fi
elif [[ "$*" == *"run jobs executions describe caseops-ip-qa-bootstrap-new"* ]]; then
  printf '%s\n' "${FAKE_QA_NEW_EXECUTION_JSON}"
elif [[ "$*" == *"run jobs executions describe caseops-ip-qa-bootstrap-old"* ]]; then
  printf '%s\n' "${FAKE_QA_OLD_EXECUTION_JSON}"
elif [[ "$*" == *"run jobs executions list"* ]]; then
  printf '%s\n' "${FAKE_EXECUTIONS_JSON}"
elif [[ "$*" == *"run jobs describe caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JOB_JSON}"
elif [[ "$*" == *"run jobs execute caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' '{"metadata":{"name":"caseops-ip-rule-governance-fingerprint-a0-test"}}'
elif [[ "$*" == *"run jobs executions describe"* && \
  "$*" == *"caseops-ip-rule-governance-fingerprint-a0-test"* ]]; then
  if [[ "${FAKE_A0_MODE}" == pending-structured* && \
    ! -f "${FAKE_EXECUTION_POLLED}" ]]; then
    touch "${FAKE_EXECUTION_POLLED}"
    printf '%s\n' "${FAKE_PENDING_EXECUTION_JSON}"
  else
    printf '%s\n' "${FAKE_EXECUTION_JSON}"
  fi
elif [[ "$*" == *"logging read"* && "$*" == *"stdout"* ]]; then
  if [[ "${FAKE_A0_MODE}" == "pending-structured-timeout" ]]; then
    exit 124
  elif [[ "${FAKE_A0_MODE}" == "pending-structured-empty" ]]; then
    printf '%s\n' '[]'
    exit 0
  fi
  printf '%s\n' "${FAKE_FINGERPRINT_LOG_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stderr"* ]]; then
  printf ''
elif [[ "$*" == *"auth print-access-token"* ]]; then
  printf '%s\n' 'fake-access-token'
elif [[ "$*" == *"run jobs describe"* ]]; then
  printf '%s%s\n' \
    'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"--format=json"* ]]; then
  FAKE_TRAFFIC_REVISION='caseops-api-test'
  FAKE_TRAFFIC_LATEST='true'
  FAKE_OBSERVED_GENERATION='2'
  FAKE_GOVERNANCE_FLAG='false'
  FAKE_MACHINE_SECRET='caseops-machine-readiness-evidence-secret'
  FAKE_LLM_PROVIDER='openai'
  FAKE_LLM_SECRET='caseops-openai-api-key'
  FAKE_SERVICE_MIN='4'
  if [[ "${FAKE_TRAFFIC_MODE}" == "drift" ]]; then
    FAKE_TRAFFIC_REVISION='caseops-api-old'
    FAKE_TRAFFIC_LATEST='false'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "generation-drift" ]]; then
    FAKE_OBSERVED_GENERATION='1'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "flag-enabled" ]]; then
    FAKE_GOVERNANCE_FLAG='true'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "capacity-drift" ]]; then
    FAKE_SERVICE_MIN='1'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "secret-drift" ]]; then
    FAKE_MACHINE_SECRET='wrong-machine-readiness-secret'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "llm-provider-drift" ]]; then
    FAKE_LLM_PROVIDER='mock'
  elif [[ "${FAKE_TRAFFIC_MODE}" == "llm-secret-drift" ]]; then
    FAKE_LLM_SECRET='wrong-llm-secret'
  fi
  printf '%s' \
    '{"metadata":{"generation":2,"annotations":{' \
    '"run.googleapis.com/minScale":"' "${FAKE_SERVICE_MIN}" '"}},' \
    '"spec":{"traffic":[{"latestRevision":true,"percent":100}],' \
    '"template":{"spec":{"containers":[{"name":"api","env":[' \
    '{"name":"CASEOPS_RELEASE_SHA",' \
    '"value":"abcdef1234567890abcdef1234567890abcdef12"},' \
    '{"name":"CASEOPS_IP_RULE_GOVERNANCE_ENABLED","value":"' \
    "${FAKE_GOVERNANCE_FLAG}" '"},' \
    '{"name":"CASEOPS_LLM_PROVIDER","value":"' "${FAKE_LLM_PROVIDER}" '"},' \
    '{"name":"CASEOPS_LLM_MODEL","value":"gpt-5.1"},' \
    '{"name":"CASEOPS_LLM_MODEL_RECOMMENDATIONS","value":"gpt-5-mini"},' \
    '{"name":"CASEOPS_PAID_PROVIDER_BLOCKED_COMPANY_SLUGS",' \
    '"value":"caseops-qa;caseops-ip-qa;test-legal"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_ENABLED","value":"true"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_API_BASE_URL",' \
    '"value":"https://api.indiankanoon.org"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_TERMS_OWNER",' \
    '"value":"Orchestrum Technologies LLP"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_TERMS_APPROVED_AT",' \
    '"value":"2026-09-03T00:00:00Z"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_TERMS_EXPIRES_AT",' \
    '"value":"2027-09-03T00:00:00Z"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_PERMITTED_USES",' \
    '"value":"search,document_display,research_storage"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_DAILY_BUDGET_MINOR","value":"2500"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_MONTHLY_BUDGET_MINOR","value":"50000"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_RETENTION_DAYS","value":"30"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_MAX_SEARCH_PAGE","value":"2"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_MAX_RESULTS","value":"10"},' \
    '{"name":"CASEOPS_INDIAN_KANOON_API_TOKEN",' \
    '"valueFrom":{"secretKeyRef":{"key":"latest",' \
    '"name":"caseops-indian-kanoon-api-token"}}},' \
    '{"name":"CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET",' \
    '"valueFrom":{"secretKeyRef":{"key":"latest","name":"' \
    "${FAKE_MACHINE_SECRET}" '"}}},' \
    '{"name":"CASEOPS_LLM_API_KEY",' \
    '"valueFrom":{"secretKeyRef":{"key":"latest","name":"' \
    "${FAKE_LLM_SECRET}" '"}}}' \
    ']}]}}},' \
    '"status":{"observedGeneration":' "${FAKE_OBSERVED_GENERATION}" ',' \
    '"latestCreatedRevisionName":"caseops-api-test",' \
    '"latestReadyRevisionName":"caseops-api-test","conditions":[' \
    '{"type":"Ready","status":"True"},' \
    '{"type":"ConfigurationsReady","status":"True"},' \
    '{"type":"RoutesReady","status":"True"}],"traffic":[' \
    '{"revisionName":"' "${FAKE_TRAFFIC_REVISION}" '",' \
    '"latestRevision":' "${FAKE_TRAFFIC_LATEST}" ',"percent":100}]}}'
  printf '\n'
elif [[ "$*" == *"run revisions describe"* ]]; then
  if [[ "${FAKE_TRAFFIC_MODE}" == "image-drift" ]]; then
    printf '%s%s\n' \
      'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
      'bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb'
  else
    printf '%s%s\n' \
      'asia-south1-docker.pkg.dev/perfect-period-305406/caseops-images/caseops-api@sha256:' \
      'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  fi
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[0].image"* ]]; then
  printf 'registry.invalid/caseops-api:%s\n' "${FAKE_TAG}"
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[1].image"* ]]; then
  printf 'clamav/clamav:1.4\n'
elif [[ "$*" == *"services describe caseops-web"* ]]; then
  printf 'registry.invalid/caseops-web:%s\n' "${FAKE_TAG}"
elif [[ "$*" == *"services describe caseops-api"* && "$*" == *"containers[].name"* ]]; then
  printf 'api;clamav\n'
elif [[ "$*" == *"services describe caseops-api"* && \
  "$*" == *"startupProbe.initialDelaySeconds"* ]]; then
  printf ''
elif [[ "$*" == *"services describe caseops-api"* && \
  "$*" == *"startupProbe.periodSeconds"* ]]; then
  printf '2\n'
fi
""",
    )
    _write_fake_executable(
        fake_bin / "gh",
        """#!/usr/bin/env bash
set -euo pipefail
printf 'gh %s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "${FAKE_GH_MODE}" == "fail" ]]; then
  exit 55
fi
""",
    )
    _write_fake_executable(
        fake_bin / "curl",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"logging.googleapis.com/v2/entries:list"* ]]; then
  request_found=false
  for argument in "$@"; do
    candidate="${argument#@}"
    if [[ "${candidate}" != "${argument}" && -f "${candidate}" ]] && \
      grep -q '"resourceNames"' "${candidate}"; then
      request_found=true
      grep -q '"orderBy":"timestamp desc"' "${candidate}"
    fi
  done
  [[ "${request_found}" == "true" ]]
  printf '%s\n' "${FAKE_FINGERPRINT_REST_JSON}"
  exit 0
fi
case "${FAKE_CURL_MODE}" in
  network-fail) exit 22 ;;
  degraded) printf '%s\n' '{"status":"degraded"}' ;;
  *) printf '%s\n' '{"status":"ok"}' ;;
esac
""",
    )
    _write_fake_executable(
        fake_bin / "sleep",
        """#!/usr/bin/env bash
exit 0
""",
    )
    _write_fake_executable(
        fake_bin / "python",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "scripts/scheduler_inventory.py" || \
      "${1:-}" == "scripts/reconcile_monitoring_alerts.py" ]]; then
  printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
  exit 0
fi
if [[ "${FAKE_PYTHON_CRLF}" == "true" ]]; then
  set +e
  "${FAKE_REAL_PYTHON}" "$@" | sed $'s/$/\\r/'
  python_status=${PIPESTATUS[0]}
  set -e
  exit "${python_status}"
fi
exec "${FAKE_REAL_PYTHON}" "$@"
""",
    )

    immutable_image = (
        "asia-south1-docker.pkg.dev/perfect-period-305406/"
        "caseops-images/caseops-api@sha256:" + "a" * 64
    )
    release_sha = "abcdef1234567890abcdef1234567890abcdef12"
    env = os.environ.copy()
    fingerprint_json = _a0_fingerprint_json()
    fingerprint_log_json = json.dumps(
        [
            {
                (
                    "jsonPayload"
                    if (a0_mode or "").startswith("pending-structured")
                    else "textPayload"
                ): (
                    json.loads(fingerprint_json)
                    if (a0_mode or "").startswith("pending-structured")
                    else fingerprint_json
                )
            }
        ],
        separators=(",", ":"),
    )
    migration_job_json = json.dumps(
        {
            "spec": {
                "template": {
                    "spec": {
                        "template": {
                            "spec": {
                                "containers": [
                                    {
                                        "env": [
                                            {
                                                "name": (
                                                    "CASEOPS_MIGRATION_DB_CONNECT_TIMEOUT_SECONDS"
                                                ),
                                                "value": "10",
                                            },
                                            {
                                                "name": (
                                                    "CASEOPS_MIGRATION_DB_STATEMENT_TIMEOUT_MS"
                                                ),
                                                "value": "900000",
                                            },
                                            {
                                                "name": ("CASEOPS_MIGRATION_DB_LOCK_TIMEOUT_MS"),
                                                "value": (
                                                    "0" if migration_timeout_drift else "5000"
                                                ),
                                            },
                                            {
                                                "name": (
                                                    "CASEOPS_MIGRATION_DB_IDLE_"
                                                    "TRANSACTION_TIMEOUT_MS"
                                                ),
                                                "value": "60000",
                                            },
                                        ]
                                    }
                                ]
                            }
                        }
                    }
                }
            }
        },
        separators=(",", ":"),
    )
    env.update(
        {
            "FAKE_A0_MODE": a0_mode or "",
            "FAKE_CURL_MODE": curl_mode,
            "FAKE_EXECUTION_JSON": _a0_execution_json(
                immutable_image,
                succeeded=a0_mode != "fingerprint-fail",
            ),
            "FAKE_EXECUTION_POLLED": _bash_path(tmp_path / "execution-polled"),
            "FAKE_EXECUTIONS_JSON": json.dumps(
                [
                    {
                        "metadata": {
                            "name": (
                                "running-execution"
                                if a0_mode == "nonterminal"
                                else "historical-failure"
                            )
                        },
                        "status": {
                            "conditions": [
                                {
                                    "status": "True" if a0_mode == "nonterminal" else "False",
                                    "type": (
                                        "Started" if a0_mode == "nonterminal" else "Completed"
                                    ),
                                }
                            ]
                        },
                    }
                ],
                separators=(",", ":"),
            ),
            "FAKE_FINGERPRINT_JOB_JSON": _a0_fingerprint_job_json(immutable_image),
            "FAKE_FINGERPRINT_LOG_JSON": fingerprint_log_json,
            "FAKE_MIGRATION_JOB_JSON": migration_job_json,
            "FAKE_FINGERPRINT_REST_JSON": json.dumps(
                {"entries": [{"jsonPayload": json.loads(fingerprint_json)}]},
                separators=(",", ":"),
            ),
            "FAKE_GCLOUD_LOG": _bash_path(gcloud_log),
            "FAKE_GIT_FETCH_COUNT": _bash_path(tmp_path / "git-fetch-count"),
            "FAKE_GIT_STATUS": git_status,
            "FAKE_MAIN_DRIFT_AFTER_FETCHES": str(main_drift_after_fetches or 0),
            "FAKE_GH_MODE": gh_mode,
            "FAKE_INDEX_HEALTH_MODE": index_health_mode,
            "FAKE_QA_AFTER_JSON": _a0_qa_job_json(
                immutable_image,
                5,
                execution_count=(
                    10
                    if a0_mode == "qa-executed"
                    or qa_execution_drift
                    or qa_already_completed
                    or qa_already_failed
                    else 9
                ),
                release_sha=release_sha,
                latest_execution=(
                    "caseops-ip-qa-bootstrap-new"
                    if qa_already_completed or qa_already_failed
                    else "caseops-ip-qa-bootstrap-old"
                ),
            ),
            "FAKE_QA_BEFORE_JSON": _a0_qa_job_json(
                immutable_image
                if qa_already_completed or qa_already_failed
                else "registry.invalid/caseops-api:old",
                5 if qa_already_completed or qa_already_failed else 4,
                execution_count=(10 if qa_already_completed or qa_already_failed else 9),
                release_sha=(release_sha if qa_already_completed or qa_already_failed else None),
                latest_execution=(
                    "caseops-ip-qa-bootstrap-new"
                    if qa_already_completed or qa_already_failed
                    else "caseops-ip-qa-bootstrap-old"
                ),
            ),
            "FAKE_QA_EXECUTED": _bash_path(tmp_path / "qa-executed"),
            "FAKE_QA_EXECUTED_JSON": _a0_qa_job_json(
                immutable_image,
                5,
                execution_count=10,
                release_sha=release_sha,
                latest_execution="caseops-ip-qa-bootstrap-new",
            ),
            "FAKE_QA_NEW_EXECUTION_JSON": _qa_execution_json(
                job_generation=5,
                succeeded=not qa_already_failed,
            ),
            "FAKE_QA_OLD_EXECUTION_JSON": _qa_execution_json(job_generation=4),
            "FAKE_QA_UPDATED": _bash_path(tmp_path / "qa-updated"),
            "FAKE_PENDING_EXECUTION_JSON": _a0_pending_execution_json(immutable_image),
            "FAKE_PYTHON_CRLF": "true" if python_crlf else "false",
            "FAKE_REAL_PYTHON": _bash_path(Path(sys.executable)),
            "FAKE_TAG": expected_tag,
            "FAKE_TRAFFIC_MODE": traffic_mode,
        }
    )
    if a0_mode is not None:
        env.update(
            {
                "CASEOPS_A0_CAPTURE_RULE_GOVERNANCE_BASELINE": "true",
                "CASEOPS_A0_RULE_GOVERNANCE_BASELINE_OUTPUT": _bash_path(
                    tmp_path / "a0-baseline.json"
                ),
            }
        )
    if private_projection_scheduler_hold is not None:
        env["CASEOPS_PRIVATE_PROJECTION_SCHEDULER_HOLD"] = private_projection_scheduler_hold
    command = [
        _find_working_bash(),
        "-c",
        'export PATH="$1:$PATH"; shift; bash scripts/deploy-prod.sh "$@"',
        "deploy-test",
        _bash_path(fake_bin),
        *arguments,
    ]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )


def _run_fingerprint_wrapper_mismatch(tmp_path: Path) -> subprocess.CompletedProcess[str]:
    fake_bin = tmp_path / "wrapper-fake-bin"
    fake_bin.mkdir()
    gcloud_log = tmp_path / "wrapper-gcloud.log"
    image = (
        "asia-south1-docker.pkg.dev/perfect-period-305406/"
        "caseops-images/caseops-api@sha256:" + "a" * 64
    )
    expected_sha = "f" * 64
    _write_fake_executable(
        fake_bin / "gcloud",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "${FAKE_GCLOUD_LOG}"
if [[ "$*" == *"run jobs describe caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JOB_JSON}"
elif [[ "$*" == *"run jobs execute caseops-ip-rule-governance-fingerprint-a0"* ]]; then
  printf '%s\n' '{"metadata":{"name":"caseops-ip-rule-governance-fingerprint-a0-mismatch"}}'
elif [[ "$*" == *"run jobs executions describe"* && \
  "$*" == *"caseops-ip-rule-governance-fingerprint-a0-mismatch"* ]]; then
  printf '%s\n' "${FAKE_EXECUTION_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stdout"* ]]; then
  printf '%s\n' "${FAKE_FINGERPRINT_JSON}"
elif [[ "$*" == *"logging read"* && "$*" == *"stderr"* ]]; then
  printf ''
fi
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "FAKE_EXECUTION_JSON": _a0_execution_json(
                image,
                expected_sha=expected_sha,
                execution_name="caseops-ip-rule-governance-fingerprint-a0-mismatch",
            ),
            "FAKE_FINGERPRINT_JOB_JSON": _a0_fingerprint_job_json(image),
            "FAKE_FINGERPRINT_JSON": _a0_fingerprint_json(),
            "FAKE_GCLOUD_LOG": _bash_path(gcloud_log),
        }
    )
    return subprocess.run(
        [
            _find_working_bash(),
            "-c",
            (
                'export PATH="$1:$PATH"; '
                'bash scripts/ip-rule-governance-fingerprint-job.sh execute "$2" "$3"'
            ),
            "wrapper-test",
            _bash_path(fake_bin),
            image,
            expected_sha,
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        check=False,
        text=True,
        timeout=90,
    )


def test_deploy_prod_rejects_a_requested_commit_that_is_not_head(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(tmp_path, "1111111", expected_tag="1111111")

    assert result.returncode != 0
    assert "does not match current HEAD" in result.stdout
    assert not (tmp_path / "gcloud.log").exists()


def test_deploy_prod_rejects_dirty_build_context_before_gcloud(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        git_status=" M apps/api/src/caseops_api/main.py",
    )

    assert result.returncode != 0
    assert "build context is dirty" in result.stdout
    assert not (tmp_path / "gcloud.log").exists()


def test_deploy_prod_accepts_clean_head_and_healthy_api(tmp_path: Path) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DONE abcdef1" in result.stdout
    assert (tmp_path / "gcloud.log").is_file()
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()

    def call_index(fragment: str) -> int:
        return next(index for index, call in enumerate(calls) if fragment in call)

    assert call_index("run jobs execute caseops-db-index-health") < call_index(
        "run jobs update caseops-ip-qa-bootstrap"
    )
    assert call_index("run jobs update caseops-ip-qa-bootstrap") < call_index(
        "run deploy caseops-api"
    )
    assert call_index("run deploy caseops-web") < call_index(
        "run jobs execute caseops-ip-qa-bootstrap"
    )
    assert call_index("run jobs execute caseops-ip-qa-bootstrap") < call_index(
        "gh workflow run prod-verify.yml"
    )
    assert sum("run jobs execute caseops-ip-qa-bootstrap" in call for call in calls) == 1
    assert any(
        "run jobs update caseops-ip-qa-bootstrap" in call
        and "--update-env-vars CASEOPS_QA_RELEASE_SHA=abcdef1234567890abcdef1234567890abcdef12"
        in call
        for call in calls
    )
    assert any(
        "run deploy caseops-api" in call
        and "--update-secrets "
        "CASEOPS_MACHINE_READINESS_EVIDENCE_SECRET="
        "caseops-machine-readiness-evidence-secret:latest"
        in call
        for call in calls
    )
    assert any(
        "run deploy caseops-api" in call
        and "CASEOPS_LLM_API_KEY=caseops-openai-api-key:latest" in call
        and "CASEOPS_LLM_PROVIDER=openai" in call
        and "CASEOPS_LLM_MODEL=gpt-5.1" in call
        and "CASEOPS_LLM_MODEL_RECOMMENDATIONS=gpt-5-mini" in call
        for call in calls
    )
    assert any(
        "run jobs update caseops-seed-indian-kanoon-costs" in call
        and "caseops_api.scripts.seed_indian_kanoon_costs" in call
        for call in calls
    )
    assert any("run jobs execute caseops-seed-indian-kanoon-costs" in call for call in calls)
    assert any(
        "run deploy caseops-api" in call
        and "CASEOPS_INDIAN_KANOON_API_TOKEN=caseops-indian-kanoon-api-token:latest" in call
        and "CASEOPS_INDIAN_KANOON_ENABLED=true" in call
        for call in calls
    )
    assert (
        "gh workflow run prod-verify.yml --repo mishrasanjeev/caseops --ref main "
        "-f expected_release_sha=abcdef1234567890abcdef1234567890abcdef12"
    ) in "\n".join(calls)


def test_deploy_prod_keeps_private_projection_scheduler_paused_during_incident(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        private_projection_scheduler_hold="true",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "private projection scheduler remains paused" in result.stdout
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    assert any(
        "scheduler_inventory.py reconcile" in call
        and "--hold-scheduler-paused caseops-private-projection-maintenance-cadence" in call
        for call in calls
    )


def test_deploy_prod_rejects_invalid_private_projection_scheduler_hold(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        private_projection_scheduler_hold="yes",
    )

    assert result.returncode == 2
    assert "CASEOPS_PRIVATE_PROJECTION_SCHEDULER_HOLD must be true or false" in result.stdout
    assert not (tmp_path / "gcloud.log").exists()


@pytest.mark.parametrize(
    ("drift_after_fetches", "required_call", "forbidden_call", "phase"),
    [
        (1, None, None, "release preflight"),
        (
            2,
            "builds submit",
            "run jobs update caseops-migrate-job",
            "post-build pre-migration gate",
        ),
        (
            3,
            "run jobs update caseops-ip-qa-bootstrap",
            "run deploy caseops-api",
            "final pre-route gate",
        ),
        (
            4,
            "run deploy caseops-web",
            "run jobs execute caseops-ip-qa-bootstrap",
            "post-route pre-certification gate",
        ),
    ],
)
def test_deploy_prod_fails_closed_when_main_advances_during_release(
    tmp_path: Path,
    drift_after_fetches: int,
    required_call: str | None,
    forbidden_call: str | None,
    phase: str,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        main_drift_after_fetches=drift_after_fetches,
    )

    assert result.returncode != 0
    assert f"main advanced during release at {phase}" in result.stdout
    assert "dddddddddddddddddddddddddddddddddddddddd" in result.stdout
    calls = (
        (tmp_path / "gcloud.log").read_text(encoding="utf-8")
        if (tmp_path / "gcloud.log").exists()
        else ""
    )
    if required_call is not None:
        assert required_call in calls
    if forbidden_call is not None:
        assert forbidden_call not in calls
    assert "gh workflow run prod-verify.yml" not in calls
    assert "=== deploy-prod.sh — DONE" not in result.stdout


def test_deploy_prod_does_not_repeat_a_successful_current_generation_qa_bootstrap(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", qa_already_completed=True)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    assert not any("run jobs execute caseops-ip-qa-bootstrap" in call for call in calls)
    assert "no second execution" in result.stdout
    assert any("gh workflow run prod-verify.yml" in call for call in calls)


def test_deploy_prod_normalizes_windows_crlf_before_qa_execution_arguments(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", python_crlf=True)

    assert result.returncode == 0, result.stdout + result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    assert sum("run jobs execute caseops-ip-qa-bootstrap" in call for call in calls) == 1
    assert any("run jobs executions describe caseops-ip-qa-bootstrap-old" in call for call in calls)
    assert any("run jobs executions describe caseops-ip-qa-bootstrap-new" in call for call in calls)


def test_deploy_prod_refuses_to_retry_a_failed_current_generation_qa_bootstrap(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", qa_already_failed=True)

    assert result.returncode != 0
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    assert not any("run jobs execute caseops-ip-qa-bootstrap" in call for call in calls)
    assert not any("gh workflow run prod-verify.yml" in call for call in calls)
    assert "refusing an automatic retry" in result.stdout


def test_deploy_prod_refuses_migration_timeout_drift_before_execution(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, migration_timeout_drift=True)

    assert result.returncode != 0
    assert "caseops-migrate-job database timeout drift" in result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8")
    assert "run jobs update caseops-migrate-job" in calls
    assert "run jobs describe caseops-migrate-job" in calls
    assert "run jobs execute caseops-migrate-job" not in calls


def test_deploy_prod_fails_before_routing_if_qa_repin_executes_the_job(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        qa_execution_drift=True,
    )

    assert result.returncode != 0, result.stdout + result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8")
    assert "run jobs update caseops-ip-qa-bootstrap" in calls
    assert "run deploy caseops-api" not in calls
    assert "DONE abcdef1" not in result.stdout


def test_deploy_prod_fails_if_exact_release_verification_cannot_be_dispatched(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", gh_mode="fail")

    assert result.returncode != 0
    assert "DONE abcdef1" not in result.stdout


def test_deploy_prod_fails_before_routing_on_database_index_health_failure(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", index_health_mode="fail")

    assert result.returncode != 0
    assert "DONE abcdef1" not in result.stdout
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8")
    assert "run jobs execute caseops-db-index-health" in calls
    assert "run deploy caseops-api" not in calls


def test_a0_deploy_captures_final_pre_route_baseline_in_fail_closed_order(
    tmp_path: Path,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", a0_mode="ok")

    assert result.returncode == 0, result.stdout + result.stderr
    baseline = json.loads((tmp_path / "a0-baseline.json").read_text(encoding="utf-8"))
    assert len(baseline["overall_sha256"]) == 64
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()

    def call_index(fragment: str) -> int:
        return next(index for index, call in enumerate(calls) if fragment in call)

    assert call_index("run jobs execute caseops-migrate-job") < call_index(
        "scheduler_inventory.py reconcile"
    )
    assert call_index("scheduler_inventory.py reconcile") < call_index(
        "reconcile_monitoring_alerts.py reconcile"
    )
    assert call_index("reconcile_monitoring_alerts.py reconcile") < call_index(
        "run jobs execute caseops-db-index-health"
    )
    assert call_index("run jobs execute caseops-db-index-health") < call_index(
        "run jobs update caseops-ip-qa-bootstrap"
    )
    assert call_index("run jobs update caseops-ip-qa-bootstrap") < call_index(
        "run jobs executions list"
    )
    assert call_index("run jobs executions list") < call_index(
        "run jobs execute caseops-ip-rule-governance-fingerprint-a0"
    )
    assert call_index("run jobs execute caseops-ip-rule-governance-fingerprint-a0") < call_index(
        "run deploy caseops-api"
    )
    assert sum("run jobs executions list" in call for call in calls) == 1


@pytest.mark.parametrize(
    "a0_mode",
    ["pending-structured-empty", "pending-structured-timeout"],
)
def test_a0_fingerprint_waits_for_terminal_status_and_reads_structured_log(
    tmp_path: Path,
    a0_mode: str,
) -> None:
    result = _run_deploy_with_fakes(
        tmp_path,
        "abcdef1",
        a0_mode=a0_mode,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    baseline = json.loads((tmp_path / "a0-baseline.json").read_text(encoding="utf-8"))
    assert baseline["schema_version"] == 1
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8").splitlines()
    execution_describes = [
        call
        for call in calls
        if "run jobs executions describe caseops-ip-rule-governance-fingerprint-a0-test" in call
    ]
    assert len(execution_describes) == 2
    assert any(
        "logging read" in call and "--order desc" in call and "--format=json" in call
        for call in calls
    )
    assert any("auth print-access-token" in call for call in calls)
    assert any("logging.googleapis.com/v2/entries:list" in call for call in calls)


@pytest.mark.parametrize(
    "a0_mode",
    ["qa-executed", "nonterminal", "fingerprint-fail"],
)
def test_a0_deploy_does_not_route_when_pre_route_control_fails(
    tmp_path: Path,
    a0_mode: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, "abcdef1", a0_mode=a0_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    calls = (tmp_path / "gcloud.log").read_text(encoding="utf-8")
    assert "run deploy caseops-api" not in calls
    assert not (tmp_path / "a0-baseline.json").exists()


def test_fingerprint_wrapper_fails_on_local_expected_digest_mismatch(
    tmp_path: Path,
) -> None:
    result = _run_fingerprint_wrapper_mismatch(tmp_path)

    assert result.returncode != 0
    assert "did not match the expected overall SHA-256" in result.stderr
    calls = (tmp_path / "wrapper-gcloud.log").read_text(encoding="utf-8")
    assert (
        "run jobs executions describe caseops-ip-rule-governance-fingerprint-a0-mismatch" in calls
    )
    assert 'execution_name"="caseops-ip-rule-governance-fingerprint-a0-mismatch' in calls


@pytest.mark.parametrize(
    ("traffic_mode", "expected_message"),
    [
        ("drift", "TRAFFIC/REVISION DRIFT"),
        ("generation-drift", "TRAFFIC/REVISION DRIFT"),
        ("flag-enabled", "TRAFFIC/REVISION DRIFT"),
        ("capacity-drift", "TRAFFIC/REVISION DRIFT"),
        ("secret-drift", "TRAFFIC/REVISION DRIFT"),
        ("llm-provider-drift", "TRAFFIC/REVISION DRIFT"),
        ("llm-secret-drift", "TRAFFIC/REVISION DRIFT"),
        ("image-drift", "REVISION IMAGE DRIFT"),
    ],
)
def test_deploy_prod_fails_closed_on_api_traffic_or_config_drift(
    tmp_path: Path,
    traffic_mode: str,
    expected_message: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, traffic_mode=traffic_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_message in result.stdout
    assert "DONE abcdef1" not in result.stdout


@pytest.mark.parametrize(
    ("curl_mode", "expected_message"),
    [
        ("network-fail", "API health request failed"),
        ("degraded", "API health response is not healthy"),
    ],
)
def test_deploy_prod_fails_closed_on_unhealthy_api(
    tmp_path: Path,
    curl_mode: str,
    expected_message: str,
) -> None:
    result = _run_deploy_with_fakes(tmp_path, curl_mode=curl_mode)

    assert result.returncode != 0, result.stdout + result.stderr
    assert expected_message in result.stdout
    assert "=== deploy-prod.sh — DONE" not in result.stdout
