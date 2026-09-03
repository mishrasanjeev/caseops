/**
 * Explicitly opt-in production verification for funded provider accounts.
 * This config intentionally does not install the no-paid-provider header.
 */
import fs from "node:fs";

import { defineConfig, devices } from "@playwright/test";

if (process.env.CASEOPS_ALLOW_LIVE_PAID_PROVIDER_TESTS !== "true") {
  throw new Error(
    "Set CASEOPS_ALLOW_LIVE_PAID_PROVIDER_TESTS=true for the bounded live-provider probe.",
  );
}

const browserExecutablePath = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
].find((candidate) => fs.existsSync(candidate));

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /paid-provider-live-2026-09-03-prod\.spec\.ts$/,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "paid-provider-live-chromium",
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
