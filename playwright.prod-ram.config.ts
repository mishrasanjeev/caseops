/**
 * Standalone Playwright config for the prod-verification spec. No
 * local webServer — points entirely at the deployed caseops.ai surface.
 *
 * Auth: signs in once via tests/e2e/setup/qa-auth.setup.ts as the
 * dedicated CaseOps QA Bot (workspace slug: caseops-qa). Storage state
 * is persisted to tests/e2e/.auth/qa-storage.json (gitignored). The
 * test infra has zero dependency on real-user accounts — see
 * feedback_dedicated_test_account_no_real_users.md.
 *
 * The filename keeps the historical "ram" prefix for backwards-compat
 * with existing CI workflow references; the underlying account is the
 * QA Bot workspace.
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

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts|qa-auth\.setup\.ts)$/,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
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
      testMatch: /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts)$/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: QA_STORAGE_STATE,
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
  ],
});
