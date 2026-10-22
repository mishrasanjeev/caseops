import { createHmac, randomBytes } from "node:crypto";
import { expect, request, type APIRequestContext, type APIResponse, type BrowserContext, type Locator, type Page } from "@playwright/test";

import { localTransportHeaders, noPaidProviderHeaders } from "./cost-controls";
import { assertPublicReleaseIdentity } from "./public-release-identity";
import { AUTHENTICATOR_QR_LABEL, renderedTotpSecret } from "./platform-report-qr";

export const CONSOLE = "/api/platform-console";
export const SESSION_COOKIE = "caseops_console_session";
export const CSRF_COOKIE = "caseops_console_csrf";
export const CSRF_HEADER = "X-Console-CSRF-Token";
const FIXTURE = "/_e2e/platform-console";
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

export type Origins = { web: URL; api: URL; local: boolean; sha: string };
export type ReadOnlyWireGuard = { mutations: number; external: number };
export type ConsoleAuth = {
  state: "mfa_enrollment_required" | "mfa_challenge_required" | "authenticated";
  admin: { id: string; email: string; full_name: string; role: "manager" | "viewer" } | null;
  expires_at: string;
  recovery_codes?: string[] | null;
};
export type FixtureAccount = { id: string; name: string; company_type: string; engagement: "active" | "dormant" | "unknown";
  last_meaningful_activity_at: string | null; active_users: number };
export type FinancialFixture = {
  profit_id: string; payment_id: string; company_id: string; period_start: string; period_end: string; paid_at: string;
  merchant_reference: string; gross_revenue_minor: number; recognized_revenue_minor: number;
  total_variable_cost_minor: number; gross_profit_minor: number; gross_margin_bps: number;
  amount_paid_minor: number; tax_amount_minor: number;
  loss: { company_id: string; company_name: string; gross_profit_minor: number };
  overview: { rollup_count: number; gross_revenue_minor: number; recognized_revenue_minor: number;
    total_variable_cost_minor: number; gross_profit_minor: number };
};
export type LocalFixture = {
  run_id: string;
  account_prefix: string;
  manager: { id: string; email: string; full_name: string };
  initial_invitation_expired: true;
  accounts: FixtureAccount[];
  usage_features: string[];
  financial: FinancialFixture;
  audit_sources: Array<{ id: string; company_id: string; actor_type: "human";
    actor_membership_id: string; action: "employee.login"; result: "success" | "failed";
    target_type: "employee"; target_id: string }>;
  tenant: { slug: string; email: string; password: string };
};
export type CapturedMail = {
  id: string;
  run_id: string;
  recipient_email: string;
  purpose: "invite" | "password_reset";
  link_url: string;
  transport: "deterministic_local";
  provider_call_performed: false;
};
export type CleanupReceipt = {
  run_id: string; status: "revoked" | "not_created"; manager_id: string | null;
  viewer_ids?: string[]; admin_ids?: string[]; token_ids?: string[]; session_ids?: string[];
  delivery_ids?: string[]; retained_audit_ids?: string[]; cleanup_audit_ids?: string[];
  retained: true; deletes: 0; no_provider_calls: true;
  persisted_verified?: true; founder_unchanged?: true;
  invitation_recovery_retention?: { viewer_id: string; user_id: string;
    membership_ids: string[]; audit_ids: string[]; user_preserved: true;
    tenant_memberships_preserved: true; prior_audits_preserved: true };
};
export type ManagedAdmin = { id: string; email: string; full_name: string; role: string;
  status: string; version: number; removed_at: string | null; can_manage: boolean };

export function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`PRA prerequisite missing: ${name}; this is not verified coverage.`);
  return value;
}

