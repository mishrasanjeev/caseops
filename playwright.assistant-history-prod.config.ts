import { defineConfig } from "@playwright/test";

import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

// A missing genuine retained-history manifest fails the journey, never skips it.
// This read-only role cannot bootstrap production users or manufacture answers.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /ram-2026-11-07-assistant\.spec\.ts$/,
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 15_000 },
  reporter: "list",
  use: {
    browserName: "chromium",
    baseURL: "https://caseops.ai",
    extraHTTPHeaders: noPaidProviderHeaders,
    storageState: { cookies: [], origins: [] },
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
