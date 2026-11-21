"""The local Docker Playwright config scales every browser time limit exactly once.

Owner-approved on 2026-11-15 after full-docker-17 timed out five browser cases
that passed in 9-48 s on full-docker-08 while other workstation work ran. Most
specs replace the config timeout with test.setTimeout(), so only the worker's
TimeoutManager sees every limit. These runs use the pinned Playwright runtime,
not a mock: a config default, describe-level and in-test setTimeout,
testInfo.setTimeout, an unlimited zero, the action, navigation and expect limits,
and a real deadline that must still fire. Scale 1 is the negative control: the
same deadline case fails, so the suite can tell a scaled limit from none.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]

APP_CONFIG_STUB = """import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: ".",
  testMatch: /.*\\.spec\\.ts/,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 1_000 },
  reporter: [["list"]],
  use: { actionTimeout: 15_000, navigationTimeout: 30_000 },
});
"""

SPEC = """import { expect, test } from "@playwright/test";
const S = Number(process.env.CASEOPS_E2E_TIMEOUT_SCALE ?? "3");
test("config default is scaled once", async ({}, info) => {
  expect(info.timeout).toBe(120_000 * S);
});
test.describe("describe-level", () => {
  test.setTimeout(150_000);
  test("describe-level setTimeout is scaled", async ({}, info) => {
    expect(info.timeout).toBe(150_000 * S);
  });
});
test("in-test setTimeout is scaled", async ({}, info) => {
  test.setTimeout(120_000);
  expect(info.timeout).toBe(120_000 * S);
});
test("testInfo.setTimeout is scaled", async ({}, info) => {
  info.setTimeout(1_000);
  expect(info.timeout).toBe(1_000 * S);
});
test("zero stays unlimited", async ({}, info) => {
  test.setTimeout(0);
  expect(info.timeout).toBe(0);
});
test("action and navigation limits are scaled", async ({}, info) => {
  expect((info.project.use as { actionTimeout?: number }).actionTimeout).toBe(60_000 * S);
  expect((info.project.use as { navigationTimeout?: number }).navigationTimeout).toBe(30_000 * S);
});
test("expect limit is scaled", async () => {
  const started = Date.now();
  await expect.poll(() => false, { intervals: [50] }).toBe(true).catch(() => undefined);
  const elapsed = Date.now() - started;
  expect(elapsed).toBeGreaterThanOrEqual(1_000 * S - 100);
  expect(elapsed).toBeLessThan(1_000 * S + 2_500);
});
test("a real deadline is enforced at the scaled limit", async () => {
  test.setTimeout(1_000);
  await new Promise((resolve) => setTimeout(resolve, 2_000));
});
"""

DEADLINE_CASE = "a real deadline is enforced at the scaled limit"


def _runtime() -> tuple[str, Path]:
    cli = Path(
        os.environ.get("CASEOPS_TEST_PLAYWRIGHT_CLI", ROOT / "node_modules/@playwright/test/cli.js")
    ).resolve()
    assert cli.is_file(), "The scaled Docker config needs an installed Playwright runtime."
    node = shutil.which("node")
    assert node, "The scaled Docker config needs node on PATH."
    return node, cli


def _project(tmp_path: Path, cli: Path) -> Path:
    package = tmp_path / "node_modules/@playwright/test"
    package.mkdir(parents=True)
    (package / "index.js").write_text(
        f"module.exports = require({json.dumps(str(cli.with_name('index.js')))});\n",
        encoding="utf-8",
    )
    (tmp_path / "playwright.docker.config.ts").write_bytes(
        (ROOT / "playwright.docker.config.ts").read_bytes()
    )
    (tmp_path / "playwright.app.config.ts").write_text(APP_CONFIG_STUB, encoding="utf-8")
    (tmp_path / "scale.spec.ts").write_text(SPEC, encoding="utf-8")
    return tmp_path


def _run(tmp_path: Path, scale: str | None) -> tuple[subprocess.CompletedProcess, dict]:
    node, cli = _runtime()
    project = _project(tmp_path, cli)
    report = tmp_path / "report.json"
    env = {key: value for key, value in os.environ.items() if key != "NODE_OPTIONS"}
    env.update(CI="1", PLAYWRIGHT_JSON_OUTPUT_NAME=str(report))
    env.pop("CASEOPS_E2E_TIMEOUT_SCALE", None)
    if scale is not None:
        env["CASEOPS_E2E_TIMEOUT_SCALE"] = scale
    result = subprocess.run(
        [node, str(cli), "test", "--config=playwright.docker.config.ts", "--reporter=json"],
        cwd=project,
        env=env,
        capture_output=True,
        encoding="utf-8",
        timeout=180,
    )
    document = json.loads(report.read_text(encoding="utf-8")) if report.exists() else {}
    return result, document


def _outcomes(document: dict) -> dict[str, str]:
    outcomes: dict[str, str] = {}

    def walk(suites):
        for suite in suites:
            for spec in suite.get("specs", []):
                for native in spec["tests"]:
                    assert len(native["results"]) == 1
                    outcomes[spec["title"]] = native["results"][0]["status"]
            walk(suite.get("suites", []))

    walk(document.get("suites", []))
    return outcomes


@pytest.mark.parametrize("scale", [None, "3", "2.5"], ids=["default", "three", "fractional"])
def test_every_browser_limit_is_scaled_exactly_once(tmp_path, scale):
    result, document = _run(tmp_path, scale)
    outcomes = _outcomes(document)
    assert len(outcomes) == 8, result.stdout + result.stderr
    assert set(outcomes.values()) == {"passed"}, outcomes
    assert result.returncode == 0, result.stdout + result.stderr


def test_scale_one_keeps_original_limits_and_the_deadline_still_fires(tmp_path):
    result, document = _run(tmp_path, "1")
    outcomes = _outcomes(document)
    assert len(outcomes) == 8, result.stdout + result.stderr
    assert outcomes.pop(DEADLINE_CASE) == "timedOut"
    assert set(outcomes.values()) == {"passed"}, outcomes
    assert result.returncode != 0


@pytest.mark.parametrize("scale", ["0.5", "6", "abc", "", "-2", "3x"])
def test_an_invalid_scale_refuses_before_any_case_runs(tmp_path, scale):
    result, document = _run(tmp_path, scale)
    assert result.returncode != 0
    assert _outcomes(document) == {}
    assert "CASEOPS_E2E_TIMEOUT_SCALE must be a number from 1 to 5." in (
        result.stdout + result.stderr + json.dumps(document.get("errors", []))
    )
