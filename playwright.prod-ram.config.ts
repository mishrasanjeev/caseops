/**
 * Standalone Playwright config for the prod-verification spec. No
 * local webServer — points entirely at the deployed caseops.ai surface.
 *
 * Auth is isolated by project. Historical production specs sign in once via
 * tests/e2e/setup/qa-auth.setup.ts as the dedicated CaseOps QA Bot and reuse a
 * gitignored storage state. Canonical dated tester specs create an empty
 * browser context and authenticate explicitly with credentials supplied only
 * through environment variables.
 *
 * The filename keeps the historical "ram" prefix for backwards-compatibility
 * with existing CI workflow references.
 *
 * Skips the bootstrap-qa-workspace.setup.ts file at the project level
 * (it's a one-off; the prod workspace is already created).
 */
import { defineConfig, devices } from "@playwright/test";
import fs from "node:fs";

import { noPaidProviderHeaders } from "./tests/e2e/support/cost-controls";

process.env.PROD_BASE_URL ||= "https://caseops.ai";
process.env.PROD_API_BASE_URL ||= "https://api.caseops.ai";
const PATENT_PROD_SPECS = /iplf-(?:079b-domain-availability|080[ab]-patent-(?:family|application|parties|priorities|source-scope))-2026-09-0[67]\.spec\.ts$/;
const SAVED_MANIFEST_PROD_SPEC = /iplf-066c-saved-manifest-later-events-2026-09-29\.spec\.ts$/;
const OCT13_PORTFOLIO_CALENDAR_SPECS = /(?:ram-2026-10-13-(?:hearings|ip-portfolio)|ram-2026-10-15-ip-(?:controls|renewal-tracker)|ram-2026-10-17-ip-(?:tracker|reminders)|ram-2026-10-17-calendar-readiness)\.spec\.ts$/;
const RETAINED_INDEX_PROD_SPECS = /ram-2026-10-(?:10|12)-prod\.spec\.ts$/;
const PLATFORM_REPORT_ADMIN_PROD_SPECS = /platform-(?:report-admin|leads)-\d{4}-\d{2}-\d{2}\.prod\.spec\.ts$/;
const BATCH3_CLIENT_SPEC = /ram-2026-10-22-bugs\.spec\.ts$/;
const BATCH3_DRAFT_READONLY_SPEC = /ram-2026-10-22-drafting\.prod\.spec\.ts$/;
const NOTES22_PROD_SPEC = /ram-2026-10-22-prod\.spec\.ts$/;
// Batch 4 specs sign in as the reporting tester themselves and run the same
// journeys locally (app config) and here against the exact serving release.
const BATCH4_SPECS = /ram-2026-(?:10-31-[a-z0-9-]+|11-01-adj-pickers)\.spec\.ts$/;
// Rule-governance pickers and proposals (BUG-003..006) can pass in production only
// while governance is enabled, so they run as their own release-owned projects.
const BATCH4_GOVERNANCE_SPEC = /ram-2026-10-31-governance-ui\.spec\.ts$/;

const candidates = [
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
];
const browserExecutablePath = candidates.find((c) => fs.existsSync(c));

const QA_STORAGE_STATE = "tests/e2e/.auth/qa-storage.json";
const LEGACY_QA_PROD_SPECS =
  /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts|pg-004-today-cockpit-2026-05-01-prod\.spec\.ts|hari-2026-05-09-prod\.spec\.ts|hari-2026-05-09-bug-033-prod\.spec\.ts|hari-2026-05-09-outlook-sync-prod\.spec\.ts|hari-2026-05-09-bug-032-prod\.spec\.ts|hari-2026-07-02-prod\.spec\.ts)$/;
