import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

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
  testMatch: /marketing\.spec\.ts/,
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [["list"]],
  use: {
    baseURL: webBaseUrl,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "marketing-chromium",
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
      command: "npx next start --hostname 127.0.0.1 --port 3100",
      cwd: path.join(__dirname, "apps", "web"),
      url: "http://127.0.0.1:3100",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
