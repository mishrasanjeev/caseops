import { defineConfig } from "@playwright/test";
import base from "../../../playwright.docker.config";

export default defineConfig({
  ...base,
  testDir: "../../../tests/e2e",
  projects: [{ name: "patent-offline-chromium", use: {
    browserName: "chromium", launchOptions: { executablePath: "/usr/bin/chromium" },
  } }],
  use: { ...base.use, video: "off" },
  reporter: [["list"], ["junit", { outputFile: process.env.PLAYWRIGHT_JUNIT_OUTPUT_FILE }]],
});
