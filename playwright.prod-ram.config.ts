/**
 * Standalone Playwright config for the prod-verification spec. No
 * local webServer — points entirely at the deployed caseops.ai surface.
 *
 * Auth is isolated by project. Historical production specs sign in once via
 * tests/e2e/setup/qa-auth.setup.ts as the dedicated CaseOps QA Bot and reuse a
 * gitignored storage state. Canonical dated tester specs create an empty
 * browser context and authenticate explicitly with credentials supplied only
 * through environment variables.
 *
 * The filename keeps the historical "ram" prefix for backwards-compatibility
 * with existing CI workflow references.
 *
 * Skips the bootstrap-qa-workspace.setup.ts file at the project level
 * (it's a one-off; the prod workspace is already created).
 */
import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const candidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const browserExecutablePath = candidates.find((c) => fs.existsSync(c));

const QA_STORAGE_STATE = "tests/e2e/.auth/qa-storage.json";
const LEGACY_QA_PROD_SPECS =
  /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts|pg-004-today-cockpit-2026-05-01-prod\.spec\.ts|hari-2026-05-09-prod\.spec\.ts|hari-2026-05-09-bug-033-prod\.spec\.ts|hari-2026-05-09-outlook-sync-prod\.spec\.ts|hari-2026-05-09-bug-032-prod\.spec\.ts|hari-2026-07-02-prod\.spec\.ts)$/;
// New canonical dated specs own their authentication and start from an empty
// context. The two historical dated specs still depend on the QA storage state
// and therefore remain in LEGACY_QA_PROD_SPECS above.
const TESTER_AUTH_PROD_SPECS =
  /(?:^(?!.*(?:hari-2026-05-09-prod|hari-2026-07-02-prod)\.spec\.ts$).*(?:hari|ram)-\d{4}-\d{2}-\d{2}-prod\.spec\.ts$|.*ram-2026-08-(?:11|24)-bugs\.spec\.ts$|.*iplf-05(?:4b-indian-kanoon|6b-provider-operations)-2026-08-25-prod\.spec\.ts$)/;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch:
    /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts|pg-004-today-cockpit-2026-05-01-prod\.spec\.ts|hari-2026-05-09-prod\.spec\.ts|hari-2026-05-09-bug-033-prod\.spec\.ts|hari-2026-05-09-outlook-sync-prod\.spec\.ts|hari-2026-05-09-bug-032-prod\.spec\.ts|hari-2026-07-02-prod\.spec\.ts|(?:hari|ram)-\d{4}-\d{2}-\d{2}-prod\.spec\.ts|ram-2026-08-(?:11|24)-bugs\.spec\.ts|iplf-05(?:4b-indian-kanoon|6b-provider-operations)-2026-08-25-prod\.spec\.ts|qa-auth\.setup\.ts)$/,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    // Production traces, screenshots, and videos can capture authenticated
    // legal data and session-bearing requests. Keep failure diagnostics in
    // the text reporter; never persist browser media from the live tenant.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "setup",
      testMatch: /qa-auth\.setup\.ts$/,
      use: {
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "prod-chromium",
      dependencies: ["setup"],
      testMatch: LEGACY_QA_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: QA_STORAGE_STATE,
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "tester-prod-chromium",
      testMatch: TESTER_AUTH_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
  ],
});
