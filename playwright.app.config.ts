import fs from "node:fs";
import path from "node:path";

import { defineConfig, devices } from "@playwright/test";

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
    /intake\.spec\.ts/,
    /teams-admin\.spec\.ts/,
    /contracts-detail\.spec\.ts/,
    /matter-hearings\.spec\.ts/,
    /research\.spec\.ts/,
    /billing-payment\.spec\.ts/,
    /hari-ii-bugs\.spec\.ts/,
    /matter-outside-counsel\.spec\.ts/,
    /mobile-responsive\.spec\.ts/,
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
    // Strict Ledger #6 (2026-04-22): mobile-responsive bugs (Ram-004,
    // Ram-005, Ram-006) had only desktop coverage; the bug-fixing
    // skill rejects desktop-only proof for mobile bugs. This project
    // runs the dedicated `mobile-responsive.spec.ts` against a
    // Pixel-5 emulated viewport (393x851, touch, Mobile Chrome UA).
    // Pixel-5 is Chromium-based so we can re-use the same browser
    // pool the desktop project uses; iPhone-13 is WebKit and would
    // need a separate browser binary. Note we DO NOT pass the
    // browserExecutablePath override here — system Edge/Chrome
    // doesn't emulate touch the way Playwright's bundled Chromium
    // does.
    {
      name: "app-mobile",
      grep: /\[mobile\]/,
      testMatch: [/mobile-responsive\.spec\.ts/],
      use: {
        ...devices["Pixel 5"],
      },
    },
  ],
  webServer: [
    {
      // Invoke uvicorn directly from the venv — bypasses `uv run`'s
      // implicit sync step, which fails on Windows when another
      // long-running process (the corpus backfill, see Sprint 11
      // bucket scripts) holds a lock on a .venv/Scripts/*.exe.
      command:
        process.platform === "win32"
          ? "apps\\api\\.venv\\Scripts\\uvicorn.exe caseops_api.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api/src"
          : "apps/api/.venv/bin/uvicorn caseops_api.main:app --host 127.0.0.1 --port 8000 --app-dir apps/api/src",
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
