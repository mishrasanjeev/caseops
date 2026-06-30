import fs from "node:fs";

import { defineConfig } from "@playwright/test";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: [/functional-qa-regression\.spec\.ts/],
  fullyParallel: false,
  workers: 1,
  timeout: 240_000,
  expect: { timeout: 15_000 },
  reporter: [["list"]],
  use: {
    baseURL: process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:3100",
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "functional-qa-chromium",
      use: {
        browserName: "chromium",
        ...(browserExecutablePath
          ? { launchOptions: { executablePath: browserExecutablePath } }
          : {}),
      },
    },
  ],
});
