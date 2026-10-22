import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, it } from "vitest";

type NativeTest = { projectId: string; projectName: string; repeatEachIndex?: number; retries?: number; results: unknown[] };
type NativeSuite = { title: string; specs?: { id: string; file: string; title: string; tests: NativeTest[] }[]; suites?: NativeSuite[] };
type Case = { id: string; file: string; titles: string[]; project: string; repeat: number; retries: number; results: unknown[] };

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const projects = {
  "tester-prod-chromium": 116,
  "tester-index-prod-chromium": 6,
  "test-legal-write-prod-chromium": 50,
};
const indexFiles = { "ram-2026-10-10-prod.spec.ts": 4, "ram-2026-10-12-prod.spec.ts": 2 };
const datedFiles = {
  "ram-2026-10-13-hearings.spec.ts": 2,
  "ram-2026-10-13-ip-portfolio.spec.ts": 4,
  "ram-2026-10-15-ip-controls.spec.ts": 34,
  "ram-2026-10-15-ip-renewal-tracker.spec.ts": 2,
  "ram-2026-10-17-calendar-readiness.spec.ts": 2,
  "ram-2026-10-17-ip-reminders.spec.ts": 4,
  "ram-2026-10-17-ip-tracker.spec.ts": 2,
};

function flatten(suites: NativeSuite[], projectRetries: Record<string, number>, parents: string[] = []): Case[] {
  return suites.flatMap(suite => {
    const titles = [...parents, suite.title];
    return [
      ...(suite.specs ?? []).flatMap(spec => spec.tests.map((test, ordinal) => ({
        id: `${spec.id}:${test.projectId}:${ordinal}`,
        file: spec.file.replaceAll("\\", "/").split("/").at(-1)!,
        titles: [...titles, spec.title], project: test.projectName,
        repeat: test.repeatEachIndex ?? 0, retries: test.retries ?? projectRetries[test.projectId], results: test.results,
      }))),
      ...flatten(suite.suites ?? [], projectRetries, titles),
    ];
  });
}

function counts(values: string[]) {
  return values.reduce<Record<string, number>>((result, value) => {
    result[value] = (result[value] ?? 0) + 1;
    return result;
  }, {});
}

describe("reviewed production tester source inventory", () => {
  let cases: Case[];

  beforeAll(() => {
    // Collection imports specs but never runs setup, browsers, auth or app code.
    const env: NodeJS.ProcessEnv = { NODE_ENV: "test" };
    for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"]) {
      if (process.env[key]) env[key] = process.env[key];
    }
    Object.assign(env, {
      CI: "1", PROD_BASE_URL: "https://caseops.ai", PROD_API_BASE_URL: "https://api.caseops.ai",
      NOTICE_QA_SLUG: "source-inventory-fixture", NOTICE_QA_OWNER_EMAIL: "qa@fixture.invalid",
      NOTICE_QA_OWNER_PASSWORD: "fixture-only-not-used",
      CASEOPS_EXPECTED_RELEASE_SHA: "a".repeat(40), CASEOPS_RELEASE_SHA: "a".repeat(40),
    });
    const result = spawnSync(process.execPath, [
      path.join(root, "node_modules/@playwright/test/cli.js"), "test",
      "--config=playwright.prod-ram.config.ts", "--list", "--reporter=json",
      ...Object.keys(projects).map(project => `--project=${project}`),
    ], { cwd: root, env, encoding: "utf8", timeout: 8_000, maxBuffer: 16 * 1024 * 1024, windowsHide: true });
    expect(result.error).toBeUndefined();
    expect(result.status, result.stderr).toBe(0);
    const native = JSON.parse(result.stdout) as {
      errors: unknown[]; suites: NativeSuite[];
      config: { projects: { id: string; retries: number; repeatEach: number }[] };
    };
    expect(native.errors).toEqual([]);
    expect(native.config.projects.every(project => project.repeatEach === 1)).toBe(true);
    const projectRetries = Object.fromEntries(native.config.projects.map(project => [project.id, project.retries]));
    cases = flatten(native.suites, projectRetries).filter(row => Object.hasOwn(projects, row.project));
  });

  it("collects the independent reviewed116+6+50 exact partition before production", () => {
    expect(counts(cases.map(row => row.project))).toEqual(projects);
    expect(cases).toHaveLength(172);
    expect(cases.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(cases.filter(row => row.file === "ram-2026-10-22-prod.spec.ts")
      .map(row => ({ project: row.project, title: row.titles.at(-1) }))).toEqual([{
        project: "tester-prod-chromium",
        title: "NOTES22 newest three of four saved notes persist after reload at 1280px and 393px",
      }]);
  });

  it("retains exact per-file index and dated inventories", () => {
    expect(counts(cases.filter(row => row.project === "tester-index-prod-chromium").map(row => row.file))).toEqual(indexFiles);
    expect(counts(cases.filter(row => row.project === "test-legal-write-prod-chromium").map(row => row.file))).toEqual(datedFiles);
    expect(cases.filter(row => row.project === "tester-prod-chromium")
      .every(row => !Object.hasOwn(indexFiles, row.file) && !Object.hasOwn(datedFiles, row.file))).toBe(true);
  });

  it("retains distinct native identities and a disjoint semantic union", () => {
    expect(new Set(cases.map(row => row.id)).size).toBe(cases.length);
    expect(new Set(cases.map(row => JSON.stringify([row.file, row.titles, row.repeat]))).size).toBe(cases.length);
  });

  it("discovers all16 breakpoint journeys and18 pure-DOM guard identities", () => {
    const controls = cases.filter(row => row.file === "ram-2026-10-15-ip-controls.spec.ts");
    const widths = [393, 639, 640, 641, 767, 768, 769, 1023, 1024, 1025, 1279, 1280, 1281, 1535, 1536, 1537];
    const guards = ["current", "missing-link", "stale-id-same-caption", "wrong-caption", "hidden", "transparent",
      "clipped", "ellipsis", "absolute", "narrow-outside-form", "outside-form", "outside-viewport", "empty-selection",
      "button-overflow", "required-no-overflow", "missing-required-no-overflow", "ancestor-clipped", "outside-owner-vertical"];
    expect(controls.map(row => row.titles.at(-1)).sort()).toEqual([
      ...widths.map(width => `IP15 BUG-001..007 governed controls and readable forms at ${width}px`),
      ...guards.map(guard => `IP15 geometry guard ${guard}`),
    ].sort());
  });
});
