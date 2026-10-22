/** J12/M11, US-034/035/037, FT-044/045/046/049, MOD-TS-009/013. Client cases only; draft cases are parent-owned. */
import { randomUUID } from "node:crypto";
import type { Browser, Locator, Page, Request, Response, TestInfo } from "@playwright/test";
import type { ClientRecord } from "../../apps/web/lib/api/endpoints";
import { expect, request, test } from "./support/prod-diagnostic-test";
import { localTransportHeaders } from "./support/cost-controls";
import {
  batch3ClientFixture, batch3ContactFields, batch3ControlBounds, batch3Json, batch3KycAudit,
  batch3LocalWrite, batch3Read, batch3Request, batch3SignIn, batch3WireGuard, closeBatch3Client,
  prepareBatch3Client, retainedClientHash, type Batch3ClientRuntime, type ContactPatch,
} from "./support/ram-batch3";

test.use({ storageState: { cookies: [], origins: [] }, serviceWorkers: "block",
  extraHTTPHeaders: async ({ baseURL }, use) => {
    if (!baseURL) throw new Error("Batch 3 requires the configured browser baseURL.");
    await use(localTransportHeaders(baseURL));
  }, trace: "off", screenshot: "off", video: "off" });
// One worker is checked before admission. Independent cases still execute after a sibling failure.
test.describe.configure({ mode: "default", retries: 0 });

const editor = (page: Page) => page.getByRole("dialog", { name: "Edit contact details", exact: true });
const editButton = (page: Page) => page.getByRole("button", { name: "Edit contact details", exact: true });
const contact = (page: Page) => page.getByRole("heading", { name: "Contact", exact: true }).locator("..").locator("..").locator("dl");
const contactValue = (page: Page, label: string) => contact(page).getByText(label, { exact: true }).locator("..").locator("dd");

async function activate(page: Page, control: Locator): Promise<void> {
  if (test.info().project.use.hasTouch === true) await control.tap();
  else await control.click();
}

async function noOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1),
    "The page must not overflow the viewport after navigation consumes its space").toBe(true);
}

async function enterClient(page: Page, runtime: Batch3ClientRuntime, client: ClientRecord): Promise<void> {
  await page.goto(`${runtime.web.origin}/app/clients/${client.id}`);
  await expect(page).toHaveURL(new RegExp(`/app/clients/${client.id}/?$`));
  await expect(page.getByRole("heading", { name: client.name, exact: true })).toBeVisible();
  await expect(contact(page)).toBeVisible();
  await batch3ControlBounds(editButton(page), page, 120);
  await noOverflow(page);
}

async function assertPrefill(page: Page, client: ClientRecord): Promise<Locator> {
  await activate(page, editButton(page));
  const dialog = editor(page);
  await expect(dialog).toBeVisible();
  await expect(dialog.locator("input")).toHaveCount(9);
  expect(await dialog.locator("input").evaluateAll(inputs => inputs.map(input => input.getAttribute("name")))).toEqual(
    batch3ContactFields.map(([key]) => key),
  );
  for (const [key, label] of batch3ContactFields) {
    await expect(dialog.getByLabel(label, { exact: true })).toHaveValue(client[key] ?? "");
  }
  await expect(dialog.getByRole("button", { name: "Save changes", exact: true })).toBeDisabled();
  return dialog;
}

async function editorGeometry(page: Page, info: TestInfo, local: boolean): Promise<void> {
  const dialog = editor(page);
  await batch3ControlBounds(dialog.getByRole("button", { name: "Close", exact: true }), page);
  for (const [, label] of batch3ContactFields) await batch3ControlBounds(dialog.getByLabel(label, { exact: true }), page, 180);
  const inputs = await dialog.locator("input").evaluateAll(elements => elements.map(element => {
    const box = element.getBoundingClientRect();
    return { x: box.x, y: box.y, width: box.width, height: box.height };
  }));
  for (let a = 0; a < inputs.length; a++) for (let b = a + 1; b < inputs.length; b++) {
    const left = inputs[a], right = inputs[b];
    expect(Math.min(left.x + left.width, right.x + right.width) - Math.max(left.x, right.x) > 0.5
      && Math.min(left.y + left.height, right.y + right.height) - Math.max(left.y, right.y) > 0.5,
    "Editable contact inputs must not overlap").toBe(false);
  }
  for (const name of ["Cancel", "Save changes"]) {
    await batch3ControlBounds(dialog.getByRole("button", { name, exact: true }), page, 85);
  }
  const buttons = await dialog.locator("form button").evaluateAll(elements => elements.map(element => {
    const box = element.getBoundingClientRect(); return { top: box.top, bottom: box.bottom, left: box.left, right: box.right };
  }));
  expect(buttons).toHaveLength(2);
  expect(buttons[0].right <= buttons[1].left || buttons[1].right <= buttons[0].left
    || buttons[0].bottom <= buttons[1].top || buttons[1].bottom <= buttons[0].top).toBe(true);
  await noOverflow(page);
  if (local) await info.attach(`synthetic-client-editor-actions-${page.viewportSize()?.width}`, {
    body: await page.screenshot(), contentType: "image/png",
  });
}

