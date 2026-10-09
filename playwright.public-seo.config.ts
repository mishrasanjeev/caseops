import { defineConfig } from "@playwright/test";

import publicConfig from "./playwright.public-content.config";
import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

const publicBrowser = publicConfig.projects?.[0]?.use ?? {};

export default defineConfig({
  ...publicConfig,
  globalSetup: undefined,
  webServer: undefined,
  testMatch: [/public-content\.spec\.ts$/, /seo_demo_20261009\.spec\.ts$/],
  retries: 0,
  use: {
    ...publicConfig.use,
    extraHTTPHeaders: noPaidProviderHeaders,
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "public-content-chromium",
      testMatch: /public-content\.spec\.ts$/,
      use: publicBrowser,
    },
    {
      name: "public-seo-readonly-chromium",
      testMatch: /seo_demo_20261009\.spec\.ts$/,
      grep: /public CTA and truthful copy|public read-only prototype source rejection/,
      use: publicBrowser,
    },
  ],
});
