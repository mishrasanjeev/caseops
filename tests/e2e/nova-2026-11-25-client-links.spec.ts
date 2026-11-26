/**
 * Tester workbook dated 25 Nov 2026, row 2 (Nova Legal Associates, nova-legal):
 * "No option available to link a client with a specific matter."
 *
 * Expected: an existing client can be linked to a matter from the Clients
 * module (/app/clients/<id>) and from Matter management (create, or the
 * matter overview), and the linked client's details show on the matter.
 *
 * Each journey signs in as the reporting tester through the sign-in page,
 * creates its own uniquely named client and matter through the UI, links and
 * unlinks through the UI, and retires what it created (unlink, archive the
 * client, dispose the matter) in a finally block. API calls are oracles only;
 * on a loopback stack they also bootstrap an empty local tester tenant.
 *
 * Production runs need CASEOPS_EXPECTED_RELEASE_SHA and the tester's
 * credentials in CASEOPS_NOVA_PROD_EMAIL / CASEOPS_NOVA_PROD_PASSWORD (never
 * committed). Missing setup fails; nothing here skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const DESKTOP = { width: 1365, height: 900 };
const PHONE = { width: 393, height: 851 };

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. UI journeys never use them to act as the user. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};
type LinkedClient = { client_id: string; client_name: string; is_primary: boolean; client_is_active: boolean };
type Created = { clientId?: string; matterId?: string };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

function localCredentials(): TesterCredentials {
  const slug = process.env.CASEOPS_NOVA_LOCAL_SLUG?.trim();
  const email = process.env.CASEOPS_NOVA_LOCAL_EMAIL?.trim();
  const password = process.env.CASEOPS_NOVA_LOCAL_PASSWORD?.trim();
  if (slug && email && password) return { slug, email, password };
  return { slug: `nov25-nova-${randomUUID()}`, email: `nova-${randomUUID()}@example.com`,
    password: `Synthetic!${randomUUID()}` };
}

async function runtimeFor(baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const local = loopback(web);
  const api = new URL(local ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
    : required("PROD_API_BASE_URL"));
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote acceptance requires the canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  await release();
  const credentials: TesterCredentials = local ? localCredentials() : {
    slug: process.env.CASEOPS_NOVA_PROD_SLUG?.trim() || "nova-legal",
    email: required("CASEOPS_NOVA_PROD_EMAIL"),
    password: required("CASEOPS_NOVA_PROD_PASSWORD"),
  };
  if (!local && credentials.slug !== "nova-legal") {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Nova Legal Associates", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Riya Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` }, release };
}

async function linkedClients(request: APIRequestContext, rt: Runtime, matterId: string): Promise<LinkedClient[]> {
  return (await json<{ clients: LinkedClient[] }>(await request.get(
    `${rt.api.origin}/api/matters/${matterId}/client-verification`, { headers: rt.headers }), "Linked clients oracle")).clients;
}

async function matterClientName(request: APIRequestContext, rt: Runtime, matterId: string): Promise<string | null> {
  return (await json<{ client_name: string | null }>(await request.get(`${rt.api.origin}/api/matters/${matterId}`,
    { headers: rt.headers }), "Matter oracle")).client_name;
}

const isPost = (pattern: RegExp) => (r: { url(): string; request(): { method(): string } }) =>
  r.request().method() === "POST" && pattern.test(new URL(r.url()).pathname);
const isDelete = (pattern: RegExp) => (r: { url(): string; request(): { method(): string } }) =>
  r.request().method() === "DELETE" && pattern.test(new URL(r.url()).pathname);

/** New client dialog on /app/clients. */
async function createClientThroughUi(page: Page, rt: Runtime, name: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/clients`);
  await page.getByTestId("new-client-open").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByTestId("new-client-name").fill(name);
  const created = page.waitForResponse(isPost(/^\/api\/clients\/?$/));
  await dialog.getByTestId("new-client-submit").click();
  const client = await json<{ id: string; name: string; is_active: boolean }>(await created, "Create client through the Clients page");
  expect(client.name).toBe(name);
  expect(client.is_active).toBe(true);
  await expect(dialog).toBeHidden();
  return client.id;
}

/** New matter dialog on /app/matters, optionally linking an existing client. */
async function createMatterThroughUi(
  page: Page, rt: Runtime, title: string, code: string, linkClient?: { id: string; name: string },
) {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Commercial Litigation");
  if (linkClient) {
    await dialog.getByLabel("Search clients").fill(linkClient.name);
    const picker = dialog.getByLabel("Or link an existing client");
    await expect(picker.locator(`option[value="${linkClient.id}"]`)).toHaveCount(1);
    await picker.selectOption(linkClient.id);
    await expect(dialog.getByTestId("new-matter-client-name")).toBeDisabled();
    await expect(dialog.getByTestId("new-matter-client-name")).toHaveValue(linkClient.name);
  }
  const create = dialog.getByRole("button", { name: "Create matter" });
  await expect(create).toBeEnabled();
  const created = page.waitForResponse(isPost(/^\/api\/matters\/?$/));
  await create.click();
  const response = await created;
  const body = response.request().postDataJSON() as Record<string, unknown>;
  const matter = await json<{ id: string; matter_code: string; client_name: string | null }>(response, "Create matter through the Matters page");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return { matter, body };
}

async function unlinkOnOverview(page: Page, rt: Runtime, matterId: string, clientName: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  const card = page.getByTestId("matter-clients-card");
  await card.getByRole("button", { name: `Unlink ${clientName}` }).click();
  await expect(card.getByRole("alert")).toContainText(`keeps “${clientName}” as its client name`);
  const removed = page.waitForResponse(isDelete(new RegExp(`^/api/matters/${matterId}/clients/[0-9a-f-]{36}$`)));
  await card.getByRole("button", { name: "Unlink client" }).click();
  expect((await removed).status(), "Unlink from the matter overview").toBe(204);
  await expect(card.getByTestId("matter-client-row")).toHaveCount(0);
  await expect(card).toContainText(`names “${clientName}” as typed text only`);
}

/** Retire what one journey created, each step independently, through the UI. */
async function retire(page: Page, request: APIRequestContext, rt: Runtime, created: Created) {
  const failures: string[] = [];
  if (created.matterId) {
    try {
      for (const linked of await linkedClients(request, rt, created.matterId)) {
        await unlinkOnOverview(page, rt, created.matterId, linked.client_name);
      }
      await page.goto(`${rt.web.origin}/app/matters/${created.matterId}`);
      await page.getByTestId("matter-dispose-trigger").click();
      await page.getByTestId("matter-lifecycle-reason").fill("Nov 25 client link journey retires its own test matter.");
      const disposed = page.waitForResponse((r) => r.request().method() === "PATCH"
        && new URL(r.url()).pathname === `/api/matters/${created.matterId}/lifecycle/status`);
      await page.getByTestId("matter-lifecycle-confirm").click();
      expect((await json<{ status: string }>(await disposed, "Dispose the journey matter")).status).toBe("disposed");
    } catch (error) {
      failures.push(`matter ${created.matterId}: ${(error as Error).message.split("\n")[0]}`);
    }
  }
  if (created.clientId) {
    try {
      await page.goto(`${rt.web.origin}/app/clients/${created.clientId}`);
      const archived = page.waitForResponse(isDelete(new RegExp(`^/api/clients/${created.clientId}$`)));
      await page.getByTestId("client-archive").click();
      expect((await json<{ is_active: boolean }>(await archived, "Archive the journey client")).is_active).toBe(false);
    } catch (error) {
      failures.push(`client ${created.clientId}: ${(error as Error).message.split("\n")[0]}`);
    }
  }
  if (failures.length) throw new Error(`Could not retire created records: ${failures.join("; ")}`);
}

function names() {
  const suffix = randomUUID().slice(0, 8).toUpperCase();
  return {
    client: stamp("Nov25 Link Client"),
    title: stamp("Nov25 client link matter"),
    code: `N25L-${suffix}`,
  };
}

test("row 2 links a client from the client page and from the matter overview", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(DESKTOP);
  await signIn(page, { web: rt.web }, rt.credentials);
  const n = names();
  const created: Created = {};
  try {
    created.clientId = await createClientThroughUi(page, rt, n.client);
    const { matter } = await createMatterThroughUi(page, rt, n.title, n.code);
    created.matterId = matter.id;
    expect(await linkedClients(request, rt, matter.id)).toEqual([]);

    // Clients module: link the client to the new matter.
    await page.goto(`${rt.web.origin}/app/clients/${created.clientId}`);
    const mattersCard = page.getByTestId("client-matters-card");
    await expect(mattersCard).toContainText("No matters linked yet");
    await mattersCard.getByTestId("client-link-matter-open").click();
    await mattersCard.getByLabel("Search matters").fill(n.code);
    const matterSelect = mattersCard.getByLabel("Matter to link");
    await expect(matterSelect.locator(`option[value="${matter.id}"]`)).toHaveCount(1);
    await matterSelect.selectOption(matter.id);
    await mattersCard.getByTestId("client-link-matter-primary").check();
    const linked = page.waitForResponse(isPost(new RegExp(`^/api/matters/${matter.id}/clients$`)));
    await mattersCard.getByTestId("client-link-matter-submit").click();
    const link = await json<{ client_id: string; is_primary: boolean; matter_client_name: string }>(
      await linked, "Link from the client page");
    expect(link).toMatchObject({ client_id: created.clientId, is_primary: true, matter_client_name: n.client });
    await expect(mattersCard.getByTestId("client-matter-row").filter({ hasText: n.code })).toContainText("primary");

    // The matter record shows the linked client and carries its name.
    await page.goto(`${rt.web.origin}/app/matters/${matter.id}`);
    const card = page.getByTestId("matter-clients-card");
    const row = card.getByTestId("matter-client-row").filter({ hasText: n.client });
    await expect(row).toHaveCount(1);
    await expect(row.getByRole("link", { name: n.client })).toHaveAttribute("href", `/app/clients/${created.clientId}`);
    await expect(row).toContainText("Primary");
    await expect(row).toContainText("KYC");
    expect(await matterClientName(request, rt, matter.id)).toBe(n.client);
    expect(await linkedClients(request, rt, matter.id)).toEqual([
      expect.objectContaining({ client_id: created.clientId, client_name: n.client, is_primary: true }),
    ]);

    // Unlink from the overview; the matter keeps the client name.
    await unlinkOnOverview(page, rt, matter.id, n.client);
    expect(await linkedClients(request, rt, matter.id)).toEqual([]);
    expect(await matterClientName(request, rt, matter.id)).toBe(n.client);

    // Matter management: link the same client again from the overview card.
    await card.getByTestId("matter-clients-link-open").click();
    await card.getByLabel("Search clients").fill(n.client);
    const clientSelect = card.getByLabel("Client to link");
    await expect(clientSelect.locator(`option[value="${created.clientId}"]`)).toHaveCount(1);
    await clientSelect.selectOption(created.clientId);
    await expect(card.getByTestId("matter-clients-primary")).toBeChecked();
    const relinked = page.waitForResponse(isPost(new RegExp(`^/api/matters/${matter.id}/clients$`)));
    await card.getByTestId("matter-clients-link-submit").click();
    expect((await json<{ is_primary: boolean }>(await relinked, "Link from the matter overview")).is_primary).toBe(true);
    await expect(card.getByTestId("matter-client-row").filter({ hasText: n.client })).toContainText("Primary");

    // Unlink from the client page.
    await page.goto(`${rt.web.origin}/app/clients/${created.clientId}`);
    const clientRow = mattersCard.getByTestId("client-matter-row").filter({ hasText: n.code });
    await clientRow.getByRole("button", { name: `Unlink ${n.code}` }).click();
    const removed = page.waitForResponse(isDelete(new RegExp(`^/api/matters/${matter.id}/clients/${created.clientId}$`)));
    await mattersCard.getByRole("button", { name: "Unlink matter" }).click();
    expect((await removed).status(), "Unlink from the client page").toBe(204);
    await expect(mattersCard).toContainText("No matters linked yet");
    expect(await linkedClients(request, rt, matter.id)).toEqual([]);
  } finally {
    await retire(page, request, rt, created);
  }
  await rt.release();
});

test("row 2 new matter links an existing client at creation", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(DESKTOP);
  await signIn(page, { web: rt.web }, rt.credentials);
  const n = names();
  const created: Created = {};
  try {
    created.clientId = await createClientThroughUi(page, rt, n.client);
    const { matter, body } = await createMatterThroughUi(page, rt, n.title, n.code,
      { id: created.clientId, name: n.client });
    created.matterId = matter.id;
    expect(body.client_id).toBe(created.clientId);
    expect(body).not.toHaveProperty("client_name");
    expect(matter.client_name).toBe(n.client);

    await page.goto(`${rt.web.origin}/app/matters/${matter.id}`);
    const row = page.getByTestId("matter-clients-card").getByTestId("matter-client-row").filter({ hasText: n.client });
    await expect(row).toContainText("Primary");
    await page.goto(`${rt.web.origin}/app/clients/${created.clientId}`);
    await expect(page.getByTestId("client-matter-row").filter({ hasText: n.code })).toContainText("primary");
  } finally {
    await retire(page, request, rt, created);
  }
  await rt.release();
});

test("[mobile] row 2 links a client from the matter overview on a phone", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(PHONE);
  await signIn(page, { web: rt.web }, rt.credentials);
  const n = names();
  const created: Created = {};
  try {
    created.clientId = await createClientThroughUi(page, rt, n.client);
    const { matter } = await createMatterThroughUi(page, rt, n.title, n.code);
    created.matterId = matter.id;

    await page.goto(`${rt.web.origin}/app/matters/${matter.id}`);
    const card = page.getByTestId("matter-clients-card");
    await card.getByTestId("matter-clients-link-open").click();
    await card.getByLabel("Search clients").fill(n.client);
    const clientSelect = card.getByLabel("Client to link");
    await expect(clientSelect.locator(`option[value="${created.clientId}"]`)).toHaveCount(1);
    await clientSelect.selectOption(created.clientId);
    const linked = page.waitForResponse(isPost(new RegExp(`^/api/matters/${matter.id}/clients$`)));
    await card.getByTestId("matter-clients-link-submit").click();
    expect((await json<{ is_primary: boolean }>(await linked, "Link from the matter overview on a phone")).is_primary).toBe(true);
    const row = card.getByTestId("matter-client-row").filter({ hasText: n.client });
    await expect(row).toContainText("Primary");
    await expect(row.getByRole("button", { name: `Unlink ${n.client}` })).toBeVisible();
    await row.scrollIntoViewIfNeeded();
    expect(await card.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), "Clients card fits the phone").toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "No page overflow").toBe(true);
    expect(await matterClientName(request, rt, matter.id)).toBe(n.client);

    await unlinkOnOverview(page, rt, matter.id, n.client);
    expect(await linkedClients(request, rt, matter.id)).toEqual([]);
  } finally {
    await retire(page, request, rt, created);
  }
  await rt.release();
});
