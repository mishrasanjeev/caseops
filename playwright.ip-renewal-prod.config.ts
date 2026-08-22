import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: /iplf-037b-renewal-2026-08-22-prod\.spec\.ts$/,
  timeout: 300_000,
  expect: { timeout: 15_000 },
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
      name: "ip-renewal-prod",
      testMatch: /iplf-037b-renewal-2026-08-22-prod\.spec\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
      },
    },
  ],
});
