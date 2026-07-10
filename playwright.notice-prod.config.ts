import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

const candidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const browserExecutablePath = candidates.find((candidate) => fs.existsSync(candidate));

const QA_STORAGE_STATE = "tests/e2e/.auth/qa-storage.json";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /(notice-module-prod\.spec\.ts|qa-auth\.setup\.ts)$/,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    // This project runs against the live tenant. Text failures are retained,
    // but authenticated browser media must never become a CI artifact.
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
      name: "prod-notice-chromium",
      dependencies: ["setup"],
      testMatch: /notice-module-prod\.spec\.ts$/,
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
