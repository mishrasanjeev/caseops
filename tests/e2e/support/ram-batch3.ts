/** Client-only batch 3 support. Remote KYC is retained evidence, never freshly fabricated. */
import { createHash, randomUUID } from "node:crypto";
import { expect, request, type APIRequestContext, type APIResponse, type BrowserContext,
  type Locator, type Page, type TestInfo } from "@playwright/test";
import type { ClientRecord } from "../../../apps/web/lib/api/endpoints";
import { localTransportHeaders } from "./cost-controls";
import { apiBaseUrl, e2eEnv } from "./env";
import { assertPublicReleaseIdentity } from "./public-release-identity";

export const batch3QaMarker = "CASEOPS-SYNTHETIC-QA:RAM-BATCH3:CLIENT-CONTACT; not real legal identity evidence";
export const batch3ContactFields = [
  ["primary_contact_name", "Primary contact"], ["primary_contact_email", "Email"],
  ["primary_contact_phone", "Phone"], ["address_line_1", "Address line 1"],
  ["address_line_2", "Address line 2"], ["city", "City"], ["state", "State"],
  ["postal_code", "Postal code"], ["country", "Country"],
] as const;
export type ContactKey = (typeof batch3ContactFields)[number][0];
export type ContactPatch = Partial<Record<ContactKey, string | null>>;
type Credentials = { company_slug: string; email: string; password: string };
type Actor = { access_token: string; company: { id: string; slug: string };
  user: { email: string }; membership: { id: string; role: string }; capabilities: string[] };
