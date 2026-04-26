/**
 * Playwright setup project: signs in once as Ram, persists the session
 * to tests/e2e/.auth/ram-storage.json so subsequent tests reuse the
 * cookies (no per-test signIn → no auth rate-limit on bulk runs).
 *
 * Used by playwright.prod-ram.config.ts.
 */
import { test as setup, expect } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const RAM_EMAIL = process.env.RAM_TEST_EMAIL ?? "ram@testfirm.com";
const RAM_SLUG = process.env.RAM_TEST_SLUG ?? "test-legal";
const RAM_PASSWORD = process.env.RAM_TEST_PASSWORD ?? "Test@1234567";

export const RAM_STORAGE_STATE = path.join(
  process.cwd(),
  "tests",
  "e2e",
  ".auth",
  "ram-storage.json",
);

setup("authenticate as Ram", async ({ page }) => {
  // Ensure the .auth dir exists.
  const dir = path.dirname(RAM_STORAGE_STATE);
  if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });

  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(RAM_SLUG);
  await page.locator("#email").fill(RAM_EMAIL);
  await page.locator("#password").fill(RAM_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  // Wait generously — auth endpoint can be slow under prior rate-limit
  // pressure. We accept up to 90s for this single sign-in.
  await page.waitForURL(`${PROD_BASE_URL}/app`, { timeout: 90_000 });
  expect(page.url()).toContain("/app");

  // Persist storage state.
  await page.context().storageState({ path: RAM_STORAGE_STATE });
});