export function origins(baseURL: string | undefined, localOnly: boolean, localReleaseSha?: string): Origins {
  if (!baseURL) throw new Error("PRA requires the configured browser baseURL.");
  const web = new URL(baseURL);
  const api = new URL(loopback(web)
    ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
    : required("PROD_API_BASE_URL"));
  if (![web, api].every(url => ["http:", "https:"].includes(url.protocol) && !url.username && !url.password
    && !url.search && !url.hash && url.pathname === "/") || loopback(web) !== loopback(api)) {
    throw new Error("PRA refuses unsafe or mixed origins.");
  }
  const local = loopback(web) && loopback(api);
  if (localOnly && !local) throw new Error("PRA fixture journeys are strictly loopback-only; no fixture action attempted.");
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("PRA remote verification requires canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || localReleaseSha || required("CASEOPS_RELEASE_SHA"))
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  if (!/^[a-f0-9]{40}$/.test(sha)) throw new Error("PRA requires the exact 40-hex expected serving SHA.");
  return { web, api, local, sha };
}

export async function assertRelease(target: Origins): Promise<void> {
  await assertPublicReleaseIdentity([`${target.api.origin}/api/build`, `${target.web.origin}/api/release-identity`], target.sha);
}

export function productionTarget(baseURL: string | undefined): Origins {
  const target = origins(baseURL, false);
  if (target.local) throw new Error("PRA production spec cannot substitute a local result for exact-serving proof.");
  return target;
}

export async function readOnlyWireGuard(context: BrowserContext, target: Origins): Promise<ReadOnlyWireGuard> {
  const guard = { mutations: 0, external: 0 };
  await context.route("**/*", route => {
    const call = route.request();
    if (![target.web.origin, target.api.origin].includes(new URL(call.url()).origin)) {
      guard.external++; return route.abort("blockedbyclient");
    }
    if (!["GET", "HEAD", "OPTIONS"].includes(call.method())) {
      guard.mutations++; return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  return guard;
}

export async function newApi(target: Origins): Promise<APIRequestContext> {
  return request.newContext({ storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: localTransportHeaders(target.api.origin) });
}

export async function json<T>(response: Pick<APIResponse, "status" | "json">, expected: number, operation: string): Promise<T> {
  expect(response.status(), `${operation}: unexpected status; private body omitted.`).toBe(expected);
  return response.json() as Promise<T>;
}

export async function safeGet(api: APIRequestContext, url: string, headers?: Record<string, string>): Promise<APIResponse> {
  try { return await api.get(url, { headers: { ...noPaidProviderHeaders, ...headers }, maxRetries: 0, maxRedirects: 0 }); }
  catch { throw new Error("PRA read transport failed; credentials/private call log omitted. No retry performed."); }
}

export async function safePost(api: APIRequestContext, url: string,
  options: Parameters<APIRequestContext["post"]>[1]): Promise<APIResponse> {
  try { return await api.post(url, { ...options, maxRetries: 0, maxRedirects: 0 }); }
  catch { throw new Error("PRA mutation transport failed; credentials/private call log omitted. No retry performed."); }
}

function fixtureCsrf(): Record<string, string> {
  const nonce = randomBytes(24).toString("hex");
  return { Cookie: `caseops_csrf=${nonce}`, "X-CSRF-Token": nonce };
}

export async function seedLocalFixture(api: APIRequestContext, target: Origins, run: string): Promise<LocalFixture> {
  if (!target.local) throw new Error("No PRA remote fixture creation is permitted.");
  const response = await safePost(api, `${target.api.origin}${FIXTURE}/fixtures`, {
    data: { run_id: run, web_origin: target.web.origin }, headers: fixtureCsrf(), maxRetries: 0, maxRedirects: 0,
  });
  if (response.status() === 404) throw new Error("PRA local fixture hook is missing. Install the agreed test-only wrapper adapter; do not skip setup/MFA.");
  const fixture = await json<LocalFixture>(response, 201, "PRA local seed");
  expect(fixture.run_id).toBe(run);
  expect(fixture.manager.email.endsWith("@example.com")).toBe(true);
  expect(fixture.initial_invitation_expired).toBe(true);
  expect(fixture.accounts).toHaveLength(4);
  expect(fixture.accounts.map(account => account.company_type).sort()).toEqual(["corporate_legal", "law_firm", "solo", "unknown"]);
  expect(fixture.accounts.map(account => account.engagement).sort()).toEqual(["active", "dormant", "unknown", "unknown"]);
  expect(new Set(fixture.accounts.map(account => account.id)).size).toBe(4);
  expect(fixture.usage_features).toEqual(Array.from({ length: 26 }, (_, index) => `pra_browser_${String(index).padStart(2, "0")}`));
  expect(fixture.financial.company_id).toBe(fixture.accounts.find(row => row.company_type === "law_firm")?.id);
  expect(fixture.financial).toEqual(expect.objectContaining({ gross_revenue_minor: 120_000, recognized_revenue_minor: 100_000,
    total_variable_cost_minor: 25_000, gross_profit_minor: 75_000, gross_margin_bps: 7_500,
    amount_paid_minor: 118_000, tax_amount_minor: 18_000, merchant_reference: `PRA-${run}` }));
  const lossAccount = fixture.accounts.find(row => row.company_type === "corporate_legal")!;
  expect(fixture.financial.loss).toEqual({ company_id: lossAccount.id, company_name: lossAccount.name,
    gross_profit_minor: -37 });
  expect(fixture.audit_sources).toHaveLength(4);
  expect(new Set(fixture.audit_sources.map(row => row.id)).size).toBe(4);
  const expectedResults: Record<string, string[]> = { active: ["success"], dormant: ["failed", "success"], unknown: [] };
  for (const account of fixture.accounts) {
    const evidence = fixture.audit_sources.filter(row => row.company_id === account.id);
    const results = account.company_type === "unknown" ? ["success"] : expectedResults[account.engagement];
    expect(evidence.map(row => row.result).sort()).toEqual(results);
    for (const row of evidence) {
      expect(row.actor_type).toBe("human");
      expect(row.action).toBe("employee.login");
      expect(row.target_type).toBe("employee");
      expect(row.target_id).toBe(row.actor_membership_id);
    }
  }
  return fixture;
}

export async function cleanupLocalFixture(api: APIRequestContext, target: Origins, run: string,
  managerId: string | null): Promise<CleanupReceipt> {
  if (!target.local) throw new Error("PRA fixture cleanup is strictly loopback-only.");
  const response = await safePost(api, `${target.api.origin}${FIXTURE}/fixtures/${run}/cleanup`, {
    data: { web_origin: target.web.origin, manager_id: managerId }, headers: fixtureCsrf(), timeout: 10_000,
  });
  const receipt = await json<CleanupReceipt>(response, 200, "PRA retained fixture cleanup");
  expect(receipt.run_id).toBe(run);
  expect(receipt.retained).toBe(true);
  expect(receipt.deletes).toBe(0);
  expect(receipt.no_provider_calls).toBe(true);
  if (managerId !== null) {
    expect(receipt.status).toBe("revoked");
    expect(receipt.manager_id).toBe(managerId);
    expect(receipt.admin_ids).toContain(managerId);
  } else expect(["revoked", "not_created"]).toContain(receipt.status);
  if (receipt.status === "revoked") {
    expect(Boolean(receipt.manager_id)).toBe(true);
    expect(receipt.admin_ids).toContain(receipt.manager_id);
    expect(receipt.persisted_verified).toBe(true);
    expect(receipt.founder_unchanged).toBe(true);
  }
  return receipt;
}

export async function mailLedger(api: APIRequestContext, target: Origins, fixture: LocalFixture): Promise<CapturedMail[]> {
  if (!target.local) throw new Error("PRA production mail capture is forbidden.");
  const response = await api.get(`${target.api.origin}${FIXTURE}/mail`, { params: { run_id: fixture.run_id }, maxRetries: 0 });
  if (response.status() === 404) throw new Error("PRA deterministic mail capture is missing; no live send or database-token fallback is allowed.");
  const ledger = await json<{ items: CapturedMail[]; external_calls: number }>(response, 200, "PRA captured mail");
  expect(ledger.external_calls).toBe(0);
  expect(ledger.items.every(item => item.run_id === fixture.run_id && item.transport === "deterministic_local"
    && item.provider_call_performed === false && item.recipient_email.endsWith("@example.com"))).toBe(true);
  return ledger.items;
}

export async function capturedLink(api: APIRequestContext, target: Origins, fixture: LocalFixture,
  email: string, purpose: CapturedMail["purpose"], priorIds: string[] = []): Promise<string> {
  let matches: CapturedMail[] = [];
  await expect.poll(async () => {
    matches = (await mailLedger(api, target, fixture)).filter(item => item.recipient_email === email
      && item.purpose === purpose && !priorIds.includes(item.id));
    return matches.length;
  }, { message: "One actual deterministic console message is required; no email retry or token fabrication.", timeout: 15_000 }).toBe(1);
  const url = new URL(matches[0].link_url);
  expect(url.origin).toBe(target.web.origin);
  expect(url.pathname).toBe(purpose === "invite" ? "/platform/setup" : "/platform/reset-password");
  expect(url.searchParams.has("token")).toBe(false);
  const tokens = new URLSearchParams(url.hash.slice(1)).getAll("token");
  expect(tokens.length === 1 && tokens[0].length >= 32).toBe(true);
  return url.href;
}

export async function managedAdmin(page: Page, target: Origins, id: string): Promise<ManagedAdmin | null> {
  let cursor: string | null = null;
  const seen = new Set<string>();
  for (let index = 0; index < 20; index++) {
    const query = new URLSearchParams({ limit: "100", ...(cursor ? { cursor } : {}) });
    const data: { items: ManagedAdmin[]; next_cursor: string | null } = await json(
      await safeGet(page.request, `${target.api.origin}${CONSOLE}/admins/manage?${query}`), 200, "Managed directory");
    for (const row of data.items) {
      expect(seen.has(row.id), "Managed directory must not duplicate an identity.").toBe(false);
      seen.add(row.id);
      expect(Number.isInteger(row.version) && row.version > 0).toBe(true);
      expect(row.removed_at).toBeNull();
      expect(typeof row.can_manage).toBe("boolean");
    }
    const row = data.items.find(item => item.id === id);
    if (row) return row;
    cursor = data.next_cursor;
    if (!cursor) return null;
  }
  throw new Error("PRA bounded managed directory did not reach the requested identity or its end.");
}

export async function ageViewerInvitation(page: Page, target: Origins, fixture: LocalFixture,
  viewerId: string): Promise<void> {
  if (!target.local) throw new Error("PRA invitation fixture clock is strictly loopback-only.");
  const cookies = await page.context().cookies();
  const session = cookies.find(cookie => cookie.name === SESSION_COOKIE)?.value;
  const csrf = cookies.find(cookie => cookie.name === CSRF_COOKIE)?.value;
  if (!session || !csrf) throw new Error("PRA fixture aging requires its real manager console session.");
  const ordinary = fixtureCsrf();
  const response = await safePost(page.request,
    `${target.api.origin}${FIXTURE}/fixtures/${fixture.run_id}/age-viewer-invitation`, {
      data: { web_origin: target.web.origin, manager_id: fixture.manager.id, viewer_id: viewerId },
      headers: { ...noPaidProviderHeaders, ...ordinary, [CSRF_HEADER]: csrf,
        Cookie: `${ordinary.Cookie}; ${SESSION_COOKIE}=${session}; ${CSRF_COOKIE}=${csrf}` }, timeout: 10_000,
    });
  const receipt = await json<{ run_id: string; manager_id: string; viewer_id: string;
    aged_minutes: number; only_created_at_changed: boolean; expiry_hash_credential_epoch_preserved: boolean;
    no_provider_calls: boolean }>(response, 200, "Fixed pending-invitation age");
  expect(receipt).toEqual(expect.objectContaining({ run_id: fixture.run_id, manager_id: fixture.manager.id,
    viewer_id: viewerId, aged_minutes: 6, only_created_at_changed: true,
    expiry_hash_credential_epoch_preserved: true, no_provider_calls: true }));
}

export function secretToken(link: string): string {
  const token = new URLSearchParams(new URL(link).hash.slice(1)).get("token");
  if (!token) throw new Error("PRA captured message has no fragment token.");
  return token;
}

// Same RFC6238 SHA1/30s test generator as the existing legal-hold browser journey.
export function totp(secret: string): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  if (!/^[A-Z2-7]+$/.test(secret)) throw new Error("PRA enrollment returned an invalid test TOTP secret.");
  const bits = [...secret].map(letter => alphabet.indexOf(letter).toString(2).padStart(5, "0")).join("");
  const key = Buffer.from((bits.match(/.{8}/g) ?? []).map(byte => parseInt(byte, 2)));
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000)));
  const digest = createHmac("sha1", key).update(counter).digest();
  return String((digest.readUInt32BE(digest[digest.length - 1] & 15) & 0x7fffffff) % 1_000_000).padStart(6, "0");
}

