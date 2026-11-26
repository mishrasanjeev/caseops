// @vitest-environment node

import { spawnSync, type SpawnSyncOptionsWithStringEncoding, type SpawnSyncReturns } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { beforeAll, describe, expect, it } from "vitest";

type NativeAnnotation = { type: string; description?: string };
type NativeTest = { projectId: string; projectName: string; repeatEachIndex?: number; retries?: number; results: unknown[]; annotations?: NativeAnnotation[]; expectedStatus?: string };
type NativeSuite = { title: string; specs?: { id: string; file: string; title: string; tests: NativeTest[] }[]; suites?: NativeSuite[] };
type Case = { id: string; file: string; titles: string[]; project: string; repeat: number; retries: number; results: unknown[]; annotations?: NativeAnnotation[]; expectedStatus?: string };

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const projects = {
  "tester-prod-chromium": 115,
  "tester-index-prod-chromium": 6,
  "test-legal-write-prod-chromium": 55,
};
const batch3Projects = {
  "batch3-clients-prod-chromium": 1,
  "batch3-clients-prod-mobile": 1,
  "batch3-drafts-readonly-prod-chromium": 1,
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
  "ram-2026-10-22-prod.spec.ts": 1,
  "ram-2026-11-14-prod.spec.ts": 4,
};

// These are independent reviewed identities, not imported planner expectations.
// Preserve all51 original cases and move the four reference cases into the
// existing serialized reporting role without changing their semantic union.
const oct13AFiles = [
  "ram-2026-10-13-hearings.spec.ts",
  "ram-2026-10-13-ip-portfolio.spec.ts",
  "ram-2026-10-15-ip-controls.spec.ts",
] as const;
const oct13BFiles = [
  "ram-2026-10-15-ip-renewal-tracker.spec.ts",
  "ram-2026-10-17-calendar-readiness.spec.ts",
  "ram-2026-10-17-ip-reminders.spec.ts",
  "ram-2026-10-17-ip-tracker.spec.ts",
  "ram-2026-10-22-prod.spec.ts",
  "ram-2026-11-14-prod.spec.ts",
] as const;
const oct13AIdentities = [
  ["ram-2026-10-13-hearings.spec.ts","October 13 court Calendar acceptance","saved court identities and every hidden event remain reachable at 1280px"],
  ["ram-2026-10-13-hearings.spec.ts","October 13 court Calendar acceptance","saved court identities and every hidden event remain reachable at 393px"],
  ["ram-2026-10-13-ip-portfolio.spec.ts","source-tolerant portfolio import, duplicate skip and renewal alert at 1280px"],
  ["ram-2026-10-13-ip-portfolio.spec.ts","acknowledged 50-row batches recover from keyless history at 1280px"],
  ["ram-2026-10-13-ip-portfolio.spec.ts","source-tolerant portfolio import, duplicate skip and renewal alert at 393px"],
  ["ram-2026-10-13-ip-portfolio.spec.ts","acknowledged 50-row batches recover from keyless history at 393px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard current"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard missing-link"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard stale-id-same-caption"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard wrong-caption"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard hidden"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard transparent"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard clipped"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard ellipsis"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard absolute"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard narrow-outside-form"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard outside-form"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard outside-viewport"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard empty-selection"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard button-overflow"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard required-no-overflow"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard missing-required-no-overflow"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard ancestor-clipped"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 geometry guard outside-owner-vertical"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 393px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 639px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 640px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 641px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 767px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 768px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 769px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1023px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1024px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1025px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1279px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1280px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1281px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1535px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1536px"],
  ["ram-2026-10-15-ip-controls.spec.ts","IP15 BUG-001..007 governed controls and readable forms at 1537px"],
] as const;
const oct13BIdentities = [
  ["ram-2026-10-15-ip-renewal-tracker.spec.ts","IP15 editable portfolio dates and persisted renewal tracker at 1280px"],
  ["ram-2026-10-15-ip-renewal-tracker.spec.ts","IP15 editable portfolio dates and persisted renewal tracker at 393px"],
  ["ram-2026-10-17-calendar-readiness.spec.ts","CAL17 actual Calendar readiness and retained cleanup remain truthful at 1280px"],
  ["ram-2026-10-17-calendar-readiness.spec.ts","CAL17 actual Calendar readiness and retained cleanup remain truthful at 393px"],
  ["ram-2026-10-17-ip-reminders.spec.ts","IP17 hearing reminder policy and time confirmation at 1280px"],
  ["ram-2026-10-17-ip-reminders.spec.ts","IP17 recipient dismisses and restores delivered renewal at 1280px"],
  ["ram-2026-10-17-ip-reminders.spec.ts","IP17 hearing reminder policy and time confirmation at 393px"],
  ["ram-2026-10-17-ip-reminders.spec.ts","IP17 recipient dismisses and restores delivered renewal at 393px"],
  ["ram-2026-10-17-ip-tracker.spec.ts","IP18 current-source tracker filters saved views export and full continuation at 1280px"],
  ["ram-2026-10-17-ip-tracker.spec.ts","IP18 current-source tracker filters saved views export and full continuation at 393px"],
  ["ram-2026-10-22-prod.spec.ts","NOTES22 newest three of four saved notes persist after reload at 1280px and 393px"],
  ["ram-2026-11-14-prod.spec.ts","IP India content and form references /app/ip/registry desktop"],
  ["ram-2026-11-14-prod.spec.ts","IP India content and form references /app/ip/patents desktop"],
  ["ram-2026-11-14-prod.spec.ts","[mobile] IP India content and form references /app/ip/registry phone"],
  ["ram-2026-11-14-prod.spec.ts","[mobile] IP India content and form references /app/ip/patents phone"],
] as const;
const oct13Parts = [
  { invocation: "test-legal-write-oct13-a", files: oct13AFiles, identities: oct13AIdentities, count: 40 },
  { invocation: "test-legal-write-oct13-b", files: oct13BFiles, identities: oct13BIdentities, count: 15 },
] as const;

function datedIdentity(row: Case) {
  return [row.file, ...row.titles.slice(1)];
}

