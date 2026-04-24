/**
 * Prod-smoke Playwright config (2026-04-24).
 *
 * Targets the live caseops.ai surface — clicks through every UI shipped
 * 2026-04-23 (Phase B calendar / clients restore / communications /
 * email templates / KYC) and 2026-04-24 (BUG-030 saved research).
 *
 * Bootstraps a fresh time-stamped tenant per run so the spec is
 * idempotent and never collides with other workspaces.
 *
 * Run:
 *   BASE_URL=https://caseops.ai npx playwright test --config=playwright.smoke.config.ts
 *
 * Default browser executable picks Edge or Chrome on Windows so the
 * spec works without a per-machine `playwright install` of all browsers.
 */
import fs from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

const baseURL = process.env.BASE_URL ?? "https://caseops.ai";

export default defineConfig({
  testDir: path.join("tests", "e2e", "smoke"),
  testMatch: [/prod\.spec\.ts/, /bug\d+-.*\.spec\.ts/],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL,
    headless: true,
    viewport: { width: 1280, height: 800 },
    ignoreHTTPSErrors: false,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    launchOptions: browserExecutablePath
      ? { executablePath: browserExecutablePath }
      : {},
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
