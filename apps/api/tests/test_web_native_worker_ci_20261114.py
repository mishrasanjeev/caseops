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
