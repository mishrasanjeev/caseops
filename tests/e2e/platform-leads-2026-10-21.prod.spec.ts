/** Non-mutating anonymous checks and synthetic renderer contracts, never real owner/lead/email acceptance. */
import type { BrowserContext } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { leadControls, leadDetails, type Lead } from "./support/platform-leads";
import { CONSOLE, assertRelease, newApi, noOverflow, origins, readOnlyWireGuard, safeGet,
  type ConsoleAuth, type Origins } from "./support/platform-report-admin";
import { expect, test } from "./support/prod-diagnostic-test";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: noPaidProviderHeaders,
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });

const synthetic: Lead = {
  id: "00000000-0000-4000-8000-000000000021", submitted_at: "2026-10-21T20:00:00Z",
  contact_name: "Synthetic renderer only", contact_email: "renderer@example.com", contact_mobile: "+910000000000",
  company_name: "Synthetic firm", segment: "firm", selected_plan: "synthetic-plan", source: "pricing_page", role: "partner",
  intent: "pricing", notes: "Renderer fixture only\n<script>never execute</script>", privacy_notice_version: "2026-10-21",
  notification: { status: "outcome_unknown", attempts: 1, last_error_code: "transport_outcome_unknown", eligible: true },
};
const second = { ...synthetic, id: "00000000-0000-4000-8000-000000000022", contact_email: "second-renderer@example.com",
  notification: { ...synthetic.notification, status: "accepted" as const, last_error_code: null } };

async function syntheticConsole(context: BrowserContext, target: Origins) {
  let state: "anonymous" | ConsoleAuth["state"] = "anonymous";
  let role: "manager" | "viewer" = "manager";
  const reads: (string | null)[] = [];
  const denied = { mutations: 0, external: 0, unexpected: 0 };
  const cursor = "synthetic+signed/cursor=2";
  await context.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (![target.web.origin, target.api.origin].includes(url.origin)) {
      denied.external++; await route.abort("blockedbyclient"); return;
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(request.method())) {
      denied.mutations++; await route.abort("blockedbyclient"); return;
    }
    if (url.origin === target.api.origin && url.pathname.startsWith(`${CONSOLE}/`)) {
      const headers = { "access-control-allow-origin": target.web.origin, "access-control-allow-credentials": "true",
        "access-control-allow-headers": "Content-Type, X-CaseOps-Automated-Test", "access-control-allow-methods": "GET, OPTIONS" };
      if (request.method() === "OPTIONS") { await route.fulfill({ status: 204, headers }); return; }
      expect(request.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      if (url.pathname === `${CONSOLE}/auth/session`) {
        await route.fulfill({ status: state === "anonymous" ? 401 : 200, headers, json: state === "anonymous" ? { detail: "Authentication required" } : {
          state, admin: state === "authenticated" ? { id: "synthetic-renderer", email: "renderer@example.com", full_name: "Synthetic renderer", role } : null,
          expires_at: "2099-01-01T00:00:00Z",
        } }); return;
      }
      if (url.pathname === `${CONSOLE}/leads` && state === "authenticated" && role === "manager") {
        expect(url.searchParams.get("limit")).toBe("25");
        const current = url.searchParams.get("cursor");
        reads.push(current);
        expect([null, cursor]).toContain(current);
        await route.fulfill({ status: 200, headers, json: current === cursor
          ? { items: [second], next_cursor: null, has_more: false }
          : { items: [synthetic], next_cursor: cursor, has_more: true } }); return;
      }
      denied.unexpected++; await route.abort("blockedbyclient"); return;
    }
    if (url.origin === target.web.origin) { await route.continue(); return; }
    denied.unexpected++; await route.abort("blockedbyclient");
  });
  return { reads, denied, cursor, set(next: typeof state, nextRole: typeof role = "manager") { state = next; role = nextRole; } };
}

