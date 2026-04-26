/**
 * Standalone Playwright config for the Ram-batch production
 * verification spec. No local webServer — points entirely at the
 * deployed caseops.ai surface so we test the EXACT bytes Ram saw.
 */
import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const candidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const browserExecutablePath = candidates.find((c) => fs.existsSync(c));

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /ram-batch-2026-04-26-prod\.spec\.ts$/,
  timeout: 60_000,
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
      name: "prod-chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
  ],
});
