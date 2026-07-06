import { defineConfig } from "@playwright/test";

import appConfig from "./playwright.app.config";

export default defineConfig({
  ...appConfig,
  globalSetup: undefined,
  webServer: undefined,
});