for (const width of [1280, 393]) {
  test(`LEAD-02 anonymous protected-route denial ${width}px is read-only`, async ({ page, context, baseURL }, info) => {
    info.annotations.push({ type: "scope", description: "Real anonymous reads only; no lead, mail, setup or owner acceptance." });
    const target = origins(baseURL, false, e2eEnv.CASEOPS_RELEASE_SHA);
    await assertRelease(target);
    const api = await newApi(target);
    try {
      expect((await safeGet(api, `${target.api.origin}${CONSOLE}/leads?limit=25`)).status()).toBe(401);
      const guard = await readOnlyWireGuard(context, target);
      await page.setViewportSize({ width, height: 900 });
      await page.goto(`${target.web.origin}/platform/leads`);
      await expect(page.getByRole("main").getByRole("heading", { name: "Sign in required", exact: true })).toBeVisible();
      await expect(page.getByRole("link", { name: "Sign in to platform reports", exact: true })).toHaveAttribute("href", "/platform/sign-in");
      await expect(page.getByRole("region", { name: "Public leads", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Leads", exact: true })).toHaveCount(0);
      await noOverflow(page);
      expect(guard).toEqual({ mutations: 0, external: 0 });
      await assertRelease(target);
    } finally { await api.dispose(); }
  });

  test(`LEAD-03 synthetic renderer only ${width}px details pagination roles and revocation`, async ({ page, context, baseURL }, info) => {
    info.annotations.push({ type: "scope", description: "Mocked GET renderer only; no real admission/API lead/email or owner MFA acceptance." });
    const target = origins(baseURL, false, e2eEnv.CASEOPS_RELEASE_SHA);
    await assertRelease(target);
    const mock = await syntheticConsole(context, target);
    await page.setViewportSize({ width, height: 900 });
    const main = page.getByRole("main");
    for (const [state, role, heading] of [
      ["anonymous", "manager", "Sign in required"],
      ["mfa_enrollment_required", "manager", "Verification required"],
      ["mfa_challenge_required", "manager", "Verification required"],
      ["authenticated", "viewer", "Access denied"],
    ] as const) {
      mock.set(state, role);
      await page.goto(`${target.web.origin}/platform/leads`);
      await expect(main.getByRole("heading", { name: heading, exact: true })).toBeVisible();
      await expect(page.getByRole("region", { name: "Public leads", exact: true })).toHaveCount(0);
      await expect(page.getByRole("link", { name: "Leads", exact: true })).toHaveCount(0);
      await noOverflow(page);
      expect(mock.reads).toEqual([]);
    }
    mock.set("authenticated");
    await page.goto(`${target.web.origin}/platform/leads`);
    await expect(main.getByRole("heading", { name: "Leads", exact: true })).toBeVisible();
    await leadDetails(page, synthetic);
    await expect(main.getByText("Outcome unknown", { exact: true })).toBeVisible();
    await expect(main.getByText("Inspect delivery evidence before any further send.")).toBeVisible();
    await leadControls(page);
    await page.getByRole("button", { name: "Next page", exact: true }).click();
    await leadDetails(page, second);
    await expect(main.getByText("Provider accepted", { exact: true })).toBeVisible();
    await expect(main.getByText(synthetic.id, { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Next page", exact: true })).toBeDisabled();
    await page.getByRole("button", { name: "Reload leads", exact: true }).click();
    await expect.poll(() => mock.reads.length).toBe(3);
    await expect(main.getByText(second.contact_email!, { exact: true }).first()).toBeVisible();
    await page.getByRole("button", { name: "Previous page", exact: true }).click();
    await expect(main.getByText(synthetic.contact_email!, { exact: true }).first()).toBeVisible();
    expect(mock.reads).toEqual([null, mock.cursor, mock.cursor, null]);
    mock.set("anonymous");
    await page.reload();
    await expect(main.getByRole("heading", { name: "Sign in required", exact: true })).toBeVisible();
    await expect(main.getByText(synthetic.contact_email!, { exact: true })).toHaveCount(0);
    expect(mock.denied).toEqual({ mutations: 0, external: 0, unexpected: 0 });
    await assertRelease(target);
  });
}
