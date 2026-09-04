/**
 * Explicitly opt-in production verification for provider readiness and the
 * CaseOps-recorded workspace budget balance. Billable provider calls remain
 * blocked by the automation marker.
 */
import fs from "node:fs";

import { defineConfig, devices } from "@playwright/test";

import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

if (process.env.CASEOPS_ALLOW_LIVE_PROVIDER_READONLY_TESTS !== "true") {
  throw new Error(
    "Set CASEOPS_ALLOW_LIVE_PROVIDER_READONLY_TESTS=true for the non-billable provider check.",
  );
}

const browserExecutablePath = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
].find((candidate) => fs.existsSync(candidate));

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /provider-nonbillable-live-2026-09-04-prod\.spec\.ts$/,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    extraHTTPHeaders: noPaidProviderHeaders,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "provider-nonbillable-live-chromium",
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
