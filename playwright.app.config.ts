import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot } from "./tests/e2e/support/env";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

const webBaseUrl = process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:3100";

export default defineConfig({
  testDir: path.join("tests", "e2e"),
  testMatch: [/marketing\.spec\.ts/, /app-spine\.spec\.ts/, /a11y\.spec\.ts/],
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  globalSetup: path.join("tests", "e2e", "global-setup.ts"),
  reporter: [["list"]],
  use: {
    baseURL: webBaseUrl,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "app-chromium",
      use: {
        browserName: "chromium",
        ...(browserExecutablePath
          ? { launchOptions: { executablePath: browserExecutablePath } }
          : {}),
      },
    },
  ],
  webServer: [
    {
      command:
        "uv --directory apps/api run uvicorn caseops_api.main:app --host 127.0.0.1 --port 8000 --app-dir src",
      cwd: repoRoot,
      env: { ...process.env, ...e2eEnv },
      url: `${apiBaseUrl}/api/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npx next start --hostname 127.0.0.1 --port 3100",
      cwd: path.join(repoRoot, "apps", "web"),
      env: {
        ...process.env,
        ...e2eEnv,
        NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
      },
      url: webBaseUrl,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
