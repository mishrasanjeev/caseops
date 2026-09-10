import { expect, test } from "@playwright/test";
import { apiBaseUrl as localApiBaseUrl } from "./support/env";
import { noPaidProviderHeaders } from "./support/cost-controls";

const apiBaseUrl = process.env.PROD_API_BASE_URL || localApiBaseUrl;
const webBaseUrl = process.env.PROD_BASE_URL || process.env.CASEOPS_WEB_BASE_URL || "http://127.0.0.1:13100";
const local = ["127.0.0.1", "localhost"].includes(new URL(webBaseUrl).hostname);

test("API slash correction preserves the caller origin and authentication boundary", async ({ request }) => {
  const response = await request.get(`${apiBaseUrl}/api/clients`, {
    headers: noPaidProviderHeaders, maxRedirects: 0,
  });
  expect(response.status()).toBe(307);
  expect(response.headers().location).toBe("/api/clients/");
  const destination = new URL(response.headers().location, apiBaseUrl);
  expect(destination.origin).toBe(new URL(apiBaseUrl).origin);
  const canonical = await request.get(destination.toString(), {
    headers: noPaidProviderHeaders, maxRedirects: 0,
  });
  expect(canonical.status()).toBe(401);
  expect((await canonical.json()).status).toBe(401);
});

test("BUG-012 scheduled eligibility is visible without spending or disabling human search", async ({ page, request }) => {
  const suffix = Date.now().toString(36);
  const slug = process.env.CASEOPS_RAM_PROD_SLUG || (local ? `ram-sep08-test-${suffix}` : "test-legal");
  const email = process.env.CASEOPS_RAM_PROD_EMAIL || (local ? `ram-sep08-${suffix}@example.com` : "ram@testfirm.com");
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD || (local ? "RamSep08Local!" : "");
  if (!password) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production verification.");
  if (local) {
    const bootstrap = await request.post(`${apiBaseUrl}/api/bootstrap/company`, {
      headers: noPaidProviderHeaders,
      data: { company_name: `Ram September 08 ${suffix}`, company_slug: slug, company_type: "law_firm", owner_full_name: "Ram", owner_email: email, owner_password: password },
    });
    expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  }
  await page.goto(`${webBaseUrl}/sign-in`);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const login = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
  await page.locator('button[type="submit"]').click();
  const response = await login;
  expect(response.status()).toBe(200);
  const identity = await response.json();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  const status = await request.get(`${apiBaseUrl}/api/case-tracking/status`, {
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${identity.access_token}` },
  });
  expect(status.status()).toBe(200);
  const body = await status.json();
  expect(body.configured).toBe(true);
  expect(body.performs_external_probe).toBe(false);
  expect(body.scheduled_sync_eligible).toBe(local);
  expect(body.scheduled_sync_disabled_reason).toBe(local ? null : "configured_test_tenant");
  expect(body.scheduled_sync_window_end_local_time).toBe("20:00");
  expect(body.workspace_monthly_reserved_minor).toBeGreaterThanOrEqual(0);
  const paidMutations: string[] = [];
  page.on("request", req => {
    if (req.method() === "POST" && /\/api\/case-tracking\/(search|bookmarks\/[^/]+\/refresh)$/.test(new URL(req.url()).pathname)) paidMutations.push(req.url());
  });
  for (const width of [393, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${webBaseUrl}/app/case-tracking`);
    const policy = page.getByRole("region", { name: "Scheduled hearing updates" });
    await expect(policy).toBeVisible();
    await expect(policy).toContainText("18:00-20:00 (Asia/Kolkata)");
    await expect(policy).toContainText(local ? "Eligible for scheduled updates" : "Scheduled paid updates are excluded for this test workspace");
    await page.getByRole("textbox", { name: "CNR number", exact: true }).fill("DLHC010091232026");
    await expect(page.getByRole("button", { name: /^Search$/ })).toBeEnabled();
    const bounds = await policy.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: test.info().outputPath(`scheduled-policy-${width}.png`), fullPage: true });
  }
  expect(paidMutations).toEqual([]);
});
