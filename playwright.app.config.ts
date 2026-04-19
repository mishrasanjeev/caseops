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
  testMatch: [
    /marketing\.spec\.ts/,
    /app-spine\.spec\.ts/,
    /a11y\.spec\.ts/,
    /query-states\.spec\.ts/,
    /personas\.spec\.ts/,
    /drafting\.spec\.ts/,
    /bootstrap-and-upload\.spec\.ts/,
    /m2-polish\.spec\.ts/,
  ],
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
      // Always start a fresh API for the e2e suite. Reusing an existing
      // local dev server reuses ITS env (notably CASEOPS_CORS_ORIGINS),
      // which silently breaks the prod-build browser flow on port 3100
      // because the dev .env only allows :3000. Forcing fresh-start
      // keeps the e2e CORS list authoritative; if port 8000 is already
      // taken, Playwright errors loudly and the operator stops their
      // local dev API first — both behaviours we want.
      reuseExistingServer: false,
    },
    {
      command: "npx next start --hostname 127.0.0.1 --port 3100",
      cwd: path.join(repoRoot, "apps", "web"),
      env: {
        ...process.env,
        ...e2eEnv,
        NEXT_PUBLIC_API_BASE_URL: apiBaseUrl,
        // Tests assert the canonical URL + OG tags on the prod domain;
        // force the prod site URL so a local `.env.local` that points
        // NEXT_PUBLIC_SITE_URL at localhost doesn't leak into the
        // marketing spec.
        NEXT_PUBLIC_SITE_URL: "https://caseops.ai",
        NEXT_PUBLIC_APP_URL: "https://caseops.ai/app",
      },
      url: webBaseUrl,
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
