/**
 * Isolated production config for the IPLF-027B A0 acceptance gate.
 *
 * It deliberately has no setup project or shared storage state. The spec owns
 * authentication to the synthetic caseops-ip-qa tenant, defaults to verify
 * mode, and requires an explicit mode override for the one-time predecessor
 * preparation command documented in the spec.
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /iplf-027b-a0-quiescence-2026-08-14-prod\.spec\.ts$/,
  timeout: 180_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "https://caseops.ai",
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "ip-a0-prod",
      testMatch: /iplf-027b-a0-quiescence-2026-08-14-prod\.spec\.ts$/,
      use: { storageState: { cookies: [], origins: [] } },
    },
  ],
});
