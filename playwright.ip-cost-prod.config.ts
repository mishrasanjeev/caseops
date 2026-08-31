/** Deployed IPLF-039F acceptance: no local server, database shell, or media. */
import fs from "node:fs";

import { defineConfig, devices } from "@playwright/test";

const candidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const executablePath = candidates.find((candidate) => fs.existsSync(candidate));

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /iplf-039f-cost-items-2026-08-30-prod\.spec\.ts$/,
  timeout: 240_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    ...devices["Desktop Chrome"],
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    storageState: { cookies: [], origins: [] },
    trace: "off",
    screenshot: "off",
    video: "off",
    launchOptions: executablePath ? { executablePath } : undefined,
  },
});
