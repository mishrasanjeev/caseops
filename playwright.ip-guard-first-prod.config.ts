/**
 * Production-only API acceptance for IPLF-039C's guard-first release.
 *
 * This config deliberately has no webServer and no persisted browser state.
 * The spec authenticates explicitly, pins both deployed release identities,
 * requires a non-secret recovery run id, and refuses to mutate until the
 * dedicated-QA acknowledgement is present. Retries stay disabled so a failed
 * writer run cannot silently create a second fixture set.
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /iplf-039c-guard-first-2026-08-16-prod\.spec\.ts$/,
  timeout: 240_000,
  retries: 0,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    trace: "off",
    screenshot: "off",
    video: "off",
  },
});
