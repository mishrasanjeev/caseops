import fs from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

const configuredBaseUrl = process.env.CASEOPS_WEB_BASE_URL?.trim() || undefined;
const localBaseUrl = "http://127.0.0.1:3101";

export default defineConfig({
  testDir: path.join("tests", "e2e"),
  testMatch: /public-content\.spec\.ts/,
  outputDir: path.join("test-results", "public-content"),
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    extraHTTPHeaders: noPaidProviderHeaders,
    baseURL: configuredBaseUrl ?? localBaseUrl,
    headless: true,
    trace: "off",
    screenshot: "only-on-failure",
    video: "off",
  },
  projects: [
    {
      name: "public-content-chromium",
      use: {
        ...devices["Desktop Chrome"],
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
  ],
});