export async function controlBounds(control: Locator, page: Page, minimumHeight = 24): Promise<void> {
  await control.scrollIntoViewIfNeeded();
  await control.evaluate(element => element.scrollIntoView({ block: "center", inline: "center" }));
  await expect(control).toBeVisible();
  const box = await control.boundingBox();
  const viewport = page.viewportSize();
  expect(Boolean(box && viewport && box.width >= 24 && box.height >= minimumHeight && box.x >= -0.5 && box.y >= -0.5
    && box.x + box.width <= viewport.width + 0.5 && box.y + box.height <= viewport.height + 0.5),
  "PRA control must have positive useful dimensions and be fully within the available viewport.").toBe(true);
  const main = page.locator("main");
  if (await main.count() === 1) {
    const mainBox = await main.boundingBox();
    if (mainBox && box && await control.evaluate(element => Boolean(element.closest("main")))) {
      expect(box.x).toBeGreaterThanOrEqual(mainBox.x - 0.5);
      expect(box.x + box.width).toBeLessThanOrEqual(mainBox.x + mainBox.width + 0.5);
    }
  }
}

export async function noOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
}

export async function passwordControl(page: Page, label: string): Promise<void> {
  const input = page.getByLabel(label, { exact: true });
  const wrapper = input.locator("..");
  await controlBounds(input, page);
  const reveal = wrapper.getByRole("button", { name: "Show password", exact: true });
  await controlBounds(reveal, page);
  await reveal.click();
  await expect(input).toHaveAttribute("type", "text");
  const hide = wrapper.getByRole("button", { name: "Hide password", exact: true });
  await controlBounds(hide, page);
  await hide.click();
  await expect(input).toHaveAttribute("type", "password");
  await noOverflow(page);
}

