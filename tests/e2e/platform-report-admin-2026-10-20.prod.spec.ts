/** Mandatory release-owned public boundary only. Positive owner proof remains PROD_OPEN. */
import type { BrowserContext } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import {
  CONSOLE, assertRelease, newApi, noOverflow, productionTarget, readOnlyWireGuard, safeGet,
  type ReadOnlyWireGuard,
} from "./support/platform-report-admin";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });
const wireGuards = new WeakMap<BrowserContext, ReadOnlyWireGuard>();

test.beforeEach(async ({ context, baseURL }) => {
  wireGuards.set(context, await readOnlyWireGuard(context, productionTarget(baseURL)));
});

test.afterEach(async ({ context }) => {
  const guard = wireGuards.get(context);
  if (guard) {
    expect(guard.mutations, "No production browser mutation may be attempted.").toBe(0);
    expect(guard.external, "No external provider or third-party browser request may be attempted.").toBe(0);
    wireGuards.delete(context);
  }
});

test("PRA production anonymous pages are private/noindex and report APIs reject missing sessions", async ({ page, baseURL }) => {
  const target = productionTarget(baseURL);
  await assertRelease(target);
  const api = await newApi(target);
  try {
    for (const route of ["sign-in", "reports", "admins", "security", "setup", "reset-password"]) {
      const response = await safeGet(api, `${target.web.origin}/platform/${route}`);
      expect(response.status()).toBe(200);
      const headers = response.headers();
      expect(headers["x-robots-tag"]).toMatch(/noindex/);
      expect(headers["cache-control"]).toMatch(/private/);
      expect(headers["cache-control"]).toMatch(/no-store/);
      expect(headers["referrer-policy"]).toBe("no-referrer");
    }
    for (const route of ["/auth/session", "/reports/activity", "/reports/overview", "/reports/usage", "/reports/profit", "/reports/company-profitability", "/reports/revenue", "/admins", "/admins/manage",
      "/reports/overview?include_account_names=true", "/reports/usage?include_account_names=true",
      "/reports/profit?include_account_names=true", "/reports/company-profitability?include_account_names=true",
      "/reports/revenue?include_account_names=true"]) {
      expect((await safeGet(api, `${target.api.origin}${CONSOLE}${route}`)).status()).toBe(401);
    }
    await page.goto(`${target.web.origin}/platform/sign-in`);
    const form = page.getByRole("form", { name: "Platform sign in", exact: true });
    await expect(form).toBeVisible();
    await expect(form.getByLabel("Email", { exact: true })).toBeVisible();
    await expect(form.getByLabel("Password", { exact: true })).toBeVisible();
    await expect(form.getByLabel(/company|workspace/i)).toHaveCount(0);
    await noOverflow(page);
    await assertRelease(target);
  } finally { await api.dispose(); }
});
