/** Real loopback admission and isolated console journey. Never run fixture controls against production. */
import { randomUUID } from "node:crypto";
import { devices, type Browser, type BrowserContext, type Page, type TestInfo } from "@playwright/test";

import { localTransportHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { capturedLeadNotifications, cleanupLocalLeads, drainLocalLeadNotifications, freshLocalAdmissionWindow, leadControls, leadDetails,
  leadRow, prepareLocalLeads, publicLeadForms, queuedLocalLeadNotifications, type Lead, type LeadPage } from "./support/platform-leads";
import { CONSOLE, assertRelease, capturedLink, cleanupLocalFixture, completeSetup, contextCsrf, controlBounds,
  enrollMfa, expectState, json, mailLedger, newApi, noOverflow, origins, safeGet, safePost, seedLocalFixture,
  type LocalFixture, type Origins } from "./support/platform-report-admin";
import { expect, test } from "./support/prod-diagnostic-test";

test.use({ storageState: { cookies: [], origins: [] }, extraHTTPHeaders: async ({ baseURL }, use) => {
  if (!baseURL) throw new Error("Lead journeys require the configured loopback baseURL.");
  await use(localTransportHeaders(baseURL));
},
  trace: "off", screenshot: "off", video: "off", serviceWorkers: "block" });
test.describe.configure({ retries: 0, mode: "default" });

async function localWireGuard(context: BrowserContext, target: Origins) {
  const refused: string[] = [];
  await context.route("**/*", route => {
    const request = route.request();
    const url = new URL(request.url());
    if (![target.web.origin, target.api.origin].includes(url.origin)) {
      refused.push("external_request"); return route.abort("blockedbyclient");
    }
    if (request.method() !== "OPTIONS") expect(request.headers()["x-caseops-automated-test"]).toBe("no-paid-providers");
    return route.continue();
  });
  return refused;
}

async function setupManager(page: Page, target: Origins, fixture: LocalFixture) {
  const before = (await mailLedger(page.request, target, fixture)).map(row => row.id);
  await page.goto(`${target.web.origin}/platform/setup`);
  const form = page.getByRole("form", { name: "Resend setup email", exact: true });
  await form.getByLabel("Email", { exact: true }).fill(fixture.manager.email);
  const resending = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/auth/invitations/resend`
    && response.request().method() === "POST");
  await form.getByRole("button", { name: "Resend setup email", exact: true }).click();
  expect((await resending).status()).toBe(200);
  const link = await capturedLink(page.request, target, fixture, fixture.manager.email, "invite", before);
  await completeSetup(page, link, `Lead-only!${randomUUID()}aA9`, fixture.manager.full_name);
  expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/leads`)).status()).toBe(403);
  await page.goto(`${target.web.origin}/platform/leads`);
  await expect(page.getByRole("main").getByRole("heading", { name: "Verification required", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "Public leads", exact: true })).toHaveCount(0);
  await page.goto(`${target.web.origin}/platform/security`);
  // This foundation helper independently decodes QR pixels and completes the real local API factor verification.
  await enrollMfa(page, target, fixture.manager.email);
  expect((await expectState(page, target, "authenticated")).admin?.role).toBe("manager");
}

async function readPage(page: Page, response: Awaited<ReturnType<Page["waitForResponse"]>>): Promise<LeadPage> {
  expect(response.status()).toBe(200);
  expect(response.headers()["cache-control"]).toContain("no-store");
  const body = await response.json() as LeadPage;
  expect(body.items.length).toBeLessThanOrEqual(25);
  expect(body.has_more).toBe(Boolean(body.next_cursor));
  await expect(page.getByRole("region", { name: "Public leads", exact: true })).toBeVisible();
  for (const row of body.items) await expect(leadRow(page, row.id)).toHaveCount(1);
  return body;
}

