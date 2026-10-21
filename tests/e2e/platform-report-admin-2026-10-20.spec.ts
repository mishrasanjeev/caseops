/** PRA-01..08: real local console APIs, captured delivery and independent MFA realm. */
import { randomUUID } from "node:crypto";
import { devices, type Browser, type BrowserContext, type Locator, type Page, type TestInfo } from "@playwright/test";

import { expect, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders, noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import {
  CONSOLE, SESSION_COOKIE, assertRelease, capturedLink, cleanupLocalFixture, completeSetup, contextCsrf,
  controlBounds, enrollMfa, expectState, json, mailLedger, newApi, noOverflow, origins, passwordControl,
  safeGet, safePost, secretToken, seedLocalFixture, signInWithRecovery,
  type LocalFixture, type Origins,
} from "./support/platform-report-admin";

test.use({ extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("PRA needs the configured local baseURL.");
  await use(localTransportHeaders(baseURL));
}, storageState: { cookies: [], origins: [] }, trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });

type Admin = { id: string; email: string; role: string; status: string };
type Activity = {
  generated_at: string;
  segments: Record<string, { company_count: number; accounts: Array<{
    company_id: string; name: string; company_type: string;
    usage_status: string; last_meaningful_activity_at: string | null;
    current: { active_users: number; active_matters: number; documents_total: number };
    periods: Record<string, Record<string, number>>;
  }>; periods: Record<string, Record<string, number>> }>;
};
type ReportData = { generated_at: string; items?: Array<Record<string, unknown>>; has_more?: boolean } & Record<string, unknown>;
const money = (minor: number) => new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(minor / 100);
const dateOnly = (date: string) => new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium" }).format(new Date(date));
const timestamp = (date: string) => new Intl.DateTimeFormat("en-IN", { timeZone: "Asia/Kolkata", dateStyle: "medium", timeStyle: "short" }).format(new Date(date));

async function visibleText(cell: Locator, value: string): Promise<void> {
  await cell.scrollIntoViewIfNeeded();
  await cell.evaluate(element => element.scrollIntoView({ block: "center", inline: "center" }));
  await expect(cell).toBeInViewport({ ratio: 0.95 });
  await expect(cell).toHaveText(value);
}

async function localScreenshot(page: Page, target: Origins, info: TestInfo, label: string): Promise<void> {
  if (!target.local || !["/platform/reports", "/platform/admins"].includes(new URL(page.url()).pathname)) {
    throw new Error("PRA screenshots are restricted to positive synthetic local report/admin pages.");
  }
  await expect(page.getByLabel("Authenticator setup key", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: /Recovery codes/i })).toHaveCount(0);
  await info.attach(`pra-${label}-${info.project.name}.png`, {
    body: await page.screenshot({ fullPage: true, animations: "disabled" }), contentType: "image/png",
  });
}