// New canonical dated specs own their authentication and start from an empty
// context. The two historical dated specs still depend on the QA storage state
// and therefore remain in LEGACY_QA_PROD_SPECS above.
const TESTER_AUTH_PROD_SPECS =
  /(?:^(?!.*(?:hari-2026-05-09-prod|hari-2026-07-02-prod)\.spec\.ts$).*(?:hari|ram)-\d{4}-\d{2}-\d{2}-prod\.spec\.ts$|.*ram-2026-08-(?:11|24)-bugs\.spec\.ts$|.*ram-2026-09-(?:02|04)-bugs\.spec\.ts$|.*iplf-05(?:4b-indian-kanoon|6b-provider-operations|7b-madrid-workflow|8b-recordal-workflow)-2026-08-25-prod\.spec\.ts$|.*iplf-0(?:59b-foreign-associate|60b-judge)-workflow-2026-08-26-prod\.spec\.ts$|.*iplf-061a-product-guide-foundation-2026-08-26-prod\.spec\.ts$|.*iplf-061b-product-guide-workflow-2026-08-27-prod\.spec\.ts$|.*iplf-062b-workspace-assistant-2026-08-27-prod\.spec\.ts$|.*iplf-063b-intelligent-review-2026-08-28-prod\.spec\.ts$|.*iplf-064b-assistant-actions-2026-08-29-prod\.spec\.ts$|.*iplf-065b-ai-safety-feedback-2026-08-30-prod\.spec\.ts$|.*iplf-066b-private-retrieval-2026-08-31-prod\.spec\.ts$|.*product-ownership-2026-08-29\.spec\.ts$)/;