const leadsRead = (page: Page) => page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/leads`
  && response.request().method() === "GET");

async function journey(page: Page, browser: Browser, baseURL: string | undefined, mobile: boolean, info: TestInfo) {
  const target = origins(baseURL, true, e2eEnv.CASEOPS_RELEASE_SHA);
  if (mobile) {
    expect(info.project.name).toBe("app-mobile");
    expect(info.project.use.isMobile).toBe(true);
    expect(info.project.use.hasTouch).toBe(true);
    expect(page.viewportSize()?.width).toBe(393);
  } else await page.setViewportSize({ width: 1280, height: 1000 });
  await assertRelease(target);
  const api = await newApi(target);
  const contexts: BrowserContext[] = [];
  const errors: string[] = [];
  const blocked = [await localWireGuard(page.context(), target)];
  page.on("pageerror", () => errors.push("pageerror"));
  let fixture: LocalFixture | undefined;
  let leadFixtureAttempted = false;
  let failed = false;
  const run = randomUUID();
  const submitted: { id: string; body: Record<string, unknown> }[] = [];
  try {
    fixture = await seedLocalFixture(api, target, run);
    leadFixtureAttempted = true;
    const seeded = await prepareLocalLeads(api, target, fixture);
    await freshLocalAdmissionWindow(api, target, fixture);
    expect((await safeGet(api, `${target.api.origin}${CONSOLE}/leads`)).status()).toBe(401);
    await setupManager(page, target, fixture);
    for (const [index, entry] of publicLeadForms.entries()) {
      await test.step(`LEAD-01 real shared admission ${entry.source}`, async () => {
        await page.goto(`${target.web.origin}${entry.path}`);
        if (entry.source === "pricing_page") {
          const requestPlan = page.getByRole("button", { name: "Request plan", exact: true }).first();
          await controlBounds(requestPlan, page);
          await requestPlan.click();
        }
        const form = page.getByRole("form", { name: "Request a demo", exact: true });
        const name = `Synthetic lead ${index} ${run}`;
        const email = `lead-${index}-${run}@example.com`;
        await form.getByLabel("Full name", { exact: true }).fill(name);
        await form.getByLabel("Work email", { exact: true }).fill(email);
        await form.getByLabel("Firm / company (optional)", { exact: true }).fill("Synthetic local enquiry firm");
        await form.getByLabel("Role", { exact: true }).selectOption(entry.segment === "gc" ? "general_counsel" : entry.segment === "solo" ? "solo_advocate" : "partner");
        await expect(form.getByLabel("Practice / team", { exact: true })).toHaveValue(entry.segment);
        await form.getByLabel("What would you like to discuss? (optional)", { exact: true })
          .fill(`Local fixture ${entry.source}\n<script>must remain plain text</script>`);
        const submit = form.getByRole("button", { name: "Request a conversation", exact: true });
        await controlBounds(submit, page);
        const saving = () => page.waitForResponse(response => new URL(response.url()).pathname === "/api/demo-request"
          && response.request().method() === "POST");
        let pending = saving();
        await submit.click();
        let result = await pending;
        const originalBody = result.request().postDataJSON() as Record<string, unknown>;
        if (index === 5) {
          expect(result.status(), "The sixth admission must hit the run-isolated five-request fixture budget; native tests own the production limiter proof.").toBe(429);
          await expect(form.getByRole("alert")).toHaveText("Too many requests. Try again later.");
          expect((await capturedLeadNotifications(api, target, fixture!)).some(row => row.lead_id === originalBody.idempotency_key)).toBe(false);
          await freshLocalAdmissionWindow(api, target, fixture!);
          pending = saving();
          await form.getByRole("button", { name: "Retry the same request", exact: true }).click();
          result = await pending;
          expect(result.request().postDataJSON()).toEqual(originalBody);
        }
        const saved = await json<{ accepted: boolean; id: string; status: string }>(result, 202, "Real public form admission");
        expect(saved).toEqual({ accepted: true, id: originalBody.idempotency_key, status: "demo_requested" });
        expect(originalBody).toMatchObject({ contact_name: name, contact_email: email, source: entry.source,
          segment: entry.segment, intent: entry.intent, privacy_notice_version: "2026-10-21" });
        if (entry.source === "pricing_page") expect(originalBody.selected_plan).toEqual(expect.any(String));
        else expect(originalBody.selected_plan).toBeNull();
        await expect(form.getByRole("status")).toContainText(`Request saved. Reference: ${saved.id}.`);
        await expect(form.getByLabel("Work email", { exact: true })).toBeDisabled();
        submitted.push({ id: saved.id, body: originalBody });
        await queuedLocalLeadNotifications(api, target, fixture!, submitted.map(row => row.id));
        const pendingRows = await json<LeadPage>(await safeGet(page.request, `${target.api.origin}${CONSOLE}/leads`),
          200, "Manager read of queued public admissions");
        for (const admission of submitted) {
          const row = pendingRows.items.find(item => item.id === admission.id);
          expect(row, "Each saved admission must remain queued until the explicit worker drain.").toBeDefined();
          expect(row!.notification).toEqual({ status: "pending", attempts: 0, last_error_code: null, eligible: false });
        }
        await noOverflow(page);
      });
    }
    const queued = await queuedLocalLeadNotifications(api, target, fixture, submitted.map(row => row.id));
    await info.attach("real-local-lead-queued-outbox", { contentType: "application/json", body: JSON.stringify({
      run_id: run, outbox: queued, captured_notifications: 0, scope: "Before explicit loopback worker drain only",
    }) });
    await test.step("LEAD-02 explicit local worker drain after all seven queued admissions", async () => {
      await drainLocalLeadNotifications(api, target, fixture!);
    });
    const captured = await capturedLeadNotifications(api, target, fixture);
    expect(captured).toHaveLength(7);
    expect(captured.map(row => row.lead_id).sort()).toEqual(submitted.map(row => row.id).sort());
    await drainLocalLeadNotifications(api, target, fixture);
    expect(await capturedLeadNotifications(api, target, fixture)).toEqual(captured);
    for (const item of captured) for (const record of submitted) for (const key of ["contact_name", "contact_email", "company_name", "notes"]) {
      expect(item.body).not.toContain(String(record.body[key]));
    }
    const tenant = await newApi(target);
    const wrongRealm = await newApi(target);
    try {
      const login = await json<{ access_token: string }>(await safePost(tenant, `${target.api.origin}/api/auth/login`, {
        data: { company_slug: fixture.tenant.slug, email: fixture.tenant.email, password: fixture.tenant.password },
      }), 200, "Isolated fixture tenant login");
      expect((await safeGet(tenant, `${target.api.origin}/api/auth/me`, { Authorization: `Bearer ${login.access_token}` })).status()).toBe(200);
      expect((await safeGet(wrongRealm, `${target.api.origin}${CONSOLE}/leads`, { Authorization: `Bearer ${login.access_token}` })).status()).toBe(401);
    } finally { await tenant.dispose(); await wrongRealm.dispose(); }
    let reading = leadsRead(page);
    await page.goto(`${target.web.origin}/platform/leads`);
    let current = await readPage(page, await reading);
    await leadControls(page);
    for (const admitted of submitted) {
      const row = current.items.find(item => item.id === admitted.id);
      expect(row, "Newly admitted enquiries must be retained on the latest real page.").toBeDefined();
      expect(row).toMatchObject({ contact_name: admitted.body.contact_name, contact_email: admitted.body.contact_email,
        company_name: admitted.body.company_name, contact_mobile: null, source: admitted.body.source,
        segment: admitted.body.segment, selected_plan: admitted.body.selected_plan, role: admitted.body.role,
        intent: admitted.body.intent, notes: admitted.body.notes, privacy_notice_version: admitted.body.privacy_notice_version });
      expect(row!.notification).toEqual({ status: "accepted", attempts: 1, last_error_code: null, eligible: false });
      await leadDetails(page, row!);
    }
    const initialIds = current.items.map(row => row.id);
    reading = leadsRead(page);
    await page.getByRole("button", { name: "Reload leads", exact: true }).click();
    current = await readPage(page, await reading);
    expect(current.items.map(row => row.id)).toEqual(initialIds);
    reading = leadsRead(page);
    await page.reload();
    current = await readPage(page, await reading);
    expect(current.items.map(row => row.id)).toEqual(initialIds);
    await expect(leadRow(page, submitted[0].id)).toHaveCount(1);
    const seen: Lead[] = [];
    const cursors = new Set<string>();
    let retainedDetailChecked = false;
    for (let pageIndex = 0; pageIndex < 100; pageIndex++) {
      seen.push(...current.items);
      const historical = current.items.filter(row => seeded.historical_ids.includes(row.id));
      for (const row of historical) expect(row.notification.eligible, "Retained historical rows must not become new mail obligations.").toBe(false);
      if (!retainedDetailChecked && historical.length) {
        expect(historical[0].contact_mobile, "The retained fixture must cover the phone detail that public forms do not collect.").not.toBeNull();
        await leadDetails(page, historical[0]);
        await expect(leadRow(page, historical[0].id).getByText("Not eligible for new-submission notifications")).toBeVisible();
        retainedDetailChecked = true;
      }
      if (!current.has_more) break;
      expect(current.next_cursor).not.toBeNull();
      expect(cursors.has(current.next_cursor!)).toBe(false);
      cursors.add(current.next_cursor!);
      reading = leadsRead(page);
      await page.getByRole("button", { name: "Next page", exact: true }).click();
      const nextResponse = await reading;
      expect(new URL(nextResponse.url()).searchParams.get("cursor")).toBe(current.next_cursor);
      current = await readPage(page, nextResponse);
      await noOverflow(page);
    }
    expect(current.has_more, "Bounded real pagination must reach the final page, not stop at 250.").toBe(false);
    expect(new Set(seen.map(row => row.id)).size).toBe(seen.length);
    expect(seen.map(row => row.id)).toEqual(expect.arrayContaining([...seeded.historical_ids, ...submitted.map(row => row.id)]));
    expect(seen.map(row => row.id)).not.toContain(seeded.excluded_commercial_id);
    expect(seen.length).toBeGreaterThan(250);
    expect(retainedDetailChecked).toBe(true);
    const sortKey = (row: Lead) => [Date.parse(row.submitted_at), row.id] as const;
    for (let i = 1; i < seen.length; i++) {
      const a = sortKey(seen[i - 1]); const b = sortKey(seen[i]);
      expect(a[0] > b[0] || (a[0] === b[0] && a[1] > b[1])).toBe(true);
    }
    await leadControls(page);
    await expect(page.getByRole("button", { name: "Next page", exact: true })).toBeDisabled();
    reading = leadsRead(page);
    await page.getByRole("button", { name: "Previous page", exact: true }).click();
    await readPage(page, await reading);
    await info.attach("real-local-lead-pagination", { contentType: "application/json", body: JSON.stringify({
      run_id: run, release_sha: target.sha, submitted_ids: submitted.map(row => row.id), retained_historical_ids: seeded.historical_ids,
      collected_ids: seen.map(row => row.id), notification_ids: captured.map(row => row.lead_id), external_calls: 0,
      scope: "Real isolated loopback only; not production lead, inbox delivery or owner acceptance",
    }) });

    await page.goto(`${target.web.origin}/platform/admins`);
    const viewerEmail = `viewer-${run}@example.com`;
    await page.getByLabel("Full name", { exact: true }).fill("Synthetic lead-denied viewer");
    await page.getByLabel("Email", { exact: true }).fill(viewerEmail);
    const invitation = page.waitForResponse(response => new URL(response.url()).pathname === `${CONSOLE}/admins/invitations`
      && response.request().method() === "POST");
    await page.getByRole("button", { name: "Invite viewer", exact: true }).click();
    expect((await invitation).status()).toBe(200);
    const link = await capturedLink(api, target, fixture, viewerEmail, "invite");
    const viewerContext = await browser.newContext({ ...(mobile ? devices["Pixel 5"] : { viewport: { width: 1280, height: 1000 } }),
      storageState: { cookies: [], origins: [] }, extraHTTPHeaders: localTransportHeaders(target.web.origin), serviceWorkers: "block" });
    contexts.push(viewerContext);
    blocked.push(await localWireGuard(viewerContext, target));
    const viewer = await viewerContext.newPage();
    viewer.on("pageerror", () => errors.push("pageerror"));
    await completeSetup(viewer, link, `Viewer-only!${randomUUID()}aA9`, "Synthetic lead-denied viewer");
    await enrollMfa(viewer, target, viewerEmail);
    expect((await expectState(viewer, target, "authenticated")).admin?.role).toBe("viewer");
    expect((await safeGet(viewer.request, `${target.api.origin}${CONSOLE}/leads`)).status()).toBe(403);
    await viewer.goto(`${target.web.origin}/platform/leads`);
    await expect(viewer.getByRole("main").getByRole("heading", { name: "Access denied", exact: true })).toBeVisible();
    await expect(viewer.getByRole("region", { name: "Public leads", exact: true })).toHaveCount(0);
    await expect(viewer.getByRole("link", { name: "Leads", exact: true })).toHaveCount(0);
    await noOverflow(viewer);
    expect((await safePost(page.request, `${target.api.origin}${CONSOLE}/auth/logout`, { headers: await contextCsrf(page.context()), data: {} })).status()).toBe(200);
    expect((await safeGet(page.request, `${target.api.origin}${CONSOLE}/leads`)).status()).toBe(401);
    await page.goto(`${target.web.origin}/platform/leads`);
    await expect(page.getByRole("main").getByRole("heading", { name: "Sign in required", exact: true })).toBeVisible();
    await expect(page.getByRole("region", { name: "Public leads", exact: true })).toHaveCount(0);
    expect(errors).toEqual([]);
    expect(blocked.flat()).toEqual([]);
    await assertRelease(target);
  } catch (error) { failed = true; throw error; }
  finally {
    const cleanupFailures: string[] = [];
    for (const context of contexts.reverse()) try { await context.close(); } catch { cleanupFailures.push("owned_context_close_failed"); }
    if (fixture && leadFixtureAttempted) try { await cleanupLocalLeads(api, target, fixture); } catch { cleanupFailures.push("retained_lead_cleanup_failed"); }
    try { await cleanupLocalFixture(api, target, run, fixture?.manager.id ?? null); } catch { cleanupFailures.push("retained_console_cleanup_failed"); }
    try { await api.dispose(); } catch { cleanupFailures.push("owned_api_context_dispose_failed"); }
    await info.attach("local-lead-cleanup", { contentType: "application/json", body: JSON.stringify({ run_id: run, cleanup_failures: cleanupFailures }) });
    if (cleanupFailures.length && !failed) throw new Error(`Lead cleanup incomplete: ${cleanupFailures.join(", ")}`);
  }
}

const requiredJourney = { annotation: [
  { type: "scope", description: "Real loopback admission, deterministic local reference capture and actual synthetic-account MFA only; never real email or owner acceptance." },
  { type: "required-public-entries", description: JSON.stringify(publicLeadForms) },
] };

test("LEAD-01..05 real local seven-form admission notification and MFA manager directory", requiredJourney, async ({ page, browser, baseURL }, info) => {
  await journey(page, browser, baseURL, false, info);
});

test("[mobile] LEAD-01..05 real local seven-form admission notification and MFA manager directory", requiredJourney, async ({ page, browser, baseURL }, info) => {
  await journey(page, browser, baseURL, true, info);
});
