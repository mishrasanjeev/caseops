import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

import { apiBaseUrl, e2eEnv, repoRoot, webBaseUrl } from "./tests/e2e/support/env";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

export default defineConfig({
  testDir: path.join("tests", "e2e"),
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  expect: {
    timeout: 15_000,
  },
  globalSetup: path.join("tests", "e2e", "global-setup.ts"),
  reporter: [
    ["list"],
    ["html", { open: "never" }],
  ],
  use: {
    baseURL: webBaseUrl,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "local-chromium",
      use: {
        browserName: "chromium",
        ...(browserExecutablePath
          ? {
              launchOptions: {
                executablePath: browserExecutablePath,
              },
            }
          : {}),
      },
    },
  ],
  webServer: [
    {
      command:
        "uv --directory apps/api run uvicorn caseops_api.main:app --host 127.0.0.1 --port 8000 --app-dir src",
      cwd: repoRoot,
      env: {
        ...process.env,
        ...e2eEnv,
      },
      url: `${apiBaseUrl}/api/health`,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
    {
      command: "npx next dev --turbopack --hostname 127.0.0.1 --port 3000",
      cwd: path.join(repoRoot, "apps", "web"),
      env: {
        ...process.env,
        ...e2eEnv,
        NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
      },
      url: webBaseUrl,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
    },
  ],
});
