/** Explicit owner acceptance only; excluded from mandatory release/recurring config. PROD_OPEN until executed. */
import type { APIResponse, BrowserContext } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { consoleManagedAdminsResponse, consoleNamedOverview, consoleNamedReportPage } from "../../apps/web/lib/platform/schemas";
import {
  CONSOLE, SESSION_COOKIE, assertRelease, newApi, noOverflow, productionTarget,
  readOnlyWireGuard, required, safeGet, type ConsoleAuth, type ReadOnlyWireGuard,
} from "./support/platform-report-admin";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });
const guards = new WeakMap<BrowserContext, ReadOnlyWireGuard>();

test.beforeEach(async ({ context, baseURL }) => {
  if (process.env.CASEOPS_PRA_PROD_READS_AUTHORIZED !== "1") {
    throw new Error("PROD_OPEN: separate owner-acceptance authorization required; no authenticated request attempted.");
  }
  guards.set(context, await readOnlyWireGuard(context, productionTarget(baseURL)));
});

test.afterEach(async ({ context }) => {
  const guard = guards.get(context);
  if (guard) {
    expect(guard.mutations, "No owner-acceptance browser mutation may be attempted.").toBe(0);
    expect(guard.external, "No external provider request may be attempted.").toBe(0);
    guards.delete(context);
  }
});

async function readJson<T>(response: APIResponse): Promise<T> {
  expect(response.status(), "PRA authorized read rejected; private response omitted.").toBe(200);
  try { return await response.json() as T; }
  catch { throw new Error("PRA read returned invalid JSON; private body omitted."); }
}

test("PRA owner acceptance: actual tenant session cannot enter the report realm", async ({ baseURL }) => {
  const target = productionTarget(baseURL);
  const tenantToken = required("CASEOPS_PRA_PROD_TENANT_TOKEN");
  await assertRelease(target);
  const api = await newApi(target);
  try {
    expect((await safeGet(api, `${target.api.origin}/api/auth/me`, { Authorization: `Bearer ${tenantToken}` })).status(),
      "The supplied tenant credential must first prove valid ordinary-tenant authority.").toBe(200);
    for (const route of ["/auth/session", "/reports/activity", "/admins", "/admins/manage",
      "/reports/overview?include_account_names=true", "/reports/usage?include_account_names=true"]) {
      expect((await safeGet(api, `${target.api.origin}${CONSOLE}${route}`,
        { Authorization: `Bearer ${tenantToken}` })).status()).toBe(401);
    }
    await assertRelease(target);
  } finally { await api.dispose(); }
});

test("PRA owner acceptance: authorized MFA-complete session reads all six reports without mutations", async ({ page, baseURL }) => {
  const target = productionTarget(baseURL);
  if (process.env.CASEOPS_PRA_PROD_READS_AUTHORIZED !== "1") {
    throw new Error("PROD_OPEN: actual owner setup/MFA and separate read authorization required; no authenticated request attempted.");
  }
  const setupProof = required("CASEOPS_PRA_PROD_SETUP_PROOF_SHA256");
  if (!/^[a-f0-9]{64}$/.test(setupProof)) throw new Error("PRA actual owner setup/MFA proof identity required; no synthetic substitution.");
  const cookie = required("CASEOPS_PRA_PROD_SESSION_COOKIE");
  const expectedAdmin = required("CASEOPS_PRA_PROD_AUTHORIZED_ADMIN_ID");
  await assertRelease(target);
  let pageErrors = 0;
  page.on("pageerror", () => { pageErrors++; });
  // Existing separately admitted session only, never minted or persisted here.
  await page.context().addCookies([{ name: SESSION_COOKIE, value: cookie, domain: target.api.hostname,
    path: CONSOLE, secure: true, httpOnly: true, sameSite: "Lax" }]);
  const session = await readJson<ConsoleAuth>(await safeGet(page.request, `${target.api.origin}${CONSOLE}/auth/session`));
  expect(session.state).toBe("authenticated");
  expect(Boolean(session.admin && session.admin.id === expectedAdmin), "Actual admitted principal must match.").toBe(true);
  expect(Date.parse(session.expires_at) > Date.now()).toBe(true);
  const alien = await newApi(target);
  try {
    for (const route of ["/api/auth/me", "/api/matters/", "/api/platform-admin/overview"]) {
      expect((await safeGet(alien, `${target.api.origin}${route}`, { Authorization: `Bearer ${cookie}` })).status()).toBe(401);
    }
  } finally { await alien.dispose(); }
  for (const report of ["activity", "overview", "usage", "profit", "company-profitability", "revenue"]) {
    await readJson<unknown>(await safeGet(page.request, `${target.api.origin}${CONSOLE}/reports/${report}`));
    if (report !== "activity") {
      const named = await readJson<unknown>(await safeGet(page.request,
        `${target.api.origin}${CONSOLE}/reports/${report}?include_account_names=true`));
      expect((report === "overview" ? consoleNamedOverview : consoleNamedReportPage).safeParse(named).success,
        "Actual named report must retain its full strict response contract; private values omitted.").toBe(true);
    }
  }
  if (session.admin?.role === "manager") {
    const directory = await readJson<unknown>(await safeGet(page.request, `${target.api.origin}${CONSOLE}/admins/manage?limit=25`));
    expect(consoleManagedAdminsResponse.safeParse(directory).success,
      "Managed directory requires version, removed_at and server-owned can_manage; private values omitted.").toBe(true);
  }
  const activityLoading = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/reports/activity`
    && response.request().method() === "GET");
  await page.goto(`${target.web.origin}/platform/reports`);
  expect((await activityLoading).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Canonical account activity report", exact: true })).toBeVisible();
  for (const [tab, endpoint] of [["Overview", "overview"], ["Usage", "usage"], ["Profit", "profit"],
    ["Account profitability", "company-profitability"], ["Revenue", "revenue"]]) {
    const loading = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/reports/${endpoint}`
      && response.request().method() === "GET");
    await page.getByRole("tab", { name: tab, exact: true }).click();
    const loaded = await loading;
    expect(loaded.status()).toBe(200);
    expect(new URL(loaded.url()).searchParams.get("include_account_names")).toBe("true");
    const panel = page.getByRole("tabpanel");
    await expect(panel).toBeVisible();
    await expect(panel.getByRole("alert")).toHaveCount(0);
    if (endpoint === "overview") await expect(panel.getByText("Configured monthly run rate", { exact: true })).toBeVisible();
    else {
      const report = panel.getByRole("region", { name: `${endpoint} report`, exact: true });
      await expect(report).toHaveAttribute("aria-busy", "false");
      await expect(report.getByText(/^Generated /)).toBeVisible();
    }
    await noOverflow(page);
  }
  await page.reload();
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  expect(pageErrors).toBe(0);
  await assertRelease(target);
});
