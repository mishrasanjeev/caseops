import { defineConfig } from "@playwright/test";

import appConfig from "./playwright.app.config";

const dockerWebBaseUrl =
  process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:13100";

export default defineConfig({
  ...appConfig,
  globalSetup: undefined,
  webServer: undefined,
  use: {
    ...appConfig.use,
    baseURL: dockerWebBaseUrl,
  },
});
