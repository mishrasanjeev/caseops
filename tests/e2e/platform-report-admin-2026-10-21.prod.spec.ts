/** Fake-state renderer contracts, never real owner setup/MFA or report-access acceptance. */
import { expect, test } from "./support/prod-diagnostic-test";
import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { CONSOLE, CSRF_COOKIE, CSRF_HEADER, assertRelease, controlBounds, noOverflow, origins, totp,
  type ConsoleAuth, type Origins } from "./support/platform-report-admin";
import { AUTHENTICATOR_QR_LABEL, renderedTotpSecret } from "./support/platform-report-qr";
import type { BrowserContext, Page } from "@playwright/test";
import { activityFixture } from "../../apps/web/lib/platform/activity-fixture.test-data";
import { consoleManagedAdminsResponse, consoleNamedOverview, consoleNamedReportPage } from "../../apps/web/lib/platform/schemas";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });

const fakeAccount = { id: "00000000-0000-4000-8000-000000000021", email: "qr-renderer@example.com",
  full_name: "Local QR renderer fixture", role: "manager" as const };
// Public, synthetic test material only; no real user's factor or session is used.
const fakeSecret = "JBSWY3DPEHPK3PXP";
const fakeCsrf = "qr-renderer-only-csrf";
const enrollment = { secret: fakeSecret, otpauth_url: `otpauth://totp/${encodeURIComponent(`CaseOps Reports:${fakeAccount.email}`)}`
  + `?secret=${fakeSecret}&issuer=CaseOps%20Reports&algorithm=SHA1&digits=6&period=30` };
const createdAt = "2026-10-22T00:00:00Z";
const pendingViewer = { id: "00000000-0000-4000-8000-000000000029", email: "pending-renderer@example.com",
  full_name: "Pending renderer viewer", role: "viewer", status: "pending", created_at: createdAt,
  version: 2, removed_at: null, can_manage: true };
const revokedViewer = { ...pendingViewer, id: "00000000-0000-4000-8000-000000000030",
  email: "revoked-renderer@example.com", full_name: "Revoked renderer viewer", status: "revoked", version: 3 };
const protectedViewer = { ...pendingViewer, id: "00000000-0000-4000-8000-000000000031",
  email: "protected-renderer@example.com", full_name: "Protected renderer viewer", can_manage: false };
const managedDirectory = consoleManagedAdminsResponse.parse({ items: [
  { ...fakeAccount, status: "active", created_at: createdAt, version: 1, removed_at: null, can_manage: false },
  pendingViewer, revokedViewer, protectedViewer,
], next_cursor: null });
const account = { company_id: "00000000-0000-4000-8000-000000000045",
  company_name: "Synthetic international account renderer " + "UnbrokenSyntheticCompanyLabel".repeat(3) };
const amounts = { ...account, gross_revenue_minor: 100, recognized_revenue_minor: 100,
  tax_minor: 0, discounts_minor: 0, payment_provider_cost_minor: 0, payment_gateway_cost_minor: 137,
  llm_cost_minor: 0, embedding_cost_minor: 0, case_refresh_cost_minor: 0, document_processing_cost_minor: 0,
  storage_cost_minor: 0, manual_support_cost_minor: 0, manual_research_cost_minor: 0,
  total_variable_cost_minor: 137, gross_profit_minor: -37, gross_margin_bps: -3700 };
const report = (items: unknown[], coverage: string) => consoleNamedReportPage.parse({
  items, coverage, generated_at: createdAt, has_more: false, next_cursor: null,
});
const namedReports = {
  usage: report([{ ...account, feature_key: "synthetic_renderer", quantity: 2, credits: 0,
    estimated_internal_cost_minor: 37 }], "recorded_usage"),
  revenue: report([{ ...account, paid_at: createdAt, merchant_reference: "SYNTHETIC-RENDERER",
    amount_paid_minor: 37, tax_amount_minor: 37 }], "recorded_payments"),
  profit: report([{ ...amounts, tax_collected_minor: 0, discount_minor: 0,
    period_start: createdAt, period_end: "2026-10-23T00:00:00Z", status: "estimated" }], "recorded_rollups"),
  "company-profitability": report([{ ...amounts, rollup_count: 1, loss_risk: true }], "recorded_rollups"),
};
const namedOverview = consoleNamedOverview.parse({ generated_at: createdAt, coverage: "recorded_rollups",
  rollup_count: 1, mrr_minor: 0, arr_minor: 0, active_subscriptions: 0, trial_count: 0, failed_payments: 0,
  gross_revenue_minor: 100, recognized_revenue_minor: 100, total_variable_cost_minor: 137,
  gross_profit_minor: -37, gross_margin_bps: -3700, margin_alerts: [{ ...account,
    gross_profit_minor: -37, gross_margin_bps: -3700 }], margin_alerts_has_more: false });

