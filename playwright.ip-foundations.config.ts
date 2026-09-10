import { defineConfig } from "@playwright/test";
import baseConfig from "./playwright.config";

export default defineConfig({
  ...baseConfig,
  testMatch: "iplf-028b-legal-holds-2026-09-09.spec.ts",
  reporter: [
    ["list"],
    ["json", { outputFile: `/output/${process.env.RUN_LABEL}.json` }],
    ["junit", { outputFile: `/output/${process.env.RUN_LABEL}.xml` }],
  ],
  outputDir: `/output/${process.env.RUN_LABEL}-artifacts`,
  use: { ...baseConfig.use, video: "off" },
  projects: [{
    name: "isolated-chromium",
    use: {
      browserName: "chromium",
      launchOptions: { executablePath: "/usr/bin/chromium" },
    },
  }],
  webServer: (Array.isArray(baseConfig.webServer) ? baseConfig.webServer : []).map((server, index) => ({
    ...server,
    ...(index === 1 ? { command: "node ../../node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 3000" } : {}),
    reuseExistingServer: false,
  })),
});