function isClientPatch(runtime: Batch3ClientRuntime, pending: Request): boolean {
  const url = new URL(pending.url());
  return url.origin === runtime.api.origin && url.pathname === `/api/clients/${runtime.fixture!.client.id}`
    && pending.method() === "PATCH";
}

async function acknowledgeSave(page: Page, runtime: Batch3ClientRuntime, expected: ContactPatch): Promise<ClientRecord> {
  const before = runtime.patches.length;
  const acknowledged = page.waitForResponse(response => isClientPatch(runtime, response.request()));
  await activate(page, editor(page).getByRole("button", { name: "Save changes", exact: true }));
  const response = await acknowledged;
  expect(response.status(), "The single contact mutation must succeed without replay").toBe(200);
  expect(await response.finished()).toBeNull();
  const body = await response.json() as ClientRecord;
  expect(runtime.patches.length).toBe(before + 1);
  expect(runtime.patches[before]).toEqual(expected);
  await expect(editor(page)).toHaveCount(0);
  await expect(page.getByText("Contact details updated.", { exact: true })).toBeVisible();
  return body;
}

async function assertSaved(page: Page, runtime: Batch3ClientRuntime, expected: ContactPatch): Promise<ClientRecord> {
  const fixture = runtime.fixture!;
  const current = await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`);
  expect(retainedClientHash(current) === fixture.retainedHash,
    "Identity, full KYC evidence, reviewer, timestamps, notes, lifecycle and matter links must remain unchanged").toBe(true);
  for (const [key, label] of batch3ContactFields) {
    if (Object.hasOwn(expected, key)) {
      expect(current[key] === expected[key], `Saved ${key} must equal the exact submitted contact value`).toBe(true);
      await expect(contactValue(page, label)).toHaveText(expected[key] ?? "\u2014");
    }
  }
  const list = await batch3Read<{ clients: ClientRecord[] }>(runtime, "/api/clients/");
  const rows = list.clients.filter(row => row.id === current.id);
  expect(rows).toHaveLength(1);
  expect(JSON.stringify(rows[0]) === JSON.stringify(current), "List and profile must expose the same persisted record").toBe(true);
  expect(JSON.stringify(await batch3KycAudit(runtime, fixture.matterId)) === JSON.stringify(fixture.audit),
    "Every retained verification audit event must remain byte-equivalent after contact edits").toBe(true);
  const panel = page.getByRole("heading", { name: "KYC verification", exact: true }).locator("..").locator("..");
  await expect(panel.getByText("verified", { exact: true })).toBeVisible();
  for (const document of current.kyc_documents) await expect(panel).toContainText(document.name);
  for (const link of current.matters) {
    const linkedMatter = page.locator(`a[href="/app/matters/${link.matter_id}"]`);
    await expect(linkedMatter).toHaveCount(1);
    await expect(linkedMatter).toContainText(link.matter_code);
  }
  return current;
}

async function persistenceJourney(page: Page, baseURL: string | undefined, info: TestInfo, mobile: boolean): Promise<void> {
  const runtime = await prepareBatch3Client(page, baseURL, info, mobile);
  try {
    const fixture = await batch3ClientFixture(runtime);
    info.annotations.push({ type: "KYC boundary", description: runtime.local
      ? "Loopback synthetic QA state-machine fixture only; no real legal identity verified."
      : "Approved retained synthetic QA evidence only; no production KYC submission or review performed." });
    await enterClient(page, runtime, fixture.client);
    let dialog = await assertPrefill(page, fixture.client);
    if (runtime.local) await info.attach(`synthetic-client-editor-top-${page.viewportSize()?.width}`, {
      body: await page.screenshot(), contentType: "image/png",
    });
    await editorGeometry(page, info, runtime.local);
    await dialog.getByLabel("City", { exact: true }).fill("Canceled synthetic QA city");
    await activate(page, dialog.getByRole("button", { name: "Cancel", exact: true }));
    await expect(editor(page)).toHaveCount(0);
    await expect(editButton(page)).toBeFocused();
    expect(runtime.patches).toEqual([]);
    dialog = await assertPrefill(page, fixture.client);
    await dialog.getByLabel("Email", { exact: true }).fill("invalid-qa-email");
    await activate(page, dialog.getByRole("button", { name: "Save changes", exact: true }));
    expect(await dialog.getByLabel("Email", { exact: true }).evaluate(input => (input as HTMLInputElement).validity.typeMismatch)).toBe(true);
    expect(runtime.patches).toEqual([]);
    const changed: ContactPatch = {
      primary_contact_name: `Synthetic QA contact ${runtime.run}`,
      primary_contact_email: `updated-${runtime.run}@example.com`, primary_contact_phone: "+1 202 555 0199",
      address_line_1: `Synthetic QA line 1 ${runtime.run}`, address_line_2: `Synthetic QA line 2 ${runtime.run}`,
      city: `QA city ${runtime.run}`, state: "Synthetic QA updated state", postal_code: "QA-001",
      country: "Synthetic QA updated country",
    };
    // A retained fixture may already have a constant contact value from a previous accepted run.
    const dirty = Object.fromEntries(Object.entries(changed).filter(([key, value]) => fixture.client[key as keyof ClientRecord] !== value));
    for (const [key, label] of batch3ContactFields) await dialog.getByLabel(label, { exact: true }).fill(changed[key]!);
    await acknowledgeSave(page, runtime, dirty);
    await assertSaved(page, runtime, changed);
    await page.reload();
    await expect(page.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    const reloaded = await assertSaved(page, runtime, changed); // Fresh API read, never an old CDP response after reload.
    await page.goto(`${runtime.web.origin}/app/clients`);
    const card = page.getByTestId(`client-card-${fixture.client.id}`);
    await expect(card).toHaveCount(1);
    await expect(card).toContainText(changed.city!);
    await batch3ControlBounds(card, page, 160);
    await activate(page, card);
    await expect(page).toHaveURL(new RegExp(`/app/clients/${fixture.client.id}/?$`));
    await expect(page.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    await assertPrefill(page, reloaded);
    const clears: ContactPatch = { primary_contact_email: null, primary_contact_phone: null, address_line_2: null, country: null };
    for (const [key, label] of batch3ContactFields) if (Object.hasOwn(clears, key)) await editor(page).getByLabel(label, { exact: true }).fill("");
    await acknowledgeSave(page, runtime, clears);
    await page.reload();
    await expect(page.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    await assertSaved(page, runtime, { ...changed, ...clears });
    await noOverflow(page);
    await runtime.release();
  } finally { await closeBatch3Client(runtime); }
}

test("B3-CLIENT-01/02/03 contact edits preserve retained verified KYC and matter links", async ({ page, baseURL }, info) => {
  await persistenceJourney(page, baseURL, info, false);
});

test("[mobile] B3-CLIENT-06 verified-client contact editing persists at 393px", async ({ page, baseURL }, info) => {
  await persistenceJourney(page, baseURL, info, true);
});

test("[local-only] B3-CLIENT-04 viewer, foreign tenant and archived-client boundaries", async ({ page, baseURL, browser }, info) => {
  const runtime = await prepareBatch3Client(page, baseURL, info, false, true);
  let viewerContext: Awaited<ReturnType<Browser["newContext"]>> | undefined;
  try {
    const fixture = await batch3ClientFixture(runtime);
    await enterClient(page, runtime, fixture.client);
    const before = JSON.stringify(await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`));
    const viewer = { company_slug: runtime.credentials.company_slug, email: `viewer-${runtime.run}@example.com`, password: `Synthetic!${randomUUID()}aA9` };
    await batch3LocalWrite(runtime, "/api/companies/current/users", { full_name: "Synthetic QA viewer", email: viewer.email, password: viewer.password, role: "viewer" });
    viewerContext = await browser.newContext({ storageState: { cookies: [], origins: [] }, serviceWorkers: "block",
      extraHTTPHeaders: localTransportHeaders(runtime.web.origin), baseURL: runtime.web.origin });
    await batch3WireGuard(viewerContext, runtime);
    const viewerPage = await viewerContext.newPage();
    await batch3SignIn(viewerPage, runtime, viewer);
    const viewerMe = await batch3Json<{ company: { id: string }; membership: { role: string }; capabilities: string[] }>(
      await batch3Request(viewerContext.request, `${runtime.api.origin}/api/auth/me`, { method: "GET" }), "Independent viewer identity");
    expect(viewerMe.company.id).toBe(runtime.actor.company.id);
    expect(viewerMe.membership.role).toBe("viewer");
    expect(viewerMe.capabilities).not.toContain("clients:edit");
    await viewerPage.goto(`${runtime.web.origin}/app/clients/${fixture.client.id}`);
    await expect(viewerPage.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    await expect(editButton(viewerPage)).toHaveCount(0);
    const csrf = (await viewerContext.cookies(runtime.api.origin)).find(cookie => cookie.name === "caseops_csrf")?.value;
    expect(Boolean(csrf)).toBe(true);
    await runtime.release();
    const denied = await batch3Request(viewerContext.request, `${runtime.api.origin}/api/clients/${fixture.client.id}`, {
      method: "PATCH",
      headers: { ...localTransportHeaders(runtime.api.origin), "X-CSRF-Token": csrf! }, data: { city: "Forbidden QA change" },
      maxRetries: 0, maxRedirects: 0,
    });
    expect(denied.status()).toBe(403);

    const foreign = await request.newContext({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: localTransportHeaders(runtime.api.origin) });
    runtime.contexts.push(foreign);
    const foreignRun = randomUUID();
    await runtime.release();
    const foreignSession = await batch3Json<{ access_token: string; company: { id: string } }>(
      await batch3Request(foreign, `${runtime.api.origin}/api/bootstrap/company`, { method: "POST", data: {
        company_name: `Synthetic foreign QA ${foreignRun}`, company_slug: `batch3-foreign-${foreignRun}`,
        company_type: "law_firm", owner_full_name: "Synthetic foreign owner", owner_email: `foreign-${foreignRun}@example.com`,
        owner_password: `Synthetic!${randomUUID()}aA9`,
      }, maxRetries: 0, maxRedirects: 0 }), "Independent loopback foreign tenant");
    expect(foreignSession.company.id !== runtime.actor.company.id).toBe(true);
    const foreignHeaders = { ...localTransportHeaders(runtime.api.origin), Authorization: `Bearer ${foreignSession.access_token}` };
    const foreignMe = await batch3Json<{ company: { id: string } }>(await batch3Request(foreign, `${runtime.api.origin}/api/auth/me`, {
      method: "GET", headers: foreignHeaders,
    }), "Independent foreign actor");
    expect(foreignMe.company.id).toBe(foreignSession.company.id);
    expect((await batch3Request(foreign, `${runtime.api.origin}/api/clients/${fixture.client.id}`, {
      method: "GET", headers: foreignHeaders,
    })).status()).toBe(404);
    await runtime.release();
    expect((await batch3Request(foreign, `${runtime.api.origin}/api/clients/${fixture.client.id}`, {
      method: "PATCH", headers: foreignHeaders, data: { city: "Forbidden foreign change" },
    })).status()).toBe(404);
    const anonymous = await request.newContext({ storageState: { cookies: [], origins: [] },
      extraHTTPHeaders: localTransportHeaders(runtime.api.origin) });
    runtime.contexts.push(anonymous);
    await runtime.release();
    expect((await batch3Request(anonymous, `${runtime.api.origin}/api/clients/${fixture.client.id}`, {
      method: "PATCH", headers: { ...localTransportHeaders(runtime.api.origin),
        Cookie: "caseops_csrf=batch3-synthetic-csrf", "X-CSRF-Token": "batch3-synthetic-csrf" },
      data: { city: "Forbidden anonymous change" },
    })).status()).toBe(401);
    await runtime.release();
    expect((await batch3Request(runtime.http, `${runtime.api.origin}/api/clients/${fixture.client.id}`, {
      method: "PATCH", headers: runtime.headers, data: { primary_contact_email: "invalid-qa-email" },
    })).status()).toBe(422);
    expect(JSON.stringify(await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`)) === before).toBe(true);
    await batch3LocalWrite(runtime, `/api/clients/${fixture.client.id}`, {}, "DELETE");
    await page.reload();
    await expect(page.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    await expect(editButton(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Restore", exact: true })).toBeVisible();
    expect((await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`)).is_active).toBe(false);
    expect(runtime.patches).toEqual([]);
  } finally {
    try { await viewerContext?.close(); } finally { await closeBatch3Client(runtime); }
  }
});