async function positiveFinancial(page: Page, target: Origins, fixture: LocalFixture,
  endpoint: string, initial: ReportData): Promise<void> {
  const panel = page.getByRole("tabpanel");
  const f = fixture.financial;
  const firm = fixture.accounts.find(account => account.id === f.company_id)!;
  let data = initial;
  if (endpoint !== "overview") {
    const identity = (row: Record<string, unknown>) => row.company_id === f.company_id
      && (endpoint !== "usage" || row.feature_key === fixture.usage_features[0]);
    for (let pages = 0; pages < 20 && !data.items?.some(identity); pages++) {
      expect(data.has_more, `Known ${endpoint} source must be reachable without truncation.`).toBe(true);
      const advancing = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/${endpoint}`
        && new URL(res.url()).searchParams.has("cursor") && res.request().method() === "GET");
      await panel.getByRole("button", { name: "Next page", exact: true }).click();
      data = await json<ReportData>(await advancing, 200, `Positive ${endpoint} source continuation`);
    }
    const known = data.items?.filter(identity) ?? [];
    expect(known).toHaveLength(1);
    const row = endpoint === "usage"
      ? panel.getByRole("row").filter({ has: page.getByText(f.company_id, { exact: true }) })
        .filter({ has: page.getByText(fixture.usage_features[0], { exact: true }) })
      : panel.getByRole("row").filter({ has: page.getByText(endpoint === "revenue" ? f.merchant_reference : firm.name, { exact: true }) });
    await expect(row).toHaveCount(1);
    let cells: string[];
    if (endpoint === "usage") {
      expect(known[0]).toEqual(expect.objectContaining({ company_id: f.company_id, feature_key: fixture.usage_features[0],
        quantity: 1, credits: 0, estimated_internal_cost_minor: 0 }));
      cells = [f.company_id, fixture.usage_features[0], "1", "0", money(0)];
    } else if (endpoint === "revenue") {
      expect(known[0]).toEqual(expect.objectContaining({ merchant_reference: f.merchant_reference,
        amount_paid_minor: 118_000, tax_amount_minor: 18_000 }));
      expect(Date.parse(String(known[0].paid_at))).toBe(Date.parse(f.paid_at));
      cells = [f.company_id, dateOnly(f.paid_at), f.merchant_reference, money(118_000), money(18_000)];
    } else {
      expect(known[0]).toEqual(expect.objectContaining({ gross_revenue_minor: 120_000, recognized_revenue_minor: 100_000,
        total_variable_cost_minor: 25_000, gross_profit_minor: 75_000, gross_margin_bps: 7_500 }));
      if (endpoint === "profit") {
        expect(Date.parse(String(known[0].period_start))).toBe(Date.parse(f.period_start));
        expect(Date.parse(String(known[0].period_end))).toBe(Date.parse(f.period_end));
      } else expect(known[0]).toEqual(expect.objectContaining({ rollup_count: 1, loss_risk: false }));
      cells = [firm.name, endpoint === "profit" ? `${dateOnly(f.period_start)} - ${dateOnly(f.period_end)}` : "1",
        money(120_000), money(25_000), money(75_000), "75.0%", endpoint === "profit" ? "estimated" : "No"];
    }
    for (const [index, value] of cells.entries()) await visibleText(row.getByRole("cell").nth(index), value);
    if (["profit", "company-profitability"].includes(endpoint)) {
      const details = row.locator("details");
      await controlBounds(details.locator("summary"), page, 1);
      await details.locator("summary").click();
      await visibleText(details.getByText("Recognized revenue", { exact: true }).locator("..").locator("dd"), money(100_000));
      await visibleText(details.getByText("Gateway cost", { exact: true }).locator("..").locator("dd"), money(25_000));
    }
  } else {
    expect(data).toEqual(expect.objectContaining(f.overview));
    for (const [label, value] of [["Recorded rollups", String(f.overview.rollup_count)],
      ["Gross revenue", money(f.overview.gross_revenue_minor)], ["Recognized revenue", money(f.overview.recognized_revenue_minor)],
      ["Variable cost", money(f.overview.total_variable_cost_minor)], ["Gross profit", money(f.overview.gross_profit_minor)]]) {
      await visibleText(panel.getByText(label, { exact: true }).locator("..").locator("dd"), value);
    }
  }
  expect(Number.isFinite(Date.parse(data.generated_at))).toBe(true);
  await expect(panel.getByText(new RegExp(`^Generated ${dateOnly(data.generated_at).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`))).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
}

async function visibleControls(page: Page): Promise<void> {
  await noOverflow(page);
  const controls = page.locator('main button:visible, main input:not([type="hidden"]):visible, main select:visible, main a:visible, main summary:visible');
  for (const control of await controls.all()) {
    const textAction = await control.evaluate(element => ["A", "SUMMARY"].includes(element.tagName));
    await controlBounds(control, page, textAction ? 1 : 24);
  }
  const boxes = await controls.evaluateAll(elements => elements.map(element => {
    const r = element.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  }));
  for (let i = 0; i < boxes.length; i++) for (let j = i + 1; j < boxes.length; j++) {
    const a = boxes[i], b = boxes[j];
    const overlap = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x) > 1
      && Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y) > 1;
    expect(overlap, "PRA sibling controls must not overlap.").toBe(false);
  }
}

async function reportAccounts(page: Page, target: Origins, fixture: LocalFixture, info: TestInfo): Promise<void> {
  await page.goto(`${target.web.origin}/platform/reports`);
  await expect(page.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
  await page.getByRole("tab", { name: "Account activity", exact: true }).click();
  const report = page.getByRole("region", { name: "Canonical account activity report", exact: true });
  await expect(report).toBeVisible();
  const search = report.getByRole("searchbox", { name: "Account name", exact: true });
  await search.fill(fixture.account_prefix);
  const dormant = report.locator("details").filter({ has: page.locator("summary").filter({ hasText: /^No recorded activity for 30 days \(1\)$/ }) });
  const summary = dormant.locator(":scope > summary");
  await expect(summary).toBeVisible();
  await expect(dormant).not.toHaveAttribute("open", "");
  const dormantAccount = fixture.accounts.find(account => account.engagement === "dormant")!;
  await expect(dormant.getByText(dormantAccount.name, { exact: true })).not.toBeVisible();
  for (const account of fixture.accounts.filter(row => row.engagement !== "dormant")) {
    await expect(report.getByText(account.name, { exact: true })).toBeVisible();
  }
  await controlBounds(summary, page);
  await summary.focus();
  await page.keyboard.press("Enter");
  await expect(dormant).toHaveAttribute("open", "");
  for (const account of fixture.accounts) {
    const row = report.getByRole("row").filter({ has: page.getByText(account.name, { exact: true }) });
    await expect(row).toHaveCount(1);
    await expect(row.getByText(account.name, { exact: true })).toBeVisible();
    const cells = row.getByRole("cell");
    await visibleText(cells.nth(2), "Enabled");
    await visibleText(cells.nth(3), account.last_meaningful_activity_at ? timestamp(account.last_meaningful_activity_at) : "Not evidenced");
    await visibleText(cells.nth(4), String(account.active_users));
    await visibleText(cells.nth(5), "0");
    await visibleText(cells.nth(6), "0");
    if (account.engagement === "unknown") {
      const unknown = report.getByRole("region", { name: "Unknown engagement", exact: true });
      await expect(unknown.getByText(account.name, { exact: true })).toBeVisible();
      await expect(unknown).toContainText("not classified as inactive");
    }
  }
  await visibleControls(page);
  await page.reload();
  await expect(report).toBeVisible();
  await search.fill(fixture.account_prefix);
  await expect(dormant).not.toHaveAttribute("open", "");
  const response = await safeGet(page.request, `${target.api.origin}${CONSOLE}/reports/activity`);
  const data = await json<Activity>(response, 200, "Canonical activity report");
  expect(Number.isFinite(Date.parse(data.generated_at))).toBe(true);
  const allAccounts = Object.values(data.segments).flatMap(segment => segment.accounts);
  for (const account of fixture.accounts) {
    expect(allAccounts.filter(row => row.company_id === account.id)).toEqual([
      expect.objectContaining({ company_id: account.id, name: account.name, company_type: account.company_type }),
    ]);
    const saved = allAccounts.find(row => row.company_id === account.id)!;
    expect(saved.usage_status).toBe(account.engagement === "active" ? "recent" : account.engagement === "dormant" ? "inactive" : "unknown");
    expect(saved.last_meaningful_activity_at ? Date.parse(saved.last_meaningful_activity_at) : null)
      .toBe(account.last_meaningful_activity_at ? Date.parse(account.last_meaningful_activity_at) : null);
    expect(saved.current).toEqual(expect.objectContaining({ active_users: account.active_users, active_matters: 0, documents_total: 0 }));
  }
  await summary.click();
  await expect(dormant).toHaveAttribute("open", "");
  for (const account of fixture.accounts) {
    const row = report.getByRole("row").filter({ has: page.getByText(account.name, { exact: true }) });
    await expect(row).toHaveCount(1);
    const cells = row.getByRole("cell");
    await visibleText(cells.nth(3), account.last_meaningful_activity_at ? timestamp(account.last_meaningful_activity_at) : "Not evidenced");
    await visibleText(cells.nth(4), String(account.active_users));
    await visibleText(cells.nth(5), "0");
    await visibleText(cells.nth(6), "0");
  }
  await localScreenshot(page, target, info, "activity-positive-reloaded");
  for (const segment of Object.values(data.segments)) {
    expect(segment.company_count).toBe(segment.accounts.length);
    for (const [period, totals] of Object.entries(segment.periods)) for (const [metric, total] of Object.entries(totals)) {
      const sum = segment.accounts.reduce((value, account) => value + account.periods[period][metric], 0);
      expect(total, `Canonical report reconciliation ${period}/${metric}`).toBeCloseTo(sum, 1);
    }
  }
  for (const [tab, endpoint] of [
    ["Overview", "overview"], ["Usage", "usage"], ["Profit", "profit"], ["Account profitability", "company-profitability"],
    ["Revenue", "revenue"],
  ]) {
    await controlBounds(page.getByRole("tab", { name: tab, exact: true }), page);
    const loaded = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/${endpoint}` && res.request().method() === "GET");
    await page.getByRole("tab", { name: tab, exact: true }).click();
    const loadedResponse = await loaded;
    expect(loadedResponse.status()).toBe(200);
    await expect(page.getByRole("tabpanel")).toBeVisible();
    if (endpoint !== "overview") {
      const data = await loadedResponse.json() as { items: Array<{ company_id: string; feature_key?: string }>; has_more: boolean };
      const panel = page.getByRole("tabpanel");
      const next = panel.getByRole("button", { name: "Next page", exact: true });
      await controlBounds(next, page);
      await controlBounds(panel.getByRole("button", { name: "Previous page", exact: true }), page);
      if (endpoint === "usage") expect(data.has_more, "Seeded26 actual usage identities must require continuation.").toBe(true);
      if (data.has_more) {
        await expect(next).toBeEnabled();
        const advancing = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/${endpoint}`
          && new URL(res.url()).searchParams.has("cursor") && res.request().method() === "GET");
        await next.click();
        expect((await advancing).status()).toBe(200);
        const previous = panel.getByRole("button", { name: "Previous page", exact: true });
        await expect(previous).toBeEnabled();
        await controlBounds(previous, page);
        const returning = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/${endpoint}`
          && !new URL(res.url()).searchParams.has("cursor") && res.request().method() === "GET");
        await previous.click();
        const restored = await returning;
        expect(restored.status()).toBe(200);
        expect((await restored.json()).items).toEqual(data.items);
      } else await expect(next).toBeDisabled();
    }
    await positiveFinancial(page, target, fixture, endpoint, await loadedResponse.json() as ReportData);
    await visibleControls(page);
    const activityReloaded = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/activity`
      && res.request().method() === "GET");
    await page.reload();
    expect((await activityReloaded).status()).toBe(200);
    await expect(page.getByRole("region", { name: "Canonical account activity report", exact: true })).toBeVisible();
    const reloaded = page.waitForResponse(res => new URL(res.url()).pathname === `${CONSOLE}/reports/${endpoint}`
      && res.request().method() === "GET");
    await page.getByRole("tab", { name: tab, exact: true }).click();
    await positiveFinancial(page, target, fixture, endpoint, await json<ReportData>(await reloaded, 200, `${endpoint} reload`));
    await localScreenshot(page, target, info, `${endpoint}-positive-reloaded`);
  }
  const firm = fixture.accounts.find(account => account.company_type === "law_firm")!;
  type UsageRow = { company_id: string; feature_key: string; quantity: number };
  const usage: UsageRow[] = [];
  let cursor: string | null = null;
  for (let pages = 0; pages < 20; pages++) {
    const query: URLSearchParams = new URLSearchParams({ limit: "25", ...(cursor ? { cursor } : {}) });
    const data: { items: UsageRow[]; next_cursor: string | null } = await json(await safeGet(page.request,
      `${target.api.origin}${CONSOLE}/reports/usage?${query}`), 200, "Usage continuation");
    usage.push(...data.items);
    cursor = data.next_cursor;
    if (!cursor || usage.filter(row => row.company_id === firm.id).length === fixture.usage_features.length) break;
  }
  const known = usage.filter(row => row.company_id === firm.id);
  expect(known.map(row => row.feature_key).sort()).toEqual([...fixture.usage_features].sort());
  for (const [index, feature] of fixture.usage_features.entries()) {
    expect(known.find(row => row.feature_key === feature)?.quantity).toBe(index + 1);
  }
}

async function realmDenials(page: Page, target: Origins, fixture: LocalFixture): Promise<void> {
  const tenant = await newApi(target);
  const wrongRealm = await newApi(target);
  try {
    const login = await json<{ access_token: string }>(await safePost(tenant, `${target.api.origin}/api/auth/login`, {
      data: { company_slug: fixture.tenant.slug, email: fixture.tenant.email, password: fixture.tenant.password },
      maxRetries: 0,
    }), 200, "Local tenant login");
    expect((await safeGet(tenant, `${target.api.origin}/api/auth/me`, { Authorization: `Bearer ${login.access_token}` })).status()).toBe(200);
    for (const route of ["/auth/session", "/reports/activity", "/admins"]) {
      expect((await safeGet(wrongRealm, `${target.api.origin}${CONSOLE}${route}`,
        { Authorization: `Bearer ${login.access_token}` })).status()).toBe(401);
    }
    const consoleCookie = (await page.context().cookies()).find(cookie => cookie.name === SESSION_COOKIE);
    expect(Boolean(consoleCookie?.value)).toBe(true);
    for (const route of ["/api/auth/me", "/api/matters/", "/api/platform-admin/overview"]) {
      expect((await safeGet(wrongRealm, `${target.api.origin}${route}`,
        { Authorization: `Bearer ${consoleCookie!.value}` })).status()).toBe(401);
    }
    const noCsrf = await safePost(page.request, `${target.api.origin}${CONSOLE}/admins/invitations`, {
      data: { email: `csrf-${fixture.run_id}@example.com`, full_name: "No CSRF admission" }, maxRetries: 0,
    });
    expect(noCsrf.status()).toBe(403);
  } finally { await tenant.dispose(); await wrongRealm.dispose(); }
}

async function journey(page: Page, browser: Browser, baseURL: string | undefined, mobile: boolean, testInfo: TestInfo) {
  test.setTimeout(300_000);
  const target = origins(baseURL, true, e2eEnv.CASEOPS_RELEASE_SHA);
  if (mobile) {
    expect(testInfo.project.name).toBe("app-mobile");
    expect(testInfo.project.use.isMobile).toBe(true);
    expect(testInfo.project.use.hasTouch).toBe(true);
    expect(page.viewportSize()?.width).toBe(393);
  } else await page.setViewportSize({ width: 1280, height: 1000 });
  await assertRelease(target);
  const api = await newApi(target);
  const contexts: BrowserContext[] = [];
  const runId = randomUUID();
  let ownedFixture: LocalFixture | undefined;
  let primaryFailed = false;
  const pageErrors: string[] = [];
  let forbidden = 0;
  page.on("pageerror", () => pageErrors.push("pageerror"));
  try {
    await page.context().route("**/*", route => {
      const url = new URL(route.request().url());
      if (![target.web.origin, target.api.origin].includes(url.origin)) { forbidden++; return route.abort("blockedbyclient"); }
      return route.continue();
    });
    const fixture = await seedLocalFixture(api, target, runId);
    ownedFixture = fixture;
    const password = `PRA!${randomUUID()}aA9`;
    const initialLink = await capturedLink(api, target, fixture, fixture.manager.email, "invite");
    await completeSetup(page, initialLink, password, fixture.manager.full_name, 401);
    await expect(page.getByRole("main").getByRole("alert")).toHaveText(
      "This link is invalid, expired or already used. Request a fresh setup or reset link.",
    );
    expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/auth/session`)).status()).toBe(401);
    const initialMailIds = (await mailLedger(api, target, fixture)).map(row => row.id);
    await page.goto(`${target.web.origin}/platform/setup`);
    const resendForm = page.getByRole("form", { name: "Resend setup email", exact: true });
    await resendForm.getByLabel("Email", { exact: true }).fill(fixture.manager.email);
    const resending = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/invitations/resend`
      && response.request().method() === "POST");
    await controlBounds(resendForm.getByRole("button", { name: "Resend setup email", exact: true }), page);
    await resendForm.getByRole("button", { name: "Resend setup email", exact: true }).click();
    expect(await json(await resending, 200, "Explicit setup resend")).toEqual({ status: "accepted" });
    await expect(resendForm.getByRole("status")).toContainText("If this account is eligible");
    const currentLink = await capturedLink(api, target, fixture, fixture.manager.email, "invite", initialMailIds);
    expect(currentLink === initialLink, "A resend must rotate the actual link.").toBe(false);
    const afterResendIds = (await mailLedger(api, target, fixture)).map(row => row.id);
    expect(await json(await safePost(api, `${target.api.origin}${CONSOLE}/auth/invitations/resend`, {
      data: { email: fixture.manager.email },
    }), 200, "Cooldown resend replay")).toEqual({ status: "accepted" });
    expect((await mailLedger(api, target, fixture)).map(row => row.id)).toEqual(afterResendIds);
    expect((await safePost(api, `${target.api.origin}${CONSOLE}/auth/invitations/complete`, {
      data: { token: secretToken(initialLink), password, full_name: fixture.manager.full_name },
    })).status()).toBe(401);
    await completeSetup(page, currentLink, password, fixture.manager.full_name);
    const recovery = await enrollMfa(page, target, fixture.manager.email);
    const manager = await expectState(page, target, "authenticated");
    expect(manager.admin?.id).toBe(fixture.manager.id);
    expect(manager.admin?.role).toBe("manager");
    const setupReplay = await safePost(api, `${target.api.origin}${CONSOLE}/auth/invitations/complete`, {
      data: { token: secretToken(currentLink), password, full_name: fixture.manager.full_name }, maxRetries: 0,
    });
    expect(setupReplay.status()).toBe(401);
    await reportAccounts(page, target, fixture, testInfo);
    await realmDenials(page, target, fixture);

    await page.goto(`${target.web.origin}/platform/admins`);
    const email = `viewer-${fixture.run_id}@example.com`;
    await page.getByLabel("Full name", { exact: true }).fill("Synthetic report viewer");
    await page.getByLabel("Email", { exact: true }).fill(email);
    await visibleControls(page);
    const sending = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/admins/invitations`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Invite viewer", exact: true }).click();
    const invitation = await json<{ admin: Admin; delivery_status: string }>(await sending, 200, "Invite viewer");
    expect(invitation.admin.email).toBe(email);
    expect(invitation.admin.role).toBe("viewer");
    expect(invitation.delivery_status).toBe("accepted");
    await expect(page.getByRole("row").filter({ has: page.getByText(email, { exact: true }) })).toContainText("pending");
    await localScreenshot(page, target, testInfo, "administrator-invited");
    const link = await capturedLink(api, target, fixture, email, "invite");
    const firstMail = (await mailLedger(api, target, fixture)).filter(row => row.recipient_email === email && row.purpose === "invite");
    const replay = await safePost(page.request, `${target.api.origin}${CONSOLE}/admins/invitations`, {
      headers: await contextCsrf(page.context()), data: { email, full_name: "Synthetic report viewer" }, maxRetries: 0,
    });
    const repeated = await json<{ admin: Admin }>(replay, 200, "Idempotent invitation replay");
    expect(repeated.admin.id).toBe(invitation.admin.id);
    expect((await mailLedger(api, target, fixture)).filter(row => row.recipient_email === email && row.purpose === "invite").map(row => row.id))
      .toEqual(firstMail.map(row => row.id));
    const adminIds: string[] = [];
    let adminCursor: string | null = null;
    for (let pages = 0; pages < 20; pages++) {
      const query = new URLSearchParams({ limit: "1", ...(adminCursor ? { cursor: adminCursor } : {}) });
      const data: { items: Admin[]; next_cursor: string | null } = await json(await safeGet(page.request,
        `${target.api.origin}${CONSOLE}/admins?${query}`), 200, "Administrator continuation");
      expect(data.items.length).toBeLessThanOrEqual(1);
      adminIds.push(...data.items.map(row => row.id));
      adminCursor = data.next_cursor;
      if (!adminCursor) break;
    }
    expect(adminCursor, "Bounded directory fixture must reach its actual final page.").toBeNull();
    expect(new Set(adminIds).size).toBe(adminIds.length);
    expect(adminIds).toContain(fixture.manager.id);
    expect(adminIds).toContain(invitation.admin.id);
    const viewerContext = await browser.newContext({ ...(mobile ? devices["Pixel 5"] : { viewport: { width: 1280, height: 1000 } }),
      storageState: { cookies: [], origins: [] }, extraHTTPHeaders: localTransportHeaders(target.web.origin), serviceWorkers: "block" });
    contexts.push(viewerContext);
    await viewerContext.route("**/*", route => {
      if (![target.web.origin, target.api.origin].includes(new URL(route.request().url()).origin)) { forbidden++; return route.abort("blockedbyclient"); }
      return route.continue();
    });
    const viewer = await viewerContext.newPage();
    viewer.on("pageerror", () => pageErrors.push("pageerror"));
    await completeSetup(viewer, link, password, "Synthetic report viewer");
    const viewerRecovery = await enrollMfa(viewer, target, email);
    expect((await expectState(viewer, target, "authenticated")).admin?.role).toBe("viewer");
    await viewer.goto(`${target.web.origin}/platform/reports`);
    await expect(viewer.getByRole("heading", { name: "Reports", exact: true })).toBeVisible();
    await expect(viewer.getByRole("link", { name: "Administrators", exact: true })).toHaveCount(0);
    expect((await safeGet(viewer.request, `${target.api.origin}${CONSOLE}/admins`)).status()).toBe(403);
    await visibleControls(viewer);

    const beforeReset = (await mailLedger(api, target, fixture)).map(row => row.id);
    await viewer.goto(`${target.web.origin}/platform/reset-password`);
    await viewer.getByLabel("Email", { exact: true }).fill(email);
    await controlBounds(viewer.getByRole("button", { name: "Send reset link", exact: true }), viewer);
    await viewer.getByRole("button", { name: "Send reset link", exact: true }).click();
    const resetLink = await capturedLink(api, target, fixture, email, "password_reset", beforeReset);
    const newPassword = `PRA-reset!${randomUUID()}aA9`;
    const oldViewerState = await viewerContext.storageState();
    try { await viewer.goto(resetLink); } catch { throw new Error("PRA reset navigation failed; private link omitted."); }
    await expect.poll(() => new URL(viewer.url()).hash === "", {
      message: "The reset fragment must be consumed; secret omitted.",
    }).toBe(true);
    await viewer.getByLabel("New password", { exact: true }).fill(newPassword);
    await viewer.getByLabel("Confirm password", { exact: true }).fill(newPassword);
    await passwordControl(viewer, "New password");
    await passwordControl(viewer, "Confirm password");
    await controlBounds(viewer.getByRole("button", { name: "Reset password", exact: true }), viewer);
    const resetting = viewer.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/password-reset/complete`
      && response.request().method() === "POST");
    await viewer.getByRole("button", { name: "Reset password", exact: true }).click();
    expect((await resetting).status()).toBe(200);
    await expect(viewer.getByRole("status")).toContainText("Password reset complete");
    const stale = await browser.newContext({ storageState: oldViewerState, extraHTTPHeaders: noPaidProviderHeaders });
    contexts.push(stale);
    expect((await safeGet(stale.request, `${target.api.origin}${CONSOLE}/auth/session`)).status()).toBe(401);
    const resetReplay = await safePost(api, `${target.api.origin}${CONSOLE}/auth/password-reset/complete`, {
      data: { token: secretToken(resetLink), password: newPassword }, maxRetries: 0,
    });
    expect(resetReplay.status()).toBe(401);
    const consumedCode = viewerRecovery.shift()!;
    await signInWithRecovery(viewer, target, email, newPassword, consumedCode);
    const logout = await safePost(viewer.request, `${target.api.origin}${CONSOLE}/auth/logout`, {
      headers: await contextCsrf(viewerContext), maxRetries: 0,
    });
    expect(logout.status()).toBe(200);
    await signInWithRecovery(viewer, target, email, newPassword, viewerRecovery.shift()!, consumedCode);
    const unauthorizedRevoke = await safePost(viewer.request, `${target.api.origin}${CONSOLE}/admins/${fixture.manager.id}/revoke`, {
      headers: await contextCsrf(viewerContext), data: { reason: "Viewer cannot revoke manager" }, maxRetries: 0,
    });
    expect(unauthorizedRevoke.status()).toBe(403);
    const managerLogout = await safePost(page.request, `${target.api.origin}${CONSOLE}/auth/logout`, {
      headers: await contextCsrf(page.context()), maxRetries: 0,
    });
    expect(managerLogout.status()).toBe(200);
    await signInWithRecovery(page, target, fixture.manager.email, password, recovery.shift()!);
    await page.goto(`${target.web.origin}/platform/admins`);
    const viewerRow = page.getByRole("row").filter({ has: page.getByText(email, { exact: true }) });
    await expect(viewerRow).toHaveCount(1);
    await controlBounds(viewerRow.getByRole("button", { name: "Revoke", exact: true }), page);
    await viewerRow.getByRole("button", { name: "Revoke", exact: true }).click();
    const dialog = page.getByRole("form", { name: "Revoke administrator access", exact: true });
    await dialog.getByLabel("Reason", { exact: true }).fill("Synthetic browser revocation proof");
    await controlBounds(dialog.getByRole("button", { name: "Revoke access", exact: true }), page);
    await dialog.getByRole("button", { name: "Revoke access", exact: true }).click();
    await expect(viewerRow).toContainText("revoked");
    expect((await safeGet(viewer.request, `${target.api.origin}${CONSOLE}/auth/session`)).status()).toBe(401);
    expect((await safeGet(viewer.request, `${target.api.origin}${CONSOLE}/reports/activity`)).status()).toBe(401);
    await viewer.reload();
    await expect(viewer.getByRole("heading", { name: "Sign in required", exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole("row").filter({ has: page.getByText(email, { exact: true }) })).toContainText("revoked");
    await localScreenshot(page, target, testInfo, "administrator-revoked-reloaded");
    expect((await mailLedger(api, target, fixture)).filter(row => row.recipient_email === email && row.purpose === "invite")).toHaveLength(1);
    expect(forbidden).toBe(0);
    expect(pageErrors).toEqual([]);
    await assertRelease(target);
  } catch (error) {
    primaryFailed = true;
    throw error;
  } finally {
    const failures: string[] = [];
    for (const context of contexts.reverse()) {
      try { await context.close(); } catch { failures.push("owned_browser_context_close_failed"); }
    }
    let cleanup: unknown;
    try { cleanup = await cleanupLocalFixture(api, target, runId, ownedFixture?.manager.id ?? null); }
    catch {
      failures.push("retained_fixture_cleanup_failed");
      cleanup = { run_id: runId, status: "failed", verified: false, automatic_retry: false };
    }
    try { await api.dispose(); } catch { failures.push("owned_api_context_dispose_failed"); }
    await testInfo.attach("pra-retained-fixture-cleanup", {
      body: Buffer.from(JSON.stringify({ cleanup, failures })), contentType: "application/json",
    });
    if (failures.length) {
      testInfo.annotations.push({ type: "cleanup_failure", description: failures.join(", ") });
      if (!primaryFailed) throw new Error("PRA retained fixture cleanup failed; inspect the attached receipt. No automatic retry.");
    }
  }
}

test("PRA-01..08 desktop manager setup MFA reports invite reset and revoke; PRA-09 decoded QR", async ({ page, browser, baseURL }, info) => {
  await journey(page, browser, baseURL, false, info);
});

test("[mobile] PRA-01..08 Pixel 5 setup MFA report controls collapse invite reset and revoke; PRA-09 decoded QR", async ({ page, browser, baseURL }, info) => {
  await journey(page, browser, baseURL, true, info);
});