async function mockConsole(context: BrowserContext, target: Origins, initial: ConsoleAuth["state"] | "anonymous") {
  let state = initial;
  let role: "manager" | "viewer" = "manager";
  const reads: string[] = [];
  const calls = { enroll: 0, verify: 0, refused: 0, external: 0, expectedCode: "" };
  const auth = (): ConsoleAuth => ({ state: state === "anonymous" ? "mfa_challenge_required" : state,
    admin: state === "authenticated" ? { ...fakeAccount, role } : null, expires_at: "2099-01-01T00:00:00Z" });
  await context.addCookies([{ name: CSRF_COOKIE, value: fakeCsrf, url: target.web.origin, sameSite: "Lax" }]);
  await context.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (![target.web.origin, target.api.origin].includes(url.origin)) {
      calls.external++; await route.abort("blockedbyclient"); return;
    }
    const headers = { "access-control-allow-origin": target.web.origin, "access-control-allow-credentials": "true",
      "access-control-allow-headers": `Content-Type, ${CSRF_HEADER}, X-CaseOps-Automated-Test`, "access-control-allow-methods": "GET, POST, OPTIONS" };
    if (url.origin === target.api.origin && url.pathname.startsWith(`${CONSOLE}/`)) {
      if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
      if (request.method() === "GET" && url.pathname === `${CONSOLE}/auth/session`) {
        await route.fulfill({ status: state === "anonymous" ? 401 : 200, headers,
          json: state === "anonymous" ? { detail: "Authentication required." } : auth() }); return;
      }
      if (request.method() === "GET" && state === "authenticated") {
        expect(request.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
        if (url.pathname === `${CONSOLE}/admins/manage` && role === "manager") {
          expect(url.searchParams.get("limit")).toBe("50");
          reads.push("managed");
          await route.fulfill({ status: 200, headers, json: managedDirectory }); return;
        }
        if (url.pathname === `${CONSOLE}/reports/activity`) {
          await route.fulfill({ status: 200, headers, json: activityFixture() }); return;
        }
        const kind = url.pathname.slice(`${CONSOLE}/reports/`.length);
        if (url.pathname.startsWith(`${CONSOLE}/reports/`) && (kind === "overview" || kind in namedReports)) {
          expect(url.searchParams.get("include_account_names")).toBe("true");
          reads.push(kind);
          await route.fulfill({ status: 200, headers,
            json: kind === "overview" ? namedOverview : namedReports[kind as keyof typeof namedReports] }); return;
        }
      }
      if (request.method() === "POST" && state === "mfa_enrollment_required"
        && request.headers()[CSRF_HEADER.toLowerCase()] === fakeCsrf) {
        if (url.pathname === `${CONSOLE}/auth/mfa/enroll`) {
          calls.enroll++; expect(request.postDataJSON()).toEqual({});
          await route.fulfill({ status: 200, headers, json: enrollment }); return;
        }
        if (url.pathname === `${CONSOLE}/auth/mfa/verify` && calls.enroll === 1) {
          const body = request.postDataJSON();
          expect(Object.keys(body)).toEqual(["code"]);
          expect(Boolean(calls.expectedCode && body.code === calls.expectedCode), "Only the decoded synthetic factor is accepted.").toBe(true);
          calls.verify++; state = "authenticated";
          await route.fulfill({ status: 200, headers, json: { ...auth(), recovery_codes: ["LOCAL-ONLY-RECOVERY-1", "LOCAL-ONLY-RECOVERY-2"] } }); return;
        }
      }
      calls.refused++; await route.abort("blockedbyclient"); return;
    }
    if (url.origin === target.web.origin && ["GET", "HEAD"].includes(request.method())) {
      await route.continue(); return;
    }
    calls.refused++; await route.abort("blockedbyclient");
  });
  return { calls, reads, setState(next: ConsoleAuth["state"] | "anonymous", nextRole: typeof role = "manager") {
    state = next; role = nextRole;
  } };
}

