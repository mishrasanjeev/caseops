import fs from "node:fs";
import path from "node:path";

import { defineConfig } from "@playwright/test";

import {
  apiBaseUrl,
  e2eEnv,
  repoRoot,
  webBaseUrl,
} from "./tests/e2e/support/env";

const browserExecutableCandidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];

const browserExecutablePath = browserExecutableCandidates.find((candidate) =>
  fs.existsSync(candidate),
);

export default defineConfig({
  testDir: path.join("tests", "e2e"),
  // Live-tenant mutation canaries are permitted only through their dedicated
  // exact-release configs/workflows, never the general local entrypoint.
  testIgnore: [
    /iplf-027b-a0-quiescence-2026-08-14-prod\.spec\.ts$/,
    /iplf-039c-guard-first-2026-08-16-prod\.spec\.ts$/,
  ],
  fullyParallel: false,
  workers: 1,
  timeout: 120_000,
  // Stop after a handful of failures in CI.
  //
  // These specs run in one worker against one server, so a failure that leaves
  // the app or its data wedged takes every following test down with it. Without
  // a limit the suite grinds through each one to its 120s timeout: an observed
  // cascade starting at ram-2026-08-11-bugs.spec.ts:411 burned 25 minutes on
  // seven tests and hit the 30-minute job budget. A job killed by its budget is
  // reported as CANCELLED, so the reporter never finishes and the traces are
  // never uploaded - the run destroys the evidence of why it failed.
  //
  // Aborting early turns that into a normal failure with a report attached,
  // which is the difference between a diagnosable cascade and an invisible one.
  // Locally there is no limit, because a developer wants the whole picture.
  // Five was too high to help: the cascade's time is spent in HANGING teardown,
  // not in counted failures. Observed on run 32152575950 - test 136 took 5.1m
  // against a 120s test timeout with retries disabled, so ~3 minutes of it sits
  // outside the test body where maxFailures has no say. Two failures abort
  // early enough for the job to finish inside its budget and upload a trace,
  // which is the outcome that matters; capping the waste is secondary.
  maxFailures: process.env.CI ? 2 : 0,
  expect: {
    timeout: 15_000,
  },
  globalSetup: path.join("tests", "e2e", "global-setup.ts"),
  reporter: [["list"], ["html", { open: "never" }]],
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
        "uv --directory apps/api run --no-sync python -m uvicorn caseops_api.main:app --host 127.0.0.1 --port 8000 --app-dir src",
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
