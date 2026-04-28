/**
 * Playwright setup project: signs in once as the dedicated CaseOps QA
 * Bot (a workspace we own end-to-end, not a real user's account),
 * persists the session to tests/e2e/.auth/qa-storage.json so subsequent
 * tests reuse the cookies (no per-test signIn → no auth rate-limit on
 * bulk runs).
 *
 * The QA workspace was bootstrapped via tests/e2e/setup/bootstrap-qa-workspace.setup.ts
 * (one-off, run once on prod). It has owner role + isolated tenant data.
 *
 * Used by playwright.prod-ram.config.ts.
 */
import { test as setup, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";

// `??` treats empty string as a value, so an unset GitHub repo
// variable (which materializes as `${{ vars.PROD_BASE_URL }}` = ""
// in the workflow) bypasses the fallback. Trim + truthy-check
// instead so an empty/whitespace var falls back to the default.
const env = (key: string, fallback: string): string => {
  const v = (process.env[key] ?? "").trim();
  return v.length > 0 ? v : fallback;
};

const PROD_BASE_URL = env("PROD_BASE_URL", "https://caseops.ai");
const QA_OWNER_EMAIL = env("CASEOPS_QA_EMAIL", "qa-bot@caseops.ai");
const QA_COMPANY_SLUG = env("CASEOPS_QA_SLUG", "caseops-qa");
const QA_OWNER_PASSWORD = process.env.CASEOPS_QA_PASSWORD ?? "";

export const QA_STORAGE_STATE = path.join(
  process.cwd(),
  "tests",
  "e2e",
  ".auth",
  "qa-storage.json",
);

setup("authenticate as CaseOps QA Bot", async ({ page }) => {
  if (!QA_OWNER_PASSWORD) {
    throw new Error(
      "CASEOPS_QA_PASSWORD env var is required. The QA workspace's " +
      "owner password is held only as a GitHub secret + the developer's " +
      "password manager — never in committed code.",
    );
  }

  // Ensure the .auth dir exists.
  const dir = path.dirname(QA_STORAGE_STATE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(QA_COMPANY_SLUG);
  await page.locator("#email").fill(QA_OWNER_EMAIL);
  await page.locator("#password").fill(QA_OWNER_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(`${PROD_BASE_URL}/app`, { timeout: 90_000 });
  expect(page.url()).toContain("/app");

  // Persist storage state.
  await page.context().storageState({ path: QA_STORAGE_STATE });
});
