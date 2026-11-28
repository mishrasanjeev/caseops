import { defineConfig } from "@playwright/test";

import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

// J05/M04 research answer acceptance against the exact serving release.
// The no-paid marker routes the model call to the deterministic offline
// provider, so this proves the deployed retrieval, verification, ordering and
// UI contract without spending on a paid model. The BUG-001 layout journey
// measures the same deployed answer page's geometry on desktop, zoom and phone;
// the BUG-002/003/004 journey proves focus, duplicate safety, timing and the
// vague-question guidance as the reporting tester.
export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: [
    /research-answer-2026-11-24\.spec\.ts$/,
    /research-answer-layout-2026-11-26\.spec\.ts$/,
    /research-answer-2026-11-26\.spec\.ts$/,
  ],
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 240_000,
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
