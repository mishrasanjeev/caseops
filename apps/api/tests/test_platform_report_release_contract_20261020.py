from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_report_browser_discovery_is_inherited_by_docker_and_mobile() -> None:
    config = (ROOT / "playwright.app.config.ts").read_text(encoding="utf-8")
    matcher = r"/platform-report-admin-\d{4}-\d{2}-\d{2}\.spec\.ts$/"
    assert config.count(matcher) == 2
    mobile = config.split('name: "app-mobile"', 1)[1].split("webServer:", 1)[0]
    assert matcher in mobile
    assert r'grep: /\[mobile\]/' in mobile
    docker = (ROOT / "playwright.docker.config.ts").read_text(encoding="utf-8")
    assert 'from "./playwright.app.config"' in docker
    assert "...appConfig" in docker


def test_report_prod_checks_are_serving_owned_read_only_and_native_captured() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/prod-verify.yml").read_text(encoding="utf-8")
    )
    steps = workflow["jobs"]["prod-playwright-shards"]["steps"]
    guard = next(step for step in steps if step.get("id") == "platform-report-prerequisites")
    assert "matrix.suite == 'public-pages'" in guard["if"]
    assert "-f tests/e2e/platform-report-admin-2026-10-20.prod.spec.ts" in guard["run"]
    assert 'echo "ready=false"' in guard["run"]
    replay = next(
        step for step in steps
        if step.get("name") == "Run exact-release report-console read-only acceptance"
    )
    assert "steps.platform-report-prerequisites.outputs.ready == 'true'" in replay["if"]
    assert "needs.resolve-release.outputs.release_sha" in replay["env"][
        "CASEOPS_EXPECTED_RELEASE_SHA"
    ]
    assert "secrets." not in str(replay)
    assert "caseops-prod-playwright\" platform-reports" in replay["run"]
    assert "--project=platform-reports-prod-chromium --workers=1 --retries=0" in replay["run"]
    reconcile = next(
        step for step in steps
        if step.get("name") == "Reconcile required native Playwright evidence"
    )
    assert "steps.platform-report-prerequisites.outputs.ready" in reconcile["env"][
        "PLATFORM_REPORT_READY"
    ]
    assert 'if [[ "$PLATFORM_REPORT_READY" == true ]]; then required+=(platform-reports)' in (
        reconcile["run"]
    )
    config = (ROOT / "playwright.prod-ram.config.ts").read_text(encoding="utf-8")
    project = config.split('name: "platform-reports-prod-chromium"', 1)[1].split(
        "name:", 1
    )[0]
    assert "testMatch: PLATFORM_REPORT_ADMIN_PROD_SPECS" in project
    assert "storageState: { cookies: [], origins: [] }" in project
    assert "extraHTTPHeaders: noPaidProviderHeaders" in config