export default defineConfig({
  testDir: "tests/e2e",
  testMatch: [
    /(ram-batch-2026-04-26-prod\.spec\.ts|recommendations-grounding-2026-04-29-prod\.spec\.ts|ram-batch-2026-05-01-prod\.spec\.ts|pg-004-today-cockpit-2026-05-01-prod\.spec\.ts|hari-2026-05-09-prod\.spec\.ts|hari-2026-05-09-bug-033-prod\.spec\.ts|hari-2026-05-09-outlook-sync-prod\.spec\.ts|hari-2026-05-09-bug-032-prod\.spec\.ts|hari-2026-07-02-prod\.spec\.ts|(?:hari|ram)-\d{4}-\d{2}-\d{2}-prod\.spec\.ts|ram-2026-08-(?:11|24)-bugs\.spec\.ts|ram-2026-09-(?:02|04)-bugs\.spec\.ts|iplf-05(?:4b-indian-kanoon|6b-provider-operations|7b-madrid-workflow|8b-recordal-workflow)-2026-08-25-prod\.spec\.ts|iplf-0(?:59b-foreign-associate|60b-judge)-workflow-2026-08-26-prod\.spec\.ts|iplf-061a-product-guide-foundation-2026-08-26-prod\.spec\.ts|iplf-061b-product-guide-workflow-2026-08-27-prod\.spec\.ts|iplf-062b-workspace-assistant-2026-08-27-prod\.spec\.ts|iplf-063b-intelligent-review-2026-08-28-prod\.spec\.ts|iplf-064b-assistant-actions-2026-08-29-prod\.spec\.ts|iplf-065b-ai-safety-feedback-2026-08-30-prod\.spec\.ts|iplf-066b-private-retrieval-2026-08-31-prod\.spec\.ts|product-ownership-2026-08-29\.spec\.ts|qa-auth\.setup\.ts)$/,
    /ram-2026-09-05-bugs\.spec\.ts$/,
    /ram-2026-09-08-bugs\.spec\.ts$/,
    /ram-2026-09-10-hearings\.spec\.ts$/,
    /ram-2026-09-24-bugs\.spec\.ts$/,
    /ram-2026-10-08-notices\.spec\.ts$/,
    /ram-2026-09-07-statute-source-data\.spec\.ts$/,
    PATENT_PROD_SPECS,
    SAVED_MANIFEST_PROD_SPEC,
    OCT13_PORTFOLIO_CALENDAR_SPECS,
    PLATFORM_REPORT_ADMIN_PROD_SPECS,
    BATCH3_CLIENT_SPEC,
    BATCH3_DRAFT_READONLY_SPEC,
    BATCH4_SPECS,
    /google-workspace-token-refresh-2026-10-07\.prod\.spec\.ts$/,
  ],
  timeout: 120_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    extraHTTPHeaders: noPaidProviderHeaders,
    baseURL: process.env.PROD_BASE_URL ?? "https://caseops.ai",
    // Production traces, screenshots, and videos can capture authenticated
    // legal data and session-bearing requests. Keep failure diagnostics in
    // the text reporter; never persist browser media from the live tenant.
    trace: "off",
    screenshot: "off",
    video: "off",
  },
  projects: [
    {
      name: "platform-reports-prod-chromium",
      testMatch: PLATFORM_REPORT_ADMIN_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "setup",
      testMatch: /qa-auth\.setup\.ts$/,
      use: {
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "prod-chromium",
      dependencies: ["setup"],
      testMatch: LEGACY_QA_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: QA_STORAGE_STATE,
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "tester-prod-chromium",
      testMatch: [TESTER_AUTH_PROD_SPECS, SAVED_MANIFEST_PROD_SPEC, /ram-2026-09-05-bugs\.spec\.ts$/, /ram-2026-09-08-bugs\.spec\.ts$/, /ram-2026-09-21-bugfixes\.spec\.ts$/, /ram-2026-09-24-bugs\.spec\.ts$/, /ram-2026-09-26-bugs\.spec\.ts$/, /ram-2026-10-08-notices\.spec\.ts$/, /google-workspace-token-refresh-2026-10-07\.prod\.spec\.ts$/],
      testIgnore: [RETAINED_INDEX_PROD_SPECS, NOTES22_PROD_SPEC],
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "batch3-drafts-readonly-prod-chromium",
      testMatch: BATCH3_DRAFT_READONLY_SPEC,
      fullyParallel: false,
      retries: 0,
      dependencies: [],
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "batch3-clients-prod-chromium",
      testMatch: BATCH3_CLIENT_SPEC,
      grep: /B3-CLIENT-01\/02\/03 contact edits preserve retained verified KYC and matter links$/,
      grepInvert: /\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      dependencies: [],
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "batch3-clients-prod-mobile",
      testMatch: BATCH3_CLIENT_SPEC,
      grep: /\[mobile\] B3-CLIENT-06 verified-client contact editing persists at 393px$/,
      grepInvert: /\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      dependencies: [],
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 393, height: 851 },
        isMobile: true,
        hasTouch: true,
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
      },
    },
    {
      name: "batch4-prod-chromium",
      testMatch: BATCH4_SPECS,
      testIgnore: BATCH4_GOVERNANCE_SPEC,
      grepInvert: /\[mobile\]|\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "batch4-prod-mobile",
      testMatch: BATCH4_SPECS,
      testIgnore: BATCH4_GOVERNANCE_SPEC,
      grep: /\[mobile\]/,
      grepInvert: /\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 393, height: 851 },
        isMobile: true,
        hasTouch: true,
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "batch4-governance-prod-chromium",
      testMatch: BATCH4_GOVERNANCE_SPEC,
      grepInvert: /\[mobile\]|\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      use: {
        ...devices["Desktop Chrome"],
        viewport: { width: 1440, height: 900 },
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "batch4-governance-prod-mobile",
      testMatch: BATCH4_GOVERNANCE_SPEC,
      grep: /\[mobile\]/,
      grepInvert: /\[local-only\]/,
      fullyParallel: false,
      retries: 0,
      use: {
        ...devices["Pixel 5"],
        viewport: { width: 393, height: 851 },
        isMobile: true,
        hasTouch: true,
        storageState: { cookies: [], origins: [] },
        extraHTTPHeaders: noPaidProviderHeaders,
        trace: "off", screenshot: "off", video: "off",
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "tester-index-prod-chromium",
      testMatch: RETAINED_INDEX_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "test-legal-write-prod-chromium",
      testMatch: [OCT13_PORTFOLIO_CALENDAR_SPECS, NOTES22_PROD_SPEC],
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "test-legal-readonly-prod-chromium",
      testMatch: /ram-2026-09-10-hearings\.spec\.ts$/,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath
          ? { executablePath: browserExecutablePath }
          : undefined,
      },
    },
    {
      name: "patent-prod-chromium",
      testMatch: PATENT_PROD_SPECS,
      use: {
        ...devices["Desktop Chrome"],
        storageState: { cookies: [], origins: [] },
        launchOptions: browserExecutablePath ? { executablePath: browserExecutablePath } : undefined,
      },
    },
    {
      name: "statute-source-prod-chromium",
      testMatch: /ram-2026-09-07-statute-source-data\.spec\.ts$/,
      fullyParallel: true,
      use: { storageState: { cookies: [], origins: [] } },
    },
  ],
});