async function readonlyRecoveryAndNames(page: Page, target: Origins, mocked: Awaited<ReturnType<typeof mockConsole>>) {
  mocked.setState("authenticated", "viewer");
  await page.goto(`${target.web.origin}/platform/admins`);
  await expect(page.getByRole("main").getByRole("heading", { name: "Access denied", exact: true })).toBeVisible();
  expect(mocked.reads).toEqual([]);
  mocked.setState("authenticated");
  await page.goto(`${target.web.origin}/platform/admins`);
  await expect(page.getByRole("heading", { name: "Report administrators", exact: true })).toBeVisible();
  const row = (email: string) => page.getByRole("row").filter({ has: page.getByText(email, { exact: true }) });
  const pending = row(pendingViewer.email);
  await expect(pending).toContainText("pending");
  const resend = pending.getByRole("button", { name: `Resend invitation for ${pendingViewer.full_name}`, exact: true });
  await expect(resend).toBeEnabled();
  await controlBounds(resend, page);
  await pending.getByRole("button", { name: "Revoke", exact: true }).click();
  const revoke = page.getByRole("form", { name: "Revoke administrator access", exact: true });
  await expect(revoke.getByRole("button", { name: "Revoke access", exact: true })).toBeVisible();
  await revoke.getByRole("button", { name: "Cancel", exact: true }).click();
  const again = row(revokedViewer.email).getByRole("button", { name: `Invite ${revokedViewer.full_name} again`, exact: true });
  await controlBounds(again, page);
  await again.click();
  await expect(page.getByLabel("Email", { exact: true })).toHaveValue(revokedViewer.email);
  await expect(page.getByLabel("Full name", { exact: true })).toHaveValue(revokedViewer.full_name);
  const remove = pending.getByRole("button", { name: `Delete report access for ${pendingViewer.full_name}`, exact: true });
  await controlBounds(remove, page);
  await remove.click();
  const deletion = page.getByRole("form", { name: "Delete administrator access", exact: true });
  await expect(deletion).toContainText("Tenant accounts and audit history will be retained.");
  await expect(deletion.getByRole("button", { name: "Delete report access", exact: true })).toBeVisible();
  await deletion.getByRole("button", { name: "Cancel", exact: true }).click();
  for (const admin of [fakeAccount, protectedViewer]) {
    const protectedRow = row(admin.email);
    await expect(protectedRow).toHaveCount(1);
    await expect(protectedRow.getByRole("button")).toHaveCount(admin.id === fakeAccount.id ? 2 : 3);
    for (const button of await protectedRow.getByRole("button").all()) await expect(button).toBeDisabled();
  }
  await noOverflow(page);
  await page.getByRole("button", { name: "Reload administrators", exact: true }).click();
  await expect.poll(() => mocked.reads.filter(kind => kind === "managed").length).toBe(2);
  await expect(pending).toContainText("pending");
  await page.goto(`${target.web.origin}/platform/reports`);
  await expect(page.getByRole("region", { name: "Canonical account activity report", exact: true })).toBeVisible();
  for (const [tab, kind] of [["Overview", "overview"], ["Usage", "usage"], ["Profit", "profit"],
    ["Account profitability", "company-profitability"], ["Revenue", "revenue"]]) {
    for (const reload of [false, true]) {
      if (reload) {
        await page.reload();
        await expect(page.getByRole("region", { name: "Canonical account activity report", exact: true })).toBeVisible();
      }
      const loaded = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/reports/${kind}`);
      const tabControl = page.getByRole("tab", { name: tab, exact: true });
      await controlBounds(tabControl, page);
      await tabControl.click();
      expect((await loaded).status()).toBe(200);
      const panel = page.getByRole("tabpanel");
      await expect(panel.getByRole("alert")).toHaveCount(0);
      if (kind === "overview") {
        await expect(panel.getByText("Configured monthly run rate", { exact: true })).toBeVisible();
        const alert = panel.getByRole("list", { name: "Margin and cost alerts", exact: true }).getByRole("listitem");
        await controlBounds(alert.getByText(account.company_name, { exact: true }), page, 1);
        await expect(alert.getByText(account.company_name, { exact: true })).toHaveText(account.company_name);
        await expect(alert.locator("p").nth(1)).toHaveText(`${account.company_id}: -\u20b90.37; margin -37.0%`);
      } else {
        const cell = panel.getByRole("row").filter({ has: page.getByText(account.company_id, { exact: true }) }).getByRole("cell").first();
        for (const value of [account.company_name, account.company_id]) {
          const text = cell.getByText(value, { exact: true });
          await text.scrollIntoViewIfNeeded();
          await expect(text).toBeInViewport({ ratio: 0.95 });
          await expect(text).toHaveText(value);
        }
        const cells = cell.locator("..").getByRole("cell");
        if (kind === "usage" || kind === "revenue") await expect(cells.last()).toHaveText("\u20b90.37");
        else await expect(cells.nth(4)).toHaveText("-\u20b90.37");
      }
      await noOverflow(page);
    }
  }
  expect(mocked.reads).toEqual(["managed", "managed", "overview", "overview", "usage", "usage",
    "profit", "profit", "company-profitability", "company-profitability", "revenue", "revenue"]);
}

for (const width of [1280, 393]) {
  test(`PRA-09 QR renderer component contract ${width}px decodes pixels and removes enrollment after mocked verification`, async ({ page, context, baseURL }, info) => {
    info.annotations.push({ type: "scope", description: "Synthetic PRA-09..13 renderer only: mocked MFA, managed eligibility and named reports; no real owner acceptance, invitation, removal or API mutation." });
    const target = origins(baseURL, false, e2eEnv.CASEOPS_RELEASE_SHA);
    if (!target.local) await assertRelease(target);
    const mocked = await mockConsole(context, target, "anonymous");
    const { calls } = mocked;
    await page.setViewportSize({ width, height: 900 });
    for (const state of ["anonymous", "mfa_challenge_required"] as const) {
      mocked.setState(state);
      await page.goto(`${target.web.origin}/platform/security`);
      if (state === "anonymous") await expect(page.getByText("Sign in to manage your platform account.", { exact: true })).toBeVisible();
      else await expect(page.getByRole("heading", { name: "Verify multi-factor authentication", exact: true })).toBeVisible();
      await expect(page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true })).toHaveCount(0);
      await expect(page.getByLabel("Authenticator setup key", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Set up authenticator", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Administrators", exact: true })).toHaveCount(0);
      await noOverflow(page);
      expect(calls).toEqual({ enroll: 0, verify: 0, refused: 0, external: 0, expectedCode: "" });
    }
    mocked.setState("mfa_enrollment_required");
    await page.goto(`${target.web.origin}/platform/security`);
    const qr = page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true });
    await expect(page.getByRole("button", { name: "Set up authenticator", exact: true })).toBeVisible();
    await expect(qr).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Administrators", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: "Set up authenticator", exact: true }).click();
    const decoded = await renderedTotpSecret(page, enrollment, fakeAccount.email);
    await controlBounds(qr, page);
    await noOverflow(page);
    const setupKey = page.getByLabel("Authenticator setup key", { exact: true });
    await expect(setupKey).toHaveAttribute("readonly", "");
    expect(await setupKey.inputValue() === decoded, "Manual fallback must match decoded synthetic QR.").toBe(true);
    calls.expectedCode = totp(decoded);
    await page.getByLabel("Six-digit code", { exact: true }).fill(calls.expectedCode);
    await page.getByRole("button", { name: "Verify MFA", exact: true }).click();
    await expect(page.getByRole("heading", { name: "MFA verified", exact: true })).toBeVisible();
    await expect(qr).toHaveCount(0);
    await expect(setupKey).toHaveCount(0);
    expect((await page.content()).includes(fakeSecret), "Enrollment secret must leave the rendered document after success.").toBe(false);
    expect(calls).toEqual({ enroll: 1, verify: 1, refused: 0, external: 0, expectedCode: calls.expectedCode });
    await readonlyRecoveryAndNames(page, target, mocked);
    expect(calls).toEqual({ enroll: 1, verify: 1, refused: 0, external: 0, expectedCode: calls.expectedCode });
    if (!target.local) await assertRelease(target);
  });
}