type Audit = { matter_id: string; total: number; events: Array<{
  target_id: string | null; action: string; metadata: Record<string, unknown> | null;
}> };
export type Batch3ClientFixture = { client: ClientRecord; matterId: string; retainedHash: string; audit: Audit };
export type Batch3ClientRuntime = {
  web: URL; api: URL; local: boolean; run: string; actor: Actor; credentials: Credentials;
  http: APIRequestContext; headers: Record<string, string>; release: () => Promise<void>;
  contexts: APIRequestContext[]; patches: ContactPatch[]; refused: string[];
  fixture?: Batch3ClientFixture;
};
const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
const loopback = (url: URL) => ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
const contactKeys = new Set<string>(batch3ContactFields.map(([key]) => key));

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing approved batch 3 setup is not a skip.`);
  return value;
}

export async function batch3Json<T>(response: APIResponse, label: string, status = 200): Promise<T> {
  expect(response.status(), `${label}; private response intentionally omitted`).toBe(status);
  try { return await response.json() as T; }
  catch { throw new Error(`${label} JSON could not be read; no mutation retry is permitted.`); }
}

export async function batch3Request(http: APIRequestContext, url: string,
  options: Parameters<APIRequestContext["fetch"]>[1] = {}): Promise<APIResponse> {
  try { return await http.fetch(url, { ...options, maxRetries: 0, maxRedirects: 0 }); }
  catch { throw new Error("Batch 3 API transport failed; no retry; private headers and request details omitted."); }
}

export function retainedClientHash(client: ClientRecord): string {
  const retained = Object.fromEntries(Object.entries(client)
    .filter(([key]) => !contactKeys.has(key) && key !== "updated_at"));
  retained.matters = [...client.matters].sort((a, b) => a.matter_id.localeCompare(b.matter_id));
  return createHash("sha256").update(JSON.stringify(retained)).digest("hex");
}

export function requireLocalBatch3(runtime: Pick<Batch3ClientRuntime, "local" | "web" | "api">): void {
  if (!runtime.local || ![runtime.web, runtime.api].every(loopback)) {
    throw new Error("Local-only synthetic KYC and negative fixtures cannot run against production.");
  }
}

async function newApi(api: URL): Promise<APIRequestContext> {
  return request.newContext({ storageState: { cookies: [], origins: [] },
    extraHTTPHeaders: localTransportHeaders(api.origin), timeout: 30_000 });
}

export async function batch3Read<T>(runtime: Batch3ClientRuntime, path: string): Promise<T> {
  if (!path.startsWith("/api/") || path.includes("?") || path.includes("#")) throw new Error("Use an exact batch 3 API path.");
  const response = await batch3Request(runtime.http, `${runtime.api.origin}${path}`, {
    method: "GET", headers: runtime.headers,
  });
  return batch3Json<T>(response, "Batch 3 authorized read");
}

export async function batch3LocalWrite<T>(runtime: Batch3ClientRuntime, path: string, data: object,
  method: "POST" | "PATCH" | "DELETE" = "POST"): Promise<T> {
  requireLocalBatch3(runtime);
  const allowed = path === "/api/clients/" || path === "/api/matters/" || path === "/api/companies/current/users"
    || /^\/api\/matters\/[a-f0-9-]{36}\/(?:clients|client-verification\/[a-f0-9-]{36})$/.test(path)
    || (method === "DELETE" && path === `/api/clients/${runtime.fixture?.client.id}`);
  if (!allowed) throw new Error("Operation is outside the local batch 3 fixture boundary.");
  await runtime.release();
  return batch3Json<T>(await batch3Request(runtime.http, `${runtime.api.origin}${path}`, {
    method, headers: runtime.headers, data,
  }), "Local synthetic QA admission");
}

async function assertActor(runtime: Batch3ClientRuntime): Promise<void> {
  const current = await batch3Read<Actor>(runtime, "/api/auth/me");
  expect(current.company.id === runtime.actor.company.id && current.company.slug === runtime.credentials.company_slug,
    "Authenticated batch 3 tenant must still be the admitted QA tenant").toBe(true);
  expect(current.user.email === runtime.credentials.email, "Authenticated QA actor must match").toBe(true);
  expect(current.capabilities.includes("clients:edit"), "Current actor requires clients:edit").toBe(true);
}

async function guardClientPatch(runtime: Batch3ClientRuntime, path: string, patch: unknown): Promise<void> {
  const fixture = runtime.fixture;
  if (!fixture || path !== `/api/clients/${fixture.client.id}` || !patch || typeof patch !== "object" || Array.isArray(patch)) {
    throw new Error("Only the admitted batch 3 QA client's contact patch is allowed.");
  }
  const entries = Object.entries(patch);
  if (!entries.length || entries.length > 9 || entries.some(([key, value]) => !contactKeys.has(key)
    || !(value === null || (typeof value === "string" && value.length <= 255)))) {
    throw new Error("Batch 3 contact mutation contains a forbidden field or value.");
  }
  await runtime.release();
  await assertActor(runtime);
  const current = await batch3Read<ClientRecord>(runtime, path);
  expect(current.is_active && current.company_id === runtime.actor.company.id
    && retainedClientHash(current) === fixture.retainedHash,
  "Current QA identity, KYC and matter links must remain exactly admitted before mutation").toBe(true);
  runtime.patches.push(patch as ContactPatch);
}

export async function batch3WireGuard(context: BrowserContext, runtime: Batch3ClientRuntime): Promise<void> {
  await context.route("**/*", async route => {
    const pending = route.request();
    const url = new URL(pending.url());
    if (![runtime.web.origin, runtime.api.origin].includes(url.origin)) {
      runtime.refused.push("external_origin");
      return route.abort("blockedbyclient");
    }
    if (pending.method() === "OPTIONS") return route.continue();
    expect(pending.headers()["x-caseops-automated-test"], "Browser isolation marker is authoritative").toBe("no-paid-providers");
    if (!url.pathname.startsWith("/api/")) return route.continue();
    if (/^\/api\/(?:case-tracking|research|recommendations|assistant|authorities\/search)(?:\/|$)/.test(url.pathname)) {
      runtime.refused.push("provider_surface");
      return route.abort("blockedbyclient");
    }
    if (["GET", "HEAD"].includes(pending.method())) return route.continue();
    if (pending.method() === "POST" && /^\/api\/auth\/(?:login|refresh|logout)$/.test(url.pathname)) return route.continue();
    if (pending.method() === "PATCH") {
      await guardClientPatch(runtime, url.pathname, pending.postDataJSON());
      return route.continue();
    }
    runtime.refused.push("unapproved_mutation");
    return route.abort("blockedbyclient");
  });
}

export async function batch3SignIn(page: Page, runtime: Batch3ClientRuntime, credentials = runtime.credentials): Promise<void> {
  await page.goto(`${runtime.web.origin}/sign-in`);
  await page.locator("#company-slug").fill(credentials.company_slug);
  await page.locator("#email").fill(credentials.email);
  await page.locator("#password").fill(credentials.password);
  const signed = page.waitForResponse(response => new URL(response.url()).origin === runtime.api.origin
    && new URL(response.url()).pathname === "/api/auth/login" && response.request().method() === "POST");
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const receipt = await signed;
  expect(receipt.status(), "Normal browser login must succeed").toBe(200);
  expect(await receipt.finished()).toBeNull();
  await page.waitForURL(/\/app(?:[/?]|$)/);
  const actor = await batch3Json<Actor>(await batch3Request(page.request, `${runtime.api.origin}/api/auth/me`, {
    method: "GET", headers: localTransportHeaders(runtime.api.origin),
  }), "Browser's own authenticated context");
  expect(actor.company.id === runtime.actor.company.id && actor.company.slug === credentials.company_slug
    && actor.user.email === credentials.email, "The browser must authenticate as its intended QA actor, not an API helper's cookie").toBe(true);
}

export async function prepareBatch3Client(page: Page, baseURL: string | undefined, info: TestInfo,
  mobile = false, localOnly = false): Promise<Batch3ClientRuntime> {
  if (!baseURL) throw new Error("Use the configured app, Docker or exact-release QA origin.");
  expect(info.config.workers, "Batch 3 mutations require one worker").toBe(1);
  expect(info.config.fullyParallel).toBe(false);
  expect(info.project.retries, "No uncertain mutation replay").toBe(0);
  const web = new URL(baseURL);
  const api = new URL(loopback(web) ? apiBaseUrl : required("PROD_API_BASE_URL"));
  const local = loopback(web) && loopback(api);
  if ([web, api].some(url => !["http:", "https:"].includes(url.protocol) || url.username || url.password
    || url.search || url.hash || url.pathname !== "/") || loopback(web) !== loopback(api)
    || (local && web.hostname !== api.hostname)) throw new Error("Unsafe or mixed batch 3 origins.");
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote batch 3 acceptance requires the canonical production origins.");
  }
  if (localOnly) requireLocalBatch3({ local, web, api });
  if (mobile) {
    if (local) expect(info.project.name, "Mobile cases must be admitted to the real app-mobile project").toBe("app-mobile");
    expect(info.project.use.isMobile).toBe(true);
    expect(info.project.use.hasTouch).toBe(true);
    expect(page.viewportSize()?.width).toBe(393);
    expect(await page.evaluate(() => navigator.maxTouchPoints)).toBeGreaterThan(0);
  } else {
    expect(info.project.use.isMobile ?? false).toBe(false);
    await page.setViewportSize({ width: 1280, height: 1000 });
  }
  const sha = local ? e2eEnv.CASEOPS_RELEASE_SHA : required("CASEOPS_EXPECTED_RELEASE_SHA");
  const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  const run = randomUUID();
  const credentials: Credentials = local
    ? { company_slug: `batch3-${run}`, email: `batch3-${run}@example.com`, password: `Synthetic!${randomUUID()}aA9` }
    : { company_slug: required("CASEOPS_RAM_PROD_SLUG"), email: required("CASEOPS_RAM_PROD_EMAIL"),
        password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (!local) {
    if (credentials.company_slug !== "test-legal") throw new Error("Batch 3 production writes are test-legal only, never GBA or a real client tenant.");
    if (!uuid.test(required("CASEOPS_RAM_BATCH3_QA_CLIENT_ID")) || !uuid.test(required("CASEOPS_RAM_BATCH3_QA_MATTER_ID"))
      || !/^[a-f0-9]{64}$/.test(required("CASEOPS_RAM_BATCH3_QA_RETAINED_SHA256"))) {
      throw new Error("An explicitly approved retained synthetic QA fixture and its exact fingerprint are required.");
    }
  }
  await release();
  const http = await newApi(api);
  try {
    if (local) await batch3Json(await batch3Request(http, `${api.origin}/api/bootstrap/company`, {
      method: "POST", headers: localTransportHeaders(api.origin), data: { company_name: `Synthetic batch 3 QA ${run}`,
        company_slug: credentials.company_slug, company_type: "law_firm", owner_full_name: "Synthetic QA owner",
        owner_email: credentials.email, owner_password: credentials.password }, maxRetries: 0, maxRedirects: 0,
    }), "Loopback-only QA bootstrap");
    const actor = await batch3Json<Actor>(await batch3Request(http, `${api.origin}/api/auth/login`, {
      method: "POST", headers: localTransportHeaders(api.origin), data: credentials,
    }), "QA API login");
    expect(uuid.test(actor.company.id) && uuid.test(actor.membership.id) && Boolean(actor.access_token)
      && actor.company.slug === credentials.company_slug, "API login must return the exact admitted QA actor").toBe(true);
    const runtime: Batch3ClientRuntime = { web, api, local, run, actor, credentials, http, release,
      headers: { ...localTransportHeaders(api.origin), Authorization: `Bearer ${actor.access_token}` },
      contexts: [http], patches: [], refused: [] };
    await assertActor(runtime);
    await page.setExtraHTTPHeaders(localTransportHeaders(web.origin));
    await batch3WireGuard(page.context(), runtime);
    await batch3SignIn(page, runtime);
    await release();
    return runtime;
  } catch (error) { await http.dispose(); throw error; }
}

export async function batch3KycAudit(runtime: Batch3ClientRuntime, matterId: string): Promise<Audit> {
  const response = await batch3Request(runtime.http, `${runtime.api.origin}/api/matters/${matterId}/audit-events`, {
    method: "GET", headers: runtime.headers, params: { action: "client.verification_updated", limit: 200 },
  });
  const audit = await batch3Json<Audit>(response, "Retained QA verification audit");
  expect(audit.total, "Audit fixture must fit one complete bounded page").toBeLessThanOrEqual(200);
  expect(audit.events.length).toBe(audit.total);
  return audit;
}

export async function batch3ClientFixture(runtime: Batch3ClientRuntime): Promise<Batch3ClientFixture> {
  let clientId: string;
  let matterId: string;
  if (runtime.local) {
    const created = await batch3LocalWrite<ClientRecord>(runtime, "/api/clients/", {
      name: `Synthetic QA batch3 contact ${runtime.run}`, client_type: "corporate", internal_notes: batch3QaMarker,
      primary_contact_name: "Synthetic QA contact", primary_contact_email: `client-${runtime.run}@example.com`,
      primary_contact_phone: "+1 202 555 0100", address_line_1: "Synthetic QA address line 1",
      address_line_2: "Synthetic QA address line 2", city: "Synthetic QA city", state: "Synthetic QA state",
      postal_code: "QA-000", country: "Synthetic QA country", pan: null, gstin: null,
    });
    expect(uuid.test(created.id) && created.company_id === runtime.actor.company.id
      && created.name === `Synthetic QA batch3 contact ${runtime.run}`,
    "Client creation must acknowledge the exact uniquely named QA client and server-owned identity").toBe(true);
    clientId = created.id;
    const matter = await batch3LocalWrite<{ id: string; matter_code: string; title: string }>(runtime, "/api/matters/", {
      matter_code: `B3CONTACT-${runtime.run}`.toUpperCase(), title: `Synthetic QA batch3 client matter ${runtime.run}`,
      status: "intake", practice_area: "Civil", forum_level: "advisory", client_name: null,
    });
    expect(uuid.test(matter.id) && matter.matter_code === `B3CONTACT-${runtime.run}`.toUpperCase()
      && matter.title === `Synthetic QA batch3 client matter ${runtime.run}`).toBe(true);
    matterId = matter.id;
    await batch3LocalWrite(runtime, `/api/matters/${matterId}/clients`, { client_id: clientId, role: "QA fixture", is_primary: true });
    const verificationPath = `/api/matters/${matterId}/client-verification/${clientId}`;
    // Loopback synthetic state-machine acceptance only, not certification of a legal identity.
    await batch3LocalWrite(runtime, verificationPath, { status: "submitted", documents: [{
      name: "Synthetic QA stub only - no legal identity verified", document_type: "synthetic_qa_only",
      status: "submitted", note: "Offline UI regression fixture, not identity evidence",
    }] }, "PATCH");
    await batch3LocalWrite(runtime, verificationPath, { status: "verified" }, "PATCH");
  } else {
    clientId = required("CASEOPS_RAM_BATCH3_QA_CLIENT_ID");
    matterId = required("CASEOPS_RAM_BATCH3_QA_MATTER_ID");
  }
  const client = await batch3Read<ClientRecord>(runtime, `/api/clients/${clientId}`);
  expect(client.id === clientId && client.company_id === runtime.actor.company.id && client.is_active
    && client.name.startsWith("Synthetic QA batch3 contact ") && client.internal_notes === batch3QaMarker,
  "Only an explicitly marked synthetic QA client may be edited").toBe(true);
  expect(client.kyc_status).toBe("verified");
  expect(Boolean(client.kyc_verified_at && client.kyc_submitted_at && client.kyc_verified_by_membership_id)).toBe(true);
  expect(client.kyc_documents.length).toBeGreaterThan(0);
  expect(client.kyc_documents.length).toBeLessThanOrEqual(20);
  expect(client.kyc_documents.every(document => document.document_type === "synthetic_qa_only"),
    "QA evidence must be explicitly synthetic, never a newly invented real identity").toBe(true);
  expect(client.matters.length).toBeGreaterThan(0);
  expect(client.matters.length).toBeLessThanOrEqual(3);
  expect(client.matters.some(link => link.matter_id === matterId)).toBe(true);
  const audit = await batch3KycAudit(runtime, matterId);
  expect(audit.events.some(event => event.target_id === clientId && event.metadata?.status === "verified"),
    "Retained verified status requires its existing matter-scoped audit").toBe(true);
  const retainedHash = retainedClientHash(client);
  if (!runtime.local) expect(retainedHash === required("CASEOPS_RAM_BATCH3_QA_RETAINED_SHA256"),
    "Retained QA identity, verification and association fingerprint must match approved evidence").toBe(true);
  const fixture = { client, matterId, retainedHash, audit };
  runtime.fixture = fixture;
  return fixture;
}

export async function batch3ControlBounds(control: Locator, page: Page, minimumWidth = 24): Promise<void> {
  await control.scrollIntoViewIfNeeded();
  await expect(control).toBeVisible();
  const box = await control.boundingBox();
  const viewport = page.viewportSize();
  expect(Boolean(box && viewport && box.width >= minimumWidth && box.height >= 24 && box.x >= -0.5 && box.y >= -0.5
    && box.x + box.width <= viewport.width + 0.5 && box.y + box.height <= viewport.height + 0.5),
  "Control must have useful dimensions and be entirely visible, not merely exist in the DOM").toBe(true);
}

export async function closeBatch3Client(runtime: Batch3ClientRuntime): Promise<void> {
  const results = await Promise.allSettled(runtime.contexts.map(context => context.dispose()));
  expect(results.every(result => result.status === "fulfilled"), "Dispose every isolated QA API context").toBe(true);
  expect(runtime.refused, "No external, provider or unapproved mutation request may occur").toEqual([]);
}