export async function contextCsrf(context: BrowserContext): Promise<Record<string, string>> {
  const csrf = (await context.cookies()).find(cookie => cookie.name === CSRF_COOKIE)?.value;
  if (!csrf) throw new Error("PRA console CSRF cookie missing; no mutation attempted.");
  return { ...noPaidProviderHeaders, [CSRF_HEADER]: csrf };
}

export async function expectState(page: Page, target: Origins, state: ConsoleAuth["state"]): Promise<ConsoleAuth> {
  const auth = await json<ConsoleAuth>(await safeGet(page.request, `${target.api.origin}${CONSOLE}/auth/session`), 200, "Console session");
  expect(auth.state).toBe(state);
  expect(Number.isFinite(Date.parse(auth.expires_at))).toBe(true);
  if (state === "authenticated") expect(Boolean(auth.admin && ["manager", "viewer"].includes(auth.admin.role))).toBe(true);
  return auth;
}

export async function completeSetup(page: Page, link: string, password: string, fullName: string,
  expectedStatus = 200): Promise<void> {
  try { await page.goto(link); } catch { throw new Error("PRA setup navigation failed; private link omitted."); }
  await expect.poll(() => new URL(page.url()).hash === "", {
    message: "The one-use fragment must be consumed; secret omitted.",
  }).toBe(true);
  expect(new URL(page.url()).searchParams.has("token")).toBe(false);
  await page.getByLabel("Full name", { exact: true }).fill(fullName);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByLabel("Confirm password", { exact: true }).fill(password);
  await passwordControl(page, "Password");
  await passwordControl(page, "Confirm password");
  await controlBounds(page.getByRole("button", { name: "Accept invitation", exact: true }), page);
  const completing = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/invitations/complete`
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Accept invitation", exact: true }).click();
  expect((await completing).status()).toBe(expectedStatus);
}

export async function enrollMfa(page: Page, target: Origins, accountEmail: string): Promise<string[]> {
  await expectState(page, target, "mfa_enrollment_required");
  expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/reports/activity`)).status()).toBe(403);
  const enrolling = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/mfa/enroll`
    && response.request().method() === "POST");
  await controlBounds(page.getByRole("button", { name: "Set up authenticator", exact: true }), page);
  await page.getByRole("button", { name: "Set up authenticator", exact: true }).click();
  const enrollment = await json<{ secret: string; otpauth_url: string }>(await enrolling, 200, "MFA enrollment");
  expect(Object.keys(enrollment).sort()).toEqual(["otpauth_url", "secret"]);
  expect(enrollment.otpauth_url.startsWith("otpauth://totp/")).toBe(true);
  const setupKey = page.getByLabel("Authenticator setup key", { exact: true });
  await expect(setupKey).toBeVisible();
  await expect(setupKey).toHaveAttribute("readonly", "");
  expect(await setupKey.inputValue() === enrollment.secret, "Visible setup key must match the actual enrollment DTO.").toBe(true);
  const decodedSecret = await renderedTotpSecret(page, enrollment, accountEmail);
  await controlBounds(page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true }), page);
  await noOverflow(page);
  const verifying = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/mfa/verify`
    && response.request().method() === "POST");
  await page.getByLabel("Six-digit code", { exact: true }).fill(totp(decodedSecret));
  await controlBounds(page.getByRole("button", { name: "Verify MFA", exact: true }), page);
  await page.getByRole("button", { name: "Verify MFA", exact: true }).click();
  const auth = await json<ConsoleAuth>(await verifying, 200, "Initial MFA verification");
  expect(auth.state).toBe("authenticated");
  await expect(page.getByRole("img", { name: AUTHENTICATOR_QR_LABEL, exact: true })).toHaveCount(0);
  await expect(setupKey).toHaveCount(0);
  expect(Boolean(auth.recovery_codes && auth.recovery_codes.length >= 2)).toBe(true);
  const cookie = (await page.context().cookies()).find(row => row.name === SESSION_COOKIE);
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.path).toBe(CONSOLE);
  await controlBounds(page.getByRole("button", { name: "Continue to reports", exact: true }), page);
  await page.getByRole("button", { name: "Continue to reports", exact: true }).click();
  return [...auth.recovery_codes!];
}

