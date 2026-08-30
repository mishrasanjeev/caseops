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
    // Docker Desktop on Windows can spend tens of seconds materializing the
    // first authenticated route after a clean image/volume reset. Keep this
    // local-only budget below the 120-second test ceiling; production uses its
    // dedicated latency assertions and exact-release configuration.
    actionTimeout: 60_000,
    baseURL: dockerWebBaseUrl,
  },
});