function flatten(suites: NativeSuite[], projectRetries: Record<string, number>, parents: string[] = []): Case[] {
  return suites.flatMap(suite => {
    const titles = [...parents, suite.title];
    return [
      ...(suite.specs ?? []).flatMap(spec => spec.tests.map((test, ordinal) => ({
        id: `${spec.id}:${test.projectId}:${ordinal}`,
        file: spec.file.replaceAll("\\", "/").split("/").at(-1)!,
        titles: [...titles, spec.title], project: test.projectName,
        repeat: test.repeatEachIndex ?? 0, retries: test.retries ?? projectRetries[test.projectId], results: test.results,
        annotations: test.annotations ?? [], expectedStatus: test.expectedStatus,
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

function collectProjects(selectedProjects: Record<string, number>, selectedFiles: readonly string[] = []): Case[] {
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
  // Match only the literal whole-file basenames, including native path separators.
  const fileFilter = selectedFiles.length ? [
    String.raw`(?:^|[/\\])(?:` + selectedFiles.map(file => file.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")$",
  ] : [];
  const result = spawnSync(process.execPath, [
    path.join(root, "node_modules/@playwright/test/cli.js"), "test",
    "--config=playwright.prod-ram.config.ts", "--list", "--reporter=json",
    ...Object.keys(selectedProjects).map(project => `--project=${project}`),
    ...fileFilter,
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
  return flatten(native.suites, projectRetries).filter(row => Object.hasOwn(selectedProjects, row.project));
}

type MetadataConstructor = (command: string, args: string[], options: SpawnSyncOptionsWithStringEncoding) =>
  Pick<SpawnSyncReturns<string>, "error" | "status" | "stdout" | "stderr">;
const appSourceProjects = { "app-chromium": 719, "app-mobile": 55 };
const motorStatuteFile = "ram-2026-09-07-statute-source-data.spec.ts";
const motorStatuteTitles = [
  "BUG-018 Motor Vehicles source records 1-40 of 259",
  "BUG-018 Motor Vehicles source records 41-80 of 259",
  "BUG-018 Motor Vehicles source records 81-120 of 259",
  "BUG-018 Motor Vehicles source records 121-160 of 259",
  "BUG-018 Motor Vehicles source records 161-200 of 259",
  "BUG-018 Motor Vehicles source records 201-240 of 259",
  "BUG-018 Motor Vehicles source records 241-259 of 259",
];
const isMotorStatute = (row: Case) => row.file === motorStatuteFile
  && Boolean(row.titles.at(-1)?.startsWith("BUG-018 Motor Vehicles source records "));
const compactMatterFile = "matter-compact-cards.spec.ts";
const compactMatterSuite = "BUG-016 compact Matter cards";
const isCompactMatter = (row: Case) => row.file === compactMatterFile && row.titles[1] === compactMatterSuite;
const batch5Files = ["statutes", "drafting", "contracts", "bugs"].map(name => `ram-2026-11-11-${name}.spec.ts`);
const isBatch5 = (row: Case) => batch5Files.includes(row.file.split("/").at(-1)!);
const nov14Cases = [
  ["app-chromium", "ram-2026-11-14-prod.spec.ts", "IP India content and form references /app/ip/registry desktop"],
  ["app-chromium", "ram-2026-11-14-prod.spec.ts", "IP India content and form references /app/ip/patents desktop"],
  ["app-chromium", "draft-quality20261114.spec.ts", "Draft quality 2026-11-14 desktop: generated findings survive correction and reload"],
  ["app-mobile", "ram-2026-11-14-prod.spec.ts", "[mobile] IP India content and form references /app/ip/registry phone"],
  ["app-mobile", "ram-2026-11-14-prod.spec.ts", "[mobile] IP India content and form references /app/ip/patents phone"],
  ["app-mobile", "draft-quality20261114.spec.ts", "Draft quality 2026-11-14 [mobile] phone: generated findings survive correction and reload"],
] as const;
const isNov14 = (row: Case) => ["ram-2026-11-14-prod.spec.ts", "draft-quality20261114.spec.ts"].includes(row.file);
const nov15Cases = [
  ["app-chromium", "drafting-formats20261115.spec.ts", "Draft formats 2026-11-15 desktop: guided deed choice, version history and exact downloads"],
  ["app-mobile", "drafting-formats20261115.spec.ts", "Draft formats 2026-11-15 [mobile] phone: guided deed choice, version history and exact downloads"],
] as const;
const isNov15 = (row: Case) => row.file === "drafting-formats20261115.spec.ts";
function expectNov15(rows: Case[]) {
  const selected = rows.filter(isNov15);
  expect(selected.map(row => JSON.stringify([row.project, row.file, row.titles])).sort()).toEqual(
    nov15Cases.map(([project, file, title]) => JSON.stringify([project, file, [file, title]])).sort(),
  );
  expect(new Set(selected.map(row => row.id)).size).toBe(2);
  expect(selected.every(row => row.retries === 0 && row.repeat === 0 && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
}
function expectNov14(rows: Case[], production = false) {
  const selected = rows.filter(isNov14);
  const expected = nov14Cases.filter(([, file]) => !production || file === "ram-2026-11-14-prod.spec.ts")
    .map(([project, file, title]) => JSON.stringify([production ? "test-legal-write-prod-chromium" : project, file, [file, title]])).sort();
  expect(selected.map(row => JSON.stringify([row.project, row.file, row.titles])).sort()).toEqual(expected);
  expect(new Set(selected.map(row => row.id)).size).toBe(selected.length);
  expect(selected.every(row => row.retries === 0 && row.repeat === 0 && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
}
// November 22 release additions, matched by exact identity (one shares an
// existing file with retained canonical cases).
const nov22Cases = [
  ["app-chromium", ["matter-ethical-walls-admin-2026-11-22.spec.ts", "admin walls a colleague off a Matter and lifts the wall at 1280px"]],
  ["app-mobile", ["matter-ethical-walls-admin-2026-11-22.spec.ts", "[mobile] admin walls a colleague off a Matter and lifts the wall at 393px"]],
  ["app-chromium", ["public-content.spec.ts", "Public landing page and user guide", "desktop November 22 product claims show their limits"]],
  ["app-chromium", ["public-content.spec.ts", "Public landing page and user guide", "mobile November 22 product claims show their limits"]],
] as const;
const nov22Keys = new Set(nov22Cases.map(([project, titles]) => JSON.stringify([project, titles])));
const isNov22 = (row: Case) => nov22Keys.has(JSON.stringify([row.project, row.titles]));
// November 24 workbook regressions (rows 1-6), matched by exact identity.
const nov24File = "ram-2026-11-24-bugs.spec.ts";
const nov24Cases = [
  ["app-chromium", "row 1 header workspace group is at the right edge at 1920px"],
  ["app-chromium", "row 1 header workspace group is at the right edge at 1536px"],
  ["app-chromium", "row 1 header workspace group is at the right edge at 1365px"],
  ["app-chromium", "row 1 header workspace group is at the right edge at 1024px"],
  ["app-chromium", "row 2 Today and Next action open the exact task and deadline"],
  ["app-chromium", "row 3 sidebar groups expand and collapse"],
  ["app-chromium", "row 4 Next reaches page four without Load more"],
  ["app-chromium", "row 5 search by title finds a matter on an unloaded page"],
  ["app-chromium", "row 5 search by code finds a matter on an unloaded page"],
  ["app-chromium", "row 5 search by client finds a matter on an unloaded page"],
  ["app-chromium", "row 6 Suggested Counsel cards align at 80-150% zoom"],
  ["app-mobile", "[mobile] row 1 header avatar stays at the right edge on a phone"],
  ["app-mobile", "[mobile] row 3 sidebar groups expand and collapse"],
] as const;
const nov24Keys = new Set(nov24Cases.map(([project, title]) => JSON.stringify([project, [nov24File, title]])));
const isNov24 = (row: Case) => row.file === nov24File;
// November 25 workbook (2) regressions (rows 1-3, nova-legal) plus the source
// batches for the newly admitted Constitution, matched by exact identity.
const nov25ConstitutionPrefix = "Nov25 Constitution source records ";
const nov25Cases = [
  ...[
    "1-40", "41-80", "81-120", "121-160", "161-200", "201-240", "241-280",
    "281-320", "321-360", "361-400", "401-440", "441-480", "481-519",
  ].map(range => ["app-chromium", motorStatuteFile, `${nov25ConstitutionPrefix}${range} of 519`] as const),
  ["app-chromium", "nova-2026-11-25-statutes.spec.ts", "row 1 Constitution Article 21 is chosen and attached from the Add Reference dialog"],
  ["app-chromium", "nova-2026-11-25-client-links.spec.ts", "row 2 links a client from the client page and from the matter overview"],
  ["app-chromium", "nova-2026-11-25-client-links.spec.ts", "row 2 new matter links an existing client at creation"],
  ["app-chromium", "nova-2026-11-25-ask-workspace.spec.ts", "row 3 Ask Workspace answers parties, pending actions, documents and Act sections from the cited Matter record"],
  ["app-mobile", "nova-2026-11-25-statutes.spec.ts", "[mobile] row 1 Constitution Article 21 is chosen and attached from the Add Reference dialog"],
  ["app-mobile", "nova-2026-11-25-client-links.spec.ts", "[mobile] row 2 links a client from the matter overview on a phone"],
] as const;
const nov25Keys = new Set(nov25Cases.map(([project, file, title]) => JSON.stringify([project, [file, title]])));
const nov25Files = new Set<string>(nov25Cases.map(([, file]) => file).filter(file => file !== motorStatuteFile));
const isNov25 = (row: Case) => nov25Files.has(row.file)
  || (row.file === motorStatuteFile && Boolean(row.titles.at(-1)?.startsWith(nov25ConstitutionPrefix)));
const batch5BugsFile = "ram-2026-11-11-bugs.spec.ts";
const batch5BugsProofCases = [
  ["BUG-003 communications resolved preview and missing-value guard desktop", "preview-no-paid-guard"],
  ["[mobile] BUG-003 communications resolved preview and missing-value guard phone", "preview-no-paid-guard"],
  ["B5-013/014 assistant factual citation, legal abstention and research mode navigation desktop", "assistant-research-no-paid-guard"],
  ["[mobile] B5-013/014 assistant factual citation, legal abstention and research mode navigation phone", "assistant-research-no-paid-guard"],
] as const;

function expectBatch5BugsProofs(rows: Case[]) {
  const actual = rows.filter(row => row.file === batch5BugsFile).map(row => JSON.stringify([
    row.project.endsWith("mobile") ? "mobile" : "desktop", row.file, row.titles,
    [...new Set((row.annotations ?? []).filter(item => item.type === "caseops-b5-proof")
      .map(item => item.description))].sort(),
  ])).sort();
  const expected = batch5BugsProofCases.map(([title, scope]) => JSON.stringify([
    title.startsWith("[mobile]") ? "mobile" : "desktop", batch5BugsFile,
    [batch5BugsFile, title], [scope],
  ])).sort();
  expect(actual).toEqual(expected);
}

function flattenApp(suites: NativeSuite[], retries: Record<string, number>, parents: string[] = []): Case[] {
  return suites.flatMap(suite => {
    const titles = [...parents, suite.title];
    return [
      ...(suite.specs ?? []).flatMap(spec => spec.tests.map((test, ordinal) => ({
        id: `${spec.id}:${test.projectId}:${ordinal}`, file: spec.file.replaceAll("\\", "/"),
        titles: [...titles, spec.title], project: test.projectName,
        repeat: test.repeatEachIndex ?? 0, retries: test.retries ?? retries[test.projectId], results: test.results,
        annotations: test.annotations ?? [], expectedStatus: test.expectedStatus,
      }))),
      ...flattenApp(suite.suites ?? [], retries, titles),
    ];
  });
}

function hasEagerSchemaModule(stderr: string): boolean {
  return stderr.split("\n").some(line => {
    if (!line.startsWith("MODULE ") || (!line.includes(': load "') && !line.includes(": load '"))) return false;
    // Collapse each separator run once; avoid overlapping path quantifiers
    // while retaining both native Windows and POSIX diagnostic formats.
    const normalized = line.replaceAll("\\", "/").replace(/\/+/g, "/").toLowerCase();
    return normalized.includes("/node_modules/zod/") || normalized.includes('/node_modules/zod"')
      || normalized.includes("/node_modules/zod'");
  });
}

function collectAppProject(project?: keyof typeof appSourceProjects, execute: MetadataConstructor = spawnSync): Case[] {
  // The retained774-case baseline is checked apart from the old eight plus two B5 additions.
  // Keep the15s constructor/20s hooks and units. The
  // established production collector above keeps its literal8s bound unchanged.
  const env: NodeJS.ProcessEnv = { NODE_ENV: "test" };
  for (const key of ["PATH", "Path", "SystemRoot", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE"]) {
    if (process.env[key]) env[key] = process.env[key];
  }
  Object.assign(env, {
    CI: "1", CASEOPS_EXPECTED_RELEASE_SHA: "a".repeat(40), CASEOPS_RELEASE_SHA: "a".repeat(40),
    CASEOPS_WEB_BASE_URL: "http://127.0.0.1:3100",
    NODE_DEBUG: "module",
    NOTICE_QA_SLUG: "source-inventory-fixture", NOTICE_QA_OWNER_EMAIL: "qa@fixture.invalid",
    NOTICE_QA_OWNER_PASSWORD: "fixture-only-not-used",
  });
  const selected = project ? [`--project=${project}`] : [];
  const result = execute(process.execPath, [
    path.join(root, "node_modules/@playwright/test/cli.js"), "test",
    "--config=playwright.app.config.ts", "--list", "--reporter=json", ...selected,
  ], { cwd: root, env, encoding: "utf8", timeout: 15_000, maxBuffer: 16 * 1024 * 1024, windowsHide: true });
  expect(result.error).toBeUndefined();
  expect(result.status, result.stderr).toBe(0);
  expect(hasEagerSchemaModule(result.stderr), "App metadata must defer runtime application schemas").toBe(false);
  const native = JSON.parse(result.stdout) as {
    errors: unknown[]; suites: NativeSuite[];
    config: { projects: { id: string; name: string; retries: number; repeatEach: number }[] };
  };
  expect(native.errors).toEqual([]);
  // FullConfig declares both projects even for a single selected native suite.
  expect(native.config.projects.map(row => [row.id, row.name, row.retries, row.repeatEach])).toEqual([
    ["app-chromium", "app-chromium", 0, 1], ["app-mobile", "app-mobile", 0, 1],
  ]);
  const retries = Object.fromEntries(native.config.projects.map(row => [row.id, row.retries]));
  return flattenApp(native.suites, retries); // Never hide an unselected native row.
}

const appIdentity = (row: Case) => [row.id, row.file, row.titles, row.project, row.repeat, row.retries];
function expectAppSelection(actual: Case[], expected: Case[]) {
  expect(actual.map(appIdentity)).toEqual(expected.map(appIdentity));
  expect(actual.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
}

function canonicalAppProject(canonical: Case[], project: keyof typeof appSourceProjects): Case[] {
  // Playwright's file collector visits directory entries by localeCompare.
  // Its built-in JSON reporter then merges files from separate projects, which
  // can append a mobile-only file. Reconstruct only canonical source-file order;
  // equal-file rows retain their observed order. Selected output stays untouched.
  return canonical.filter(row => row.project === project).sort((left, right) => {
    const a = left.file.split("/"), b = right.file.split("/");
    for (let index = 0; index < Math.max(a.length, b.length); index++) {
      if (a[index] === undefined) return -1;
      if (b[index] === undefined) return 1;
      const order = a[index].localeCompare(b[index]);
      if (order) return order;
    }
    return 0;
  });
}

// Independent source collection: no production Python registry or config import
// supplies the expected App partition. --list never starts either local stack.
describe("complete independent App CI project inventory", () => {
  let all: Case[];
  let canonical: Case[];
  let batch5: Case[];
  let nov14: Case[];
  let nov15: Case[];
  let motorStatutes: Case[];
  let compactMatter: Case[];
  let nov22: Case[];
  let nov24: Case[];
  let nov25: Case[];
  let wholeByDeclaration: Case[];

  beforeAll(() => {
    all = collectAppProject();
    batch5 = all.filter(isBatch5);
    nov14 = all.filter(isNov14);
    nov15 = all.filter(isNov15);
    motorStatutes = all.filter(isMotorStatute);
    compactMatter = all.filter(isCompactMatter);
    nov22 = all.filter(isNov22);
    nov24 = all.filter(isNov24);
    nov25 = all.filter(isNov25);
    canonical = all.filter(row => !isBatch5(row) && !isNov14(row) && !isNov15(row)
      && !isMotorStatute(row) && !isCompactMatter(row) && !isNov22(row) && !isNov24(row) && !isNov25(row));
    // Built-in JSON merges shared spec suites across projects. This named
    // projection preserves observed order inside each literal declaration.
    wholeByDeclaration = (Object.keys(appSourceProjects) as (keyof typeof appSourceProjects)[])
      .flatMap(project => canonicalAppProject(canonical, project));
  }, 20_000);

  it("keeps all774 original canonical identities, project order and zero retry/repeat", () => {
    expect(canonical).toHaveLength(774);
    expect(counts(canonical.map(row => row.project))).toEqual(appSourceProjects);
    expect(wholeByDeclaration.map(row => row.project)).toEqual([
      ...Array<string>(719).fill("app-chromium"), ...Array<string>(55).fill("app-mobile"),
    ]);
    expect(new Set(canonical.map(row => row.id)).size).toBe(774);
    expect(canonical.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(canonical.every(row => !path.isAbsolute(row.file) && !row.file.split("/").includes(".."))).toBe(true);
    expect(canonical.filter(row => row.file === "control-crawl-contract.spec.ts")
      .map(row => [row.project, row.titles])).toEqual([
      ["app-chromium", ["control-crawl-contract.spec.ts",
        "control audit follows fieldset, first-legend and option-group disabled states"]],
    ]);
    expect(canonical.filter(row => row.file === "watch-acl-query-states.spec.ts")
      .map(row => [row.project, row.titles])).toEqual([
      ["app-chromium", ["watch-acl-query-states.spec.ts",
        "Watch removes revoked source evidence from the workspace and report after reload"]],
    ]);
  });

  for (const project of Object.keys(appSourceProjects) as (keyof typeof appSourceProjects)[]) {
    const count = appSourceProjects[project];
    it(`collects exactly the ordered canonical ${project} subset without filters`, () => {
      const native = collectAppProject(project);
      expectAppSelection(native, canonicalAppProject(all, project));
      const selected = native.filter(
        row => !isBatch5(row) && !isNov14(row) && !isNov15(row)
          && !isMotorStatute(row) && !isCompactMatter(row) && !isNov22(row) && !isNov24(row) && !isNov25(row),
      );
      expect(selected).toHaveLength(count);
      expectAppSelection(selected, canonicalAppProject(canonical, project));
    }, 20_000);
  }

  it("forms an exact disjoint719+55 ordered union with the original mobile tag boundary", () => {
    const chromium = canonicalAppProject(canonical, "app-chromium");
    const mobile = canonicalAppProject(canonical, "app-mobile");
    expect(chromium.every(row => !row.titles.join(" ").includes("[mobile]"))).toBe(true);
    expect(mobile.every(row => row.titles.join(" ").includes("[mobile]"))).toBe(true);
    expect([...chromium, ...mobile].map(appIdentity)).toEqual(wholeByDeclaration.map(appIdentity));
    expect(new Set(wholeByDeclaration.map(row => row.id))).toEqual(new Set(canonical.map(row => row.id)));
    const desktopIds = new Set(chromium.map(row => row.id));
    expect(mobile.every(row => !desktopIds.has(row.id))).toBe(true);
  });

  it("requires all six Nov14 identities outside the unchanged774 and ten B5 cases", () => {
    expectNov14(nov14);
    expect(canonical.length + batch5.length + nov14.length + nov15.length).toBe(792);
    expect(counts(nov14.map(row => row.project))).toEqual({ "app-chromium": 3, "app-mobile": 3 });
  });

  it("requires both exact Nov15 format journeys outside the unchanged prior cohorts", () => {
    expectNov15(nov15);
    expect(counts(nov15.map(row => row.project))).toEqual({ "app-chromium": 1, "app-mobile": 1 });
    expect(counts([...canonical, ...batch5, ...nov14, ...nov15].map(row => row.project)))
      .toEqual({ "app-chromium": 728, "app-mobile": 64 });
  });

  it("keeps all seven Motor Vehicles source batches and every original App case", () => {
    expect(motorStatutes.map(row => [row.project, row.file, row.titles])).toEqual(
      motorStatuteTitles.map(title => ["app-chromium", motorStatuteFile, [motorStatuteFile, title]]),
    );
    expect(new Set(motorStatutes.map(row => row.id)).size).toBe(7);
    expect(motorStatutes.every(row => row.retries === 0 && row.repeat === 0
      && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
    expect(counts([...canonical, ...batch5, ...nov14, ...nov15, ...motorStatutes].map(row => row.project)))
      .toEqual({ "app-chromium": 735, "app-mobile": 64 });
  });

  it("requires the two populated Matter disclosures in their native projects", () => {
    expect(compactMatter.map(row => JSON.stringify([row.project, row.file, row.titles])).sort()).toEqual([
      JSON.stringify(["app-chromium", "matter-compact-cards.spec.ts", ["matter-compact-cards.spec.ts", "BUG-016 compact Matter cards", "populated counsel and bench disclosures"]]),
      JSON.stringify(["app-mobile", "matter-compact-cards.spec.ts", ["matter-compact-cards.spec.ts", "BUG-016 compact Matter cards", "[mobile] populated counsel and bench disclosures"]]),
    ]);
    expect(new Set(compactMatter.map(row => row.id)).size).toBe(2);
    expect(compactMatter.every(row => row.retries === 0 && row.repeat === 0
      && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
    const reviewed = [...canonical, ...batch5, ...nov14, ...nov15, ...motorStatutes, ...compactMatter, ...nov22, ...nov24, ...nov25];
    expect(new Set(reviewed.map(row => row.id))).toEqual(new Set(all.map(row => row.id)));
    expect(new Set(all.map(row => row.id)).size).toBe(all.length);
    expect(counts(reviewed.map(row => row.project))).toEqual({ "app-chromium": 767, "app-mobile": 70 });
  });

  it("requires every exact Nov22 release identity outside the unchanged prior cohorts", () => {
    expect(nov22.map(row => JSON.stringify([row.project, row.titles])).sort())
      .toEqual([...nov22Keys].sort());
    expect(new Set(nov22.map(row => row.id)).size).toBe(nov22Cases.length);
    expect(nov22.every(row => row.retries === 0 && row.repeat === 0 && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
    expect(counts([...canonical, ...batch5, ...nov14, ...nov15, ...nov22].map(row => row.project)))
      .toEqual({ "app-chromium": 731, "app-mobile": 65 });
  });

  it("requires every exact Nov24 workbook identity outside the unchanged prior cohorts", () => {
    expect(nov24.map(row => JSON.stringify([row.project, row.titles])).sort())
      .toEqual([...nov24Keys].sort());
    expect(new Set(nov24.map(row => row.id)).size).toBe(nov24Cases.length);
    expect(nov24.every(row => row.retries === 0 && row.repeat === 0 && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
    expect(counts(nov24.map(row => row.project))).toEqual({ "app-chromium": 11, "app-mobile": 2 });
  });

  it("requires every exact Nov25 workbook identity and Constitution source batch outside the prior cohorts", () => {
    expect(nov25.map(row => JSON.stringify([row.project, row.titles])).sort())
      .toEqual([...nov25Keys].sort());
    expect(new Set(nov25.map(row => row.id)).size).toBe(nov25Cases.length);
    expect(nov25.every(row => row.retries === 0 && row.repeat === 0 && row.results.length === 0 && row.expectedStatus === "passed")).toBe(true);
    expect(counts(nov25.map(row => row.project))).toEqual({ "app-chromium": 17, "app-mobile": 2 });
  });

  it("reconciles every additive B5 identity with its dedicated exact-production role", () => {
    const present = batch5Files.filter(file => existsSync(path.join(root, "tests/e2e", file)));
    if (present.length === 0) {
      // Configuration-only preparation is not evidence that B5 journeys ran.
      expect(batch5).toEqual([]);
      return;
    }
    expect(present).toEqual(batch5Files);
    expect(batch5).toHaveLength(8 + 2);
    expect(canonical.length + batch5.length).toBe(774 + 8 + 2);
    expect(counts(batch5.map(row => row.project))).toEqual({ "app-chromium": 5, "app-mobile": 5 });
    for (const project of Object.keys(appSourceProjects)) {
      expect(counts(batch5.filter(row => row.project === project).map(row => row.file))).toEqual({
        "ram-2026-11-11-statutes.spec.ts": 1, "ram-2026-11-11-drafting.spec.ts": 1,
        "ram-2026-11-11-contracts.spec.ts": 1, "ram-2026-11-11-bugs.spec.ts": 2,
      });
    }
    expectBatch5BugsProofs(batch5);
    expect(new Set(batch5.map(row => row.id)).size).toBe(batch5.length);
    expect(batch5.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(new Set(batch5.filter(row => row.project === "app-chromium").map(row => row.file))).toEqual(new Set(batch5Files));
    expect(batch5.filter(row => row.file === batch5Files[0] && row.project === "app-mobile").length).toBeGreaterThan(0);
    const dedicated = collectProjects({ "batch5-prod-chromium": 7, "batch5-prod-mobile": 7 });
    expect(counts(dedicated.map(row => row.project))).toEqual({
      "batch5-prod-chromium": 7, "batch5-prod-mobile": 7,
    });
    const production = dedicated.filter(isBatch5);
    expect(production).toHaveLength(8 + 2);
    expectBatch5BugsProofs(production);
    const identity = (row: Case) => JSON.stringify([
      row.file, row.titles, row.project.endsWith("mobile") ? "mobile" : "desktop", row.repeat, row.retries,
    ]);
    expect(production.every(row => isBatch5(row) && row.results.length === 0)).toBe(true);
    expect(production.map(identity).sort()).toEqual(batch5.map(identity).sort());
    expect(production.every(row => row.titles.join(" ").includes("[mobile]") === row.project.endsWith("mobile"))).toBe(true);
  }, 20_000);

});

describe("App metadata constructor and source-order controls", () => {
  it.each([
    ["Windows", 'MODULE 1234: load "C:\\\\owned\\\\node_modules\\\\zod\\\\v4\\\\index.cjs" for module "schema"'],
    ["POSIX", 'MODULE 1234: load "/owned/node_modules/zod/v4/index.cjs" for module "schema"'],
  ])("rejects eager application schemas in native %s metadata without retry", (_platform, stderr) => {
    let calls = 0;
    const execute: MetadataConstructor = (_command, args, options) => {
      calls++;
      expect(args).toContain("--list");
      expect(options.timeout).toBe(15_000);
      expect(options.env?.NODE_DEBUG).toBe("module");
      return { status: 0, stderr, stdout: JSON.stringify({ errors: [], suites: [], config: { projects:
        Object.keys(appSourceProjects).map(name => ({ id: name, name, retries: 0, repeatEach: 1 })),
      } }) };
    };
    expect(() => collectAppProject(undefined, execute)).toThrow("App metadata must defer runtime application schemas");
    expect(calls).toBe(1);
  });

  it("retains successful native module diagnostics without treating stderr as failure", () => {
    let calls = 0;
    const execute: MetadataConstructor = () => {
      calls++;
      return { status: 0, stderr: 'MODULE 1234: load "/owned/node_modules/playwright/lib/common/index.js" for module "runner"',
        stdout: JSON.stringify({ errors: [], suites: [], config: { projects:
          Object.keys(appSourceProjects).map(name => ({ id: name, name, retries: 0, repeatEach: 1 })),
        } }) };
    };
    const rows = collectAppProject(undefined, execute);
    expect(rows).toEqual([]);
    expect(calls).toBe(1);
  });

  it("bounds long native diagnostic paths without overlapping matcher work", () => {
    let calls = 0;
    const execute: MetadataConstructor = () => {
      calls++;
      return { status: 0, stderr: 'MODULE 1234: load "' + "/".repeat(50_000) + 'unrelated.cjs" for module "runner"',
        stdout: JSON.stringify({ errors: [], suites: [], config: { projects:
          Object.keys(appSourceProjects).map(name => ({ id: name, name, retries: 0, repeatEach: 1 })),
        } }) };
    };
    const started = performance.now();
    const rows = collectAppProject(undefined, execute);
    const elapsed = performance.now() - started;
    expect(rows).toEqual([]);
    expect(calls).toBe(1);
    expect(elapsed).toBeLessThan(1000);
  });

  it.each(["timeout", "nonzero"] as const)(
    "rejects native App discovery %s without retry or accepting a JSON prefix", failure => {
      let calls = 0;
      const execute: MetadataConstructor = (_command, args, options) => {
        calls++;
        expect(args).toContain("--list");
        expect(options.timeout).toBe(15_000);
        return {
          error: failure === "timeout" ? Object.assign(new Error("bounded native discovery"), { code: "ETIMEDOUT" }) : undefined,
          status: failure === "timeout" ? null : 1,
          stderr: "",
          // A valid prefix must never turn an incomplete constructor into
          // an accepted empty inventory, even if its schema would parse.
          stdout: JSON.stringify({ errors: [], suites: [], config: { projects:
            Object.keys(appSourceProjects).map(name => ({ id: name, name, retries: 0, repeatEach: 1 })),
          } }),
        };
      };
      expect(() => collectAppProject(undefined, execute)).toThrow();
      expect(calls).toBe(1);
    },
  );

  it.each(["title", "missing", "duplicate", "project", "repeat", "retry", "executed", "expected-skip"])(
    "Nov15 exact format identities reject %s", damage => {
      const rows: Case[] = nov15Cases.map(([project, file, title], index) => ({
        id: `nov15-${index}`, project, file, titles: [file, title], repeat: 0, retries: 0, results: [], expectedStatus: "passed",
      }));
      if (damage === "title") rows[0].titles[1] += " changed";
      else if (damage === "missing") rows.pop();
      else if (damage === "duplicate") rows[1] = rows[0];
      else if (damage === "project") rows[0].project = "app-mobile";
      else if (damage === "repeat") rows[0].repeat = 1;
      else if (damage === "retry") rows[0].retries = 1;
      else if (damage === "executed") rows[0].results = [{ status: "passed" }];
      else rows[0].expectedStatus = "skipped";
      expect(() => expectNov15(rows)).toThrow();
    },
  );
  it.each(["title", "missing", "duplicate", "project", "repeat", "retry", "executed", "foreign", "expected-skip"])(
    "Nov14 exact identities reject %s", damage => {
      const rows: Case[] = nov14Cases.map(([project, file, title], index) => ({
        id: `nov14-${index}`, project, file, titles: [file, title], repeat: 0, retries: 0, results: [], expectedStatus: "passed",
      }));
      if (damage === "title") rows[0].titles[1] += " changed";
      else if (damage === "missing") rows.pop();
      else if (damage === "duplicate") rows[1] = rows[0];
      else if (damage === "project") rows[0].project = "app-mobile";
      else if (damage === "repeat") rows[0].repeat = 1;
      else if (damage === "retry") rows[0].retries = 1;
      else if (damage === "executed") rows[0].results = [{ status: "passed" }];
      else if (damage === "expected-skip") rows[0].expectedStatus = "skipped";
      else rows[0].file = `other/${rows[0].file}`;
      expect(() => expectNov14(rows)).toThrow();
    },
  );
  it.each(["renamed", "duplicate-comms", "swapped-scope", "both-scopes", "missing-scope"])(
    "rejects %s in the four exact mixed-file proof identities", damage => {
      const rows: Case[] = batch5BugsProofCases.map(([title, scope]) => ({
        id: title, file: batch5BugsFile, titles: [batch5BugsFile, title],
        project: title.startsWith("[mobile]") ? "app-mobile" : "app-chromium",
        repeat: 0, retries: 0, results: [],
        annotations: [{ type: "caseops-b5-proof", description: scope }],
      }));
      if (damage === "renamed") rows[2].titles[1] += " changed identity";
      else if (damage === "duplicate-comms") {
        rows[2].titles = [...rows[0].titles];
        rows[2].annotations = [...rows[0].annotations!];
      } else if (damage === "swapped-scope") rows[2].annotations![0].description = "preview-no-paid-guard";
      else if (damage === "both-scopes") rows[2].annotations!.push({ type: "caseops-b5-proof", description: "preview-no-paid-guard" });
      else rows[2].annotations = [];
      expect(() => expectBatch5BugsProofs(rows)).toThrow();
    },
  );

  it("rejects an extra project returned by the selected native constructor without filtering it away", () => {
    const suites: NativeSuite[] = [{ title: "nested/spec.ts", specs: [{
      id: "source-id", file: "nested/spec.ts", title: "literal case", tests: [
        { projectId: "app-chromium", projectName: "app-chromium", repeatEachIndex: 0, retries: 0, results: [] },
        { projectId: "app-mobile", projectName: "app-mobile", repeatEachIndex: 0, retries: 0, results: [] },
      ],
    }] }];
    const execute: MetadataConstructor = (_command, args, options) => {
      expect(args).toContain("--project=app-chromium");
      expect(args).toContain("--list");
      expect(options.timeout).toBe(15_000);
      return { status: 0, stderr: "", stdout: JSON.stringify({ errors: [], suites, config: { projects:
        Object.keys(appSourceProjects).map(name => ({ id: name, name, retries: 0, repeatEach: 1 })),
      } }) };
    };
    const rows = collectAppProject("app-chromium", execute);
    expect(rows).toHaveLength(2);
    expect(rows[0].file).toBe("nested/spec.ts");
    expect(() => expectAppSelection(rows, [rows[0]])).toThrow();
  });

  function projectionFixture() {
    const row = (id: string, file: string, title: string, project = "app-mobile"): Case => ({
      id, file, titles: [file, title], project, repeat: 0, retries: 0, results: [],
    });
    return [
      row("desktop", "a.spec.ts", "desktop source", "app-chromium"),
      row("root-file", "a.spec.ts", "mobile root file"),
      row("other", "other/same.spec.ts", "same basename in other directory"),
      row("registered-B", "a/same.spec.ts", "Z title registered first"),
      row("registered-A", "a/same.spec.ts", "A title registered second"),
    ];
  }

  it("projects full relative directory order while preserving each file's registration order", () => {
    const canonical = projectionFixture();
    const originalIds = canonical.map(row => row.id);
    const projected = canonicalAppProject(canonical, "app-mobile");
    expect(projected.map(row => row.id)).toEqual(["registered-B", "registered-A", "root-file", "other"]);
    expect(canonical.map(row => row.id)).toEqual(originalIds);
    expect(new Set(projected.map(row => row.id))).toEqual(new Set(canonical.filter(row => row.project === "app-mobile").map(row => row.id)));
    expectAppSelection(projected, [canonical[3], canonical[4], canonical[1], canonical[2]]);
  });

  it.each(["swapped-files", "within-file-order", "missing", "foreign", "same-basename-other-directory"])(
    "rejects %s in selected raw rows without repairing their sequence", damage => {
      const canonical = projectionFixture();
      const expected = canonicalAppProject(canonical, "app-mobile");
      const actual = expected.map(row => ({ ...row, titles: [...row.titles] }));
      if (damage === "swapped-files") [actual[2], actual[3]] = [actual[3], actual[2]];
      else if (damage === "within-file-order") [actual[0], actual[1]] = [actual[1], actual[0]];
      else if (damage === "missing") actual.pop();
      else if (damage === "foreign") actual[0] = canonical[0];
      else actual[0] = { ...actual[0], file: "other/same.spec.ts" };
      expect(() => expectAppSelection(actual, expected)).toThrow();
    },
  );
});

describe("reviewed production tester source inventory", () => {
  let cases: Case[];

  beforeAll(() => { cases = collectProjects(projects); });

  it("collects reviewed115+6+55 QA roles with four reference cases but no local draft generation", () => {
    expect(counts(cases.map(row => row.project))).toEqual(projects);
    expect(cases).toHaveLength(176);
    expectNov14(cases, true);
    expect(cases.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(cases.filter(row => row.file === "ram-2026-10-22-prod.spec.ts")
      .map(row => ({ project: row.project, title: row.titles.at(-1) }))).toEqual([{
        project: "test-legal-write-prod-chromium",
        title: "NOTES22 newest three of four saved notes persist after reload at 1280px and 393px",
      }]);
  });

  it("preserves all four Nov7 workspace journeys in the test-legal B5 roles", () => {
    const moved = collectProjects({ "batch5-prod-chromium": 0, "batch5-prod-mobile": 0 })
      .filter(row => /ram-2026-11-07-(?:contracts|teams)\.spec\.ts$/.test(row.file));
    const expected = [
      ["ram-2026-11-07-contracts.spec.ts", "AI-CON-01 table-cell tracked changes retain source bytes and survive workspace reload"],
      ["ram-2026-11-07-teams.spec.ts", "AI-TEAM-01 membership and audited lead changes persist after reload"],
    ].flatMap(([file, title]) => [
      ["batch5-prod-chromium", file, title], ["batch5-prod-mobile", file, `[mobile] ${title}`],
    ]);
    expect(moved.map(row => [row.project, row.file, row.titles.at(-1)]).sort()).toEqual(expected.sort());
    expect(moved.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(cases).toHaveLength(176);
    expect(cases.filter(row => !isNov14(row)).length + moved.length).toBe(176);
    expect(cases.some(row => /ram-2026-11-07-(?:contracts|teams)\.spec\.ts$/.test(row.file))).toBe(false);
  });

  it("routes the Notes mutation to the project matching its unchanged production tenant guard", () => {
    const notes = cases.filter(row => row.file === "ram-2026-10-22-prod.spec.ts");
    expect(notes).toHaveLength(1);
    expect(notes[0].project).toBe("test-legal-write-prod-chromium");
    const source = readFileSync(path.join(root, "tests/e2e/ram-2026-10-22-prod.spec.ts"), "utf8");
    expect(source).toContain('if (!local && credentials.company_slug !== "test-legal")');
    expect(source).toContain('throw new Error("Production notes mutations are test-legal only.")');
  });

  it("routes all four official-reference cases to the serialized reporting principal", () => {
    const references = cases.filter(row => row.file === "ram-2026-11-14-prod.spec.ts");
    expect(references).toHaveLength(4);
    expect(references.every(row => row.project === "test-legal-write-prod-chromium")).toBe(true);
    expectNov14(references, true);
    const source = readFileSync(path.join(root, "tests/e2e/support/ram-bugs4.ts"), "utf8");
    expect(source).toContain('if (!local && credentials.slug !== "test-legal")');
    expect(source).toContain('throw new Error("Production batch-4 acceptance is test-legal only.")');
    expect(source).not.toContain("CASEOPS_IP_REFERENCE_PROD_");
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


  it("retains all51 dated identities plus four references in disjoint40+15 canonical order", () => {
    const dated = cases.filter(row => row.project === "test-legal-write-prod-chromium");
    const a = dated.filter(row => oct13AFiles.some(file => file === row.file));
    const b = dated.filter(row => oct13BFiles.some(file => file === row.file));
    expect(oct13AIdentities).toHaveLength(40);
    expect(oct13BIdentities).toHaveLength(15);
    expect(dated.filter(row => !isNov14(row))).toHaveLength(51);
    expect(a.map(datedIdentity)).toEqual(oct13AIdentities);
    expect(b.map(datedIdentity)).toEqual(oct13BIdentities);
    expect(dated.map(datedIdentity)).toEqual([...oct13AIdentities, ...oct13BIdentities]);
    expect(dated.map(row => row.id)).toEqual([...a, ...b].map(row => row.id));
    expect(new Set([...a, ...b].map(row => row.id)).size).toBe(55);
    expect(a.every(row => !b.some(other => other.id === row.id))).toBe(true);
    expect([...new Set(a.map(row => row.file))]).toEqual(oct13AFiles);
    expect([...new Set(b.map(row => row.file))]).toEqual(oct13BFiles);
    expect([...oct13AFiles, ...oct13BFiles]).toEqual(Object.keys(datedFiles));
    expect(new Set([...oct13AFiles, ...oct13BFiles]).size).toBe(9);
    expect(counts(a.map(row => row.file))).toEqual({
      "ram-2026-10-13-hearings.spec.ts": 2,
      "ram-2026-10-13-ip-portfolio.spec.ts": 4,
      "ram-2026-10-15-ip-controls.spec.ts": 34,
    });
    expect(counts(b.map(row => row.file))).toEqual({
      "ram-2026-10-15-ip-renewal-tracker.spec.ts": 2,
      "ram-2026-10-17-calendar-readiness.spec.ts": 2,
      "ram-2026-10-17-ip-reminders.spec.ts": 4,
      "ram-2026-10-17-ip-tracker.spec.ts": 2,
      "ram-2026-10-22-prod.spec.ts": 1,
      "ram-2026-11-14-prod.spec.ts": 4,
    });
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


describe.each(oct13Parts)("$invocation fixed native source inventory", part => {
  let cases: Case[];

  // Each subset has its own original8s native collection bound. The unfiltered
  // canonical project preserves the original51 plus four reporting references.
  beforeAll(() => {
    cases = collectProjects({ "test-legal-write-prod-chromium": part.count }, part.files);
  });

  it("discovers its complete whole-file group once in canonical order without retries or repeats", () => {
    expect(counts(cases.map(row => row.project))).toEqual({ "test-legal-write-prod-chromium": part.count });
    expect(cases).toHaveLength(part.count);
    expect(cases.map(datedIdentity)).toEqual(part.identities);
    expect([...new Set(cases.map(row => row.file))]).toEqual(part.files);
    expect(new Set(cases.map(row => row.id)).size).toBe(part.count);
    expect(cases.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
  });
});

describe("separate mandatory Batch3 production source inventory", () => {
  let cases: Case[];

  // Preserve the original collection budget; do not import the full historical
  // partition again to collect these three independently admitted projects.
  beforeAll(() => { cases = collectProjects(batch3Projects); });

  it("collects one exact positive case per role without local-only journeys", () => {
    expect(counts(cases.map(row => row.project))).toEqual(batch3Projects);
    expect(cases.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(new Set(cases.map(row => row.id)).size).toBe(3);
    expect(cases.map(row => [row.project, row.file, row.titles.at(-1)]).sort()).toEqual([
      ["batch3-clients-prod-chromium", "ram-2026-10-22-bugs.spec.ts",
        "B3-CLIENT-01/02/03 contact edits preserve retained verified KYC and matter links"],
      ["batch3-clients-prod-mobile", "ram-2026-10-22-bugs.spec.ts",
        "[mobile] B3-CLIENT-06 verified-client contact editing persists at 393px"],
      ["batch3-drafts-readonly-prod-chromium", "ram-2026-10-22-drafting.prod.spec.ts",
        "B3-DRAFT-PROD read-only retained finalized and mutable Appeal controls persist after reload"],
    ].sort());
    expect(cases.every(row => !row.titles.some(title => title.includes("[local-only]")))).toBe(true);
  });
});

const batch4Projects = {
  "batch4-prod-chromium": 36,
  "batch4-prod-mobile": 14,
  "batch4-governance-prod-chromium": 2,
  "batch4-governance-prod-mobile": 2,
};
const batch4Governance = "ram-2026-10-31-governance-ui.spec.ts";
// The adjacent-defect picker journey is the one 2026-11-01 spec prod-ram runs.
const batch4File = (name: string) => `ram-2026-${name.startsWith("adj-") ? "11-01" : "10-31"}-${name}.spec.ts`;
const crawlRoutes = [
  "/app/ip", "/app/ip Documents tab", "/app/ip/portfolio", "/app/ip/renewals", "/app/ip/madrid", "/app/ip/recordals",
  "/app/ip/foreign-associates", "/app/ip/registry", "/app/ip/watch", "/app/ip/reports", "/app/ip/client-portal",
  "/app/ip/patents", "/app/ip/specialist", "/app/calendar", "/app/admin/matter-billing",
  "/app/drive", "/app/mailbox", "/app/calendar/conflicts", "/app/admin/notifications",
  "/app/ip reported docket",
  "/app/matters reported Matter billing",
];
const batch4Titles: Record<string, [string, string][]> = {
  "batch4-prod-chromium": [
    ["calendar-year", "ENH-017 Year view shows Ram's UI-created hearing and task on their days in distinct colours and survives reload"],
    ...crawlRoutes.map((route): [string, string] => ["control-crawl", `BUG-015 controls on ${route} are usable or explain themselves`]),
    ["docket-sweep", "DOCKET-SWEEP calendar-copy reviews: the daily docket counts every pending review the server reports, not the first 100"],
    ["fixture-honesty", "BUG-002 Ram's Documents Classification is provisioned, never seeded, and previews a classified name"],
    ["foreign-associates", "BUG-009/010/011/013 Ram walks a new instruction from every empty picker to a created and retired instruction"],
    ["invoice-pdf", "BUG-016 draft invoice PDF downloaded from the billing page is legible, one page and marked DRAFT"],
    ["invoice-pdf", "BUG-016 [prod-only] the reported invoices INVR-2026-028 and INVR-2026-068 download legible (read-only)"],
    ["ip-create", "BUG-001 BUG-002 Ram creates a two-class trademark that opens in view and records its Nice edition"],
    ["madrid-portal", "BUG-015 Madrid: Ram records an outbound IR choosing the basic mark docket through the picker"],
    ["madrid-portal", "BUG-015 client portal: every offered grant loads its shareable versions or says why there are none"],
    ["madrid-portal", "BUG-015 sweep: Madrid, client portal, renewals and reports ask for no internal record ID"],
    ["matter-links", "BUG-007 Ram finds a Matter by typing among 60+ Matters, links it and retires it at 1440x900"],
    ["recordals", "BUG-008 Ram uploads an instrument from the recordal form and both parties cite it"],
    ["registry", "BUG-012 Ram finds a docket beyond the first 50 by its number and records manual registry evidence through structured fields"],
    ["watch", "BUG-014 journal capture: 'Class 45' with captured evidence is recorded, listed and shown on the hit; a bad class token is refused at its field"],
    ["adj-pickers", "B4-ADJ-02 review queues find the Matter by typing and name it, never by id, at 1440x900"],
  ],
  "batch4-prod-mobile": [
    ["calendar-year", "ENH-017 [mobile] Year view opens on screen in one column at 375 px, keeps chips legible, and opens a day"],
    ["docket-sweep", "[mobile] DOCKET-SWEEP calendar-copy reviews: the count and list state fit at 393px without horizontal page scroll"],
    ["fixture-honesty", "BUG-002 [mobile] Classification and its upload gate stay on screen without horizontal scroll"],
    ["foreign-associates", "[mobile] BUG-009/010/011/013 Ram walks the new instruction, records the quote and creates it at 393px"],
    ["invoice-pdf", "BUG-016 [mobile] draft invoice PDF journey works at 393px without page overflow"],
    ["invoice-pdf", "BUG-016 [prod-only] [mobile] the reported invoices download legible at 393px (read-only)"],
    ["ip-create", "BUG-001 BUG-002 [mobile] Ram creates a two-class trademark on a phone without horizontal scroll"],
    ["madrid-portal", "BUG-015 Madrid [mobile]: intake pickers fit a phone and never offer a dead choice"],
    ["madrid-portal", "BUG-015 client portal [mobile]: grant and publish controls fit a phone"],
    ["matter-links", "BUG-007 [mobile] Ram finds, links and retires a Matter on a phone without overflow"],
    ["recordals", "BUG-008 [mobile] the recordal journey works at Pixel 5 width without horizontal scroll"],
    ["registry", "BUG-012 [mobile] the registry journey works at phone width without horizontal scroll"],
    ["watch", "[mobile] BUG-014 journal capture works at 393px without horizontal page scroll"],
    ["adj-pickers", "B4-ADJ-02 [mobile] review queue Matter pickers fit a phone and name the Matter"],
  ],
  "batch4-governance-prod-chromium": [
    ["governance-ui", "BUG-003/004 opposition governed-rule and calendar pickers are never dead selects"],
    ["governance-ui", "BUG-005/006 Ram proposes a calendar and sees the honest pending-approval state"],
  ],
  "batch4-governance-prod-mobile": [
    ["governance-ui", "[mobile] BUG-003/004 opposition picker reasons and governance link fit 393px"],
    ["governance-ui", "[mobile] BUG-005 governance card controls fit 393px with a computed source hash"],
  ],
};

describe("separate mandatory Batch4 production source inventory", () => {
  let cases: Case[];

  beforeAll(() => { cases = collectProjects(batch4Projects); });

  it("collects every production-eligible case per role exactly, with local-only journeys excluded", () => {
    expect(counts(cases.map(row => row.project))).toEqual(batch4Projects);
    expect(cases.every(row => row.results.length === 0 && row.retries === 0 && row.repeat === 0)).toBe(true);
    expect(new Set(cases.map(row => row.id)).size).toBe(54);
    for (const [project, titles] of Object.entries(batch4Titles)) {
      expect(cases.filter(row => row.project === project).map(row => [row.file, ...row.titles.slice(1)]).sort())
        .toEqual(titles.map(([file, title]) => [batch4File(file), title]).sort());
    }
    expect(cases.every(row => !row.titles.some(title => title.includes("[local-only]")))).toBe(true);
  });

  it("keeps the governance spec out of the always-on roles and splits desktop from mobile", () => {
    for (const row of cases) {
      expect(row.file === batch4Governance, row.project).toBe(row.project.startsWith("batch4-governance-"));
      expect(row.titles.at(-1)!.includes("[mobile]"), row.project).toBe(row.project.endsWith("-mobile"));
    }
    const projectFiles = new Set(cases.filter(row => !row.project.startsWith("batch4-governance-")).map(row => row.file));
    expect(projectFiles.has(batch4Governance)).toBe(false);
    expect(projectFiles.size).toBe(13);
  });
});
