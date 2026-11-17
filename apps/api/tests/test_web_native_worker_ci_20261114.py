"""Keep the real offline browser worker provisioned and its failed evidence retained."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]


def test_web_native_browser_dependency_precedes_unchanged_coverage_gate() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["web"]["steps"]
    installs = [index for index, step in enumerate(steps)
                if step.get("run") == "npx --no-install playwright install chromium"]
    coverage = next(index for index, step in enumerate(steps)
                    if step.get("run") == "npm run test:coverage --workspace @caseops/web")
    assert len(installs) == 1 and installs[0] < coverage
    assert steps[installs[0]]["env"]["NPM_CONFIG_STRICT_SSL"] == (
        "${{ steps.node_trust.outputs.NPM_CONFIG_STRICT_SSL }}"
    )
    assert workflow["jobs"]["web"]["timeout-minutes"] == 15
    assert workflow["jobs"]["web"]["runs-on"] == "ubuntu-24.04"


def test_web_worker_failure_retention_is_exact_synthetic_json_only() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["web"]["steps"]
                if step.get("name") == "Retain native offline worker results")
    assert step["if"] == "always()"
    assert step["with"]["path"] == "test-results/native-loader/**/*.json"
    assert step["with"]["include-hidden-files"] is False
    assert step["with"]["retention-days"] == 14
    source = (ROOT / "apps/web/lib/e2e-external-journey-loading.test.ts").read_text(
        encoding="utf-8"
    )
    assert 'path.join(root, "test-results/native-loader", path.basename(dir))' in source
    assert 'writeFileSync(path.join(retained, "native.json"), result.stdout ?? "")' in source


def test_windows_runs_the_complete_frontend_inventory_with_original_budgets() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    linux = workflow["jobs"]["web"]
    windows = workflow["jobs"]["web-windows"]
    assert windows["runs-on"] == "windows-2025-vs2026"
    assert windows["timeout-minutes"] == 60
    assert linux["timeout-minutes"] == 15
    steps = windows["steps"]
    node = next(step for step in steps if step.get("uses") == "actions/setup-node@v4")
    assert node["with"]["node-version"] == "22.23.4"
    python = next(step for step in steps if step.get("id") == "metadata_python")
    assert python["uses"] == (
        "actions/setup-python@6d4fd22b20465ccc0f7354476588e8df7c9ca0e0"
    )
    assert python["with"]["python-version"] == "3.13.14"
    stdlib = next(step for step in steps
                  if step.get("name") == "Create candidate-owned stdlib metadata environment")
    assert stdlib["timeout-minutes"] == 1
    assert "-m venv --without-pip apps/api/.venv" in stdlib["run"]
    assert "sys.version_info[:3] == (3, 13, 14)" in stdlib["run"]
    assert steps.index(stdlib) < next(index for index, step in enumerate(steps)
                                     if step.get("run") == "npm ci")
    runs = [step.get("run") for step in steps]
    assert runs.count("npm run test:coverage --workspace @caseops/web") == 1
    assert "npm run typecheck:web" in runs and "npm run typecheck:e2e" in runs
    assert runs.index("npx --no-install playwright install chromium") < runs.index(
        "npm run test:coverage --workspace @caseops/web"
    )
    linux_install = next(step for step in linux["steps"] if step.get("run") == "npm ci")
    for step in steps:
        if step.get("run") in {"npm ci", "npm run typecheck:web", "npm run typecheck:e2e",
                               "npx --no-install playwright install chromium",
                               "npm run test:coverage --workspace @caseops/web"}:
            assert step["env"] == linux_install["env"]
    source = (ROOT / "apps/web/lib/e2e-external-journey-loading.test.ts").read_text(
        encoding="utf-8"
    )
    assert "timeout: 15_000" in source and "timeout: 5000" in source
    assert "expected: 3, unexpected: 0, skipped: 0, flaky: 0" in source


def test_windows_retains_failure_phases_and_trust_lifecycle_without_media() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    artifacts = [step for step in workflow["jobs"]["web-windows"]["steps"]
                 if step.get("uses") == "actions/upload-artifact@v4"]
    assert {step["with"]["path"] for step in artifacts if "native" in step["with"]["name"]} == {
        "test-results/native-loader/**/*.json", "test-results/native-trust/**/*.json",
    }
    assert all(step["if"] == "always()" for step in artifacts)
    assert all(step["with"].get("include-hidden-files", False) is False for step in artifacts)
    source = (ROOT / "apps/web/lib/e2e-external-journey-loading.test.ts").read_text(
        encoding="utf-8"
    )
    assert 'writeFileSync(path.join(retained, "stages.json"), JSON.stringify(stages))' in source
