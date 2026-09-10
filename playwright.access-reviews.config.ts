import { defineConfig } from "@playwright/test";
import baseConfig from "./playwright.ip-foundations.config";

export default defineConfig({ ...baseConfig, workers: 1, testMatch: "iplf-073b-access-reviews-2026-09-10.spec.ts" });