test("[local-only] B3-CLIENT-05 failed saves retain input; in-flight saves cannot be canceled or duplicated", async ({ page, baseURL }, info) => {
  const runtime = await prepareBatch3Client(page, baseURL, info, false, true);
  let releaseTransport: (() => void) | undefined;
  try {
    const fixture = await batch3ClientFixture(runtime);
    await enterClient(page, runtime, fixture.client);
    const original = JSON.stringify(await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`));
    const dialog = await assertPrefill(page, fixture.client);
    let status: number | "network" | "pending" = 403;
    let intercepted = 0;
    let entered!: () => void;
    const pendingEntered = new Promise<void>(resolve => { entered = resolve; });
    const pendingRelease = new Promise<void>(resolve => { releaseTransport = resolve; });
    await page.route(`${runtime.api.origin}/api/clients/${fixture.client.id}`, async route => {
      if (route.request().method() !== "PATCH") return route.fallback();
      intercepted++;
      expect(route.request().headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
      if (status === "pending") { entered(); await pendingRelease; return route.fallback(); }
      if (status === "network") return route.abort("connectionfailed");
      // Deliberate loopback transport fault, not evidence of a real server authorization failure.
      return route.fulfill({ status, headers: { "content-type": "application/problem+json",
        "access-control-allow-origin": runtime.web.origin, "access-control-allow-credentials": "true" },
        body: JSON.stringify({ type: "https://caseops.ai/errors/synthetic-qa-contact-refusal", title: "Synthetic QA refusal", status,
          detail: `Synthetic QA contact refusal ${status}. Reload the client before saving.` }) });
    });
    await dialog.getByLabel("City", { exact: true }).fill("Unsaved synthetic QA city");
    for (const fault of [403, 409, 422, 500, "network"] as const) {
      status = fault;
      const count = intercepted;
      const predicate = (pending: Request) => isClientPatch(runtime, pending);
      const finished = fault === "network" ? page.waitForEvent("requestfailed", { predicate })
        : page.waitForEvent("requestfinished", { predicate });
      await dialog.getByRole("button", { name: "Save changes", exact: true }).click();
      await finished;
      await expect(dialog.getByRole("alert")).toHaveText(fault === "network"
        ? "Could not reach the workspace API. Check your connection and try again."
        : `Synthetic QA contact refusal ${fault}. Reload the client before saving.`);
      await expect(dialog.getByLabel("City", { exact: true })).toHaveValue("Unsaved synthetic QA city");
      await expect(dialog.getByRole("button", { name: "Save changes", exact: true })).toBeEnabled();
      expect(intercepted).toBe(count + 1);
      expect(JSON.stringify(await batch3Read<ClientRecord>(runtime, `/api/clients/${fixture.client.id}`)) === original).toBe(true);
    }
    status = "pending";
    const saved = page.waitForResponse(response => isClientPatch(runtime, response.request()));
    await dialog.getByRole("button", { name: "Save changes", exact: true }).click();
    await pendingEntered;
    await expect(dialog.getByLabel("City", { exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeDisabled();
    await expect(dialog.getByRole("button", { name: "Saving...", exact: true })).toBeDisabled();
    await page.keyboard.press("Escape");
    await dialog.getByRole("button", { name: "Close", exact: true }).click();
    await page.mouse.click(2, 2);
    await dialog.locator("form").evaluate(form => (form as HTMLFormElement).requestSubmit());
    await expect(dialog).toBeVisible();
    expect(intercepted).toBe(6);
    releaseTransport!();
    const receipt: Response = await saved;
    expect(receipt.status()).toBe(200);
    expect(await receipt.finished()).toBeNull();
    await receipt.json();
    await expect(dialog).toHaveCount(0);
    expect(intercepted).toBe(6);
    expect(runtime.patches).toEqual([{ city: "Unsaved synthetic QA city" }]);
    await page.reload();
    await expect(page.getByRole("heading", { name: fixture.client.name, exact: true })).toBeVisible();
    await assertSaved(page, runtime, { city: "Unsaved synthetic QA city" });
  } finally { releaseTransport?.(); await closeBatch3Client(runtime); }
});