export async function signInWithRecovery(page: Page, target: Origins, email: string, password: string,
  recoveryCode: string, rejectedRecoveryCode?: string): Promise<void> {
  await page.goto(`${target.web.origin}/platform/sign-in`);
  const form = page.getByRole("form", { name: "Platform sign in", exact: true });
  await form.getByLabel("Email", { exact: true }).fill(email);
  await form.getByLabel("Password", { exact: true }).fill(password);
  await passwordControl(page, "Password");
  await controlBounds(form.getByRole("button", { name: "Sign in", exact: true }), page);
  const loggingIn = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/login`
    && response.request().method() === "POST");
  await form.getByRole("button", { name: "Sign in", exact: true }).click();
  expect((await json<ConsoleAuth>(await loggingIn, 200, "Console login")).state).toBe("mfa_challenge_required");
  await expectState(page, target, "mfa_challenge_required");
  expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/reports/activity`)).status()).toBe(403);
  await controlBounds(page.getByRole("button", { name: "Recovery code", exact: true }), page);
  await page.getByRole("button", { name: "Recovery code", exact: true }).click();
  if (rejectedRecoveryCode) {
    await page.getByLabel("Recovery code", { exact: true }).fill(rejectedRecoveryCode);
    const rejecting = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/mfa/verify`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Verify MFA", exact: true }).click();
    expect((await rejecting).status()).toBe(401);
    await expect(page.getByRole("main").getByRole("alert")).toBeVisible();
    await expectState(page, target, "mfa_challenge_required");
    expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/reports/activity`)).status()).toBe(403);
  }
  await page.getByLabel("Recovery code", { exact: true }).fill(recoveryCode);
  await controlBounds(page.getByRole("button", { name: "Verify MFA", exact: true }), page);
  const verifying = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/mfa/verify`
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Verify MFA", exact: true }).click();
  expect((await json<ConsoleAuth>(await verifying, 200, "Recovery MFA verification")).state).toBe("authenticated");
  await expectState(page, target, "authenticated");
  await controlBounds(page.getByRole("button", { name: "Continue to reports", exact: true }), page);
  await page.getByRole("button", { name: "Continue to reports", exact: true }).click();
}
