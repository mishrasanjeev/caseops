/**
 * Tester workbook dated 27 Nov 2026 (Aishwarya, nova-legal), rows 5, 7, 8, 9.
 *
 * Production runs sign in as the test-legal tester only (owner decision,
 * 27 Nov 2026): CASEOPS_RAM_PROD_SLUG / _EMAIL / _PASSWORD plus
 * CASEOPS_EXPECTED_RELEASE_SHA, never committed. Every journey creates its own
 * matter through the UI with a clock+serial code and disposes it at the end;
 * nothing assumes nova-legal records exist. Production never saves or tests
 * the shared Microsoft 365 configuration (read-only there); the save/test half
 * of row 8 is [local-only]. Locally each run bootstraps its own workspace.
 *
 * API calls are oracles only (what the server says the page must show).
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
const DELHI_HC_SITE = "https://delhihighcourt.nic.in/";
const OUTLOOK_CALLBACK = "/api/calendar/connections/outlook/callback";
const AFFIDAVIT_TEXT = [
  "AFFIDAVIT IN SUPPORT OF THE PETITION",
  "Page 2. I state that on 12.04.2026 the respondent received goods worth Rs. 5,00,000 under",
  "Invoice No. 118. The invoice is annexed as Annexure A. The respondent defaulted on payment",
  "and no receipt is identified. I state that a legal notice was served on 02.05.2026 and the",
  "respondent refused to accept delivery. I submit that the respondent acknowledged the debt",
  "by an email dated 15.05.2026, annexed as Annexure B.",
].join("\n");

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  headers: Record<string, string>;
  release: () => Promise<void>;
};

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
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
  const credentials: TesterCredentials = local
    ? { slug: `nov27-${randomUUID()}`, email: `nova-${randomUUID()}@example.com`, password: `Synthetic!${randomUUID()}` }
    : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (!local && credentials.slug !== "test-legal") {
    throw new Error("Production acceptance for this workbook runs only in the test-legal workspace.");
  }
  if (local) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Nova Legal Associates", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Aishwarya Rao", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(
    await request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } }),
    "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials, release,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` } };
}

const isPost = (pattern: RegExp) => (r: { url(): string; request(): { method(): string } }) =>
  r.request().method() === "POST" && pattern.test(new URL(r.url()).pathname);

/** New matter dialog on /app/matters, court chosen from the catalogue search. */
type HighCourt = { state: string; entryId: string; name: string };
const DELHI_HC: HighCourt = { state: "Delhi", entryId: "hc:delhi", name: "Delhi High Court" };
const ALLAHABAD_HC: HighCourt = { state: "Uttar Pradesh", entryId: "hc:allahabad", name: "Allahabad High Court" };

async function createMatterThroughUi(page: Page, rt: Runtime, code: string, court: HighCourt | null) {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(`${code} hearing preparation`);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Commercial Litigation");
  if (court) {
    // The forum hierarchy pickers: High Court > state > exact court.
    await dialog.getByTestId("new-matter-forum-category").selectOption("high_court");
    await dialog.getByTestId("new-matter-forum-state").selectOption(court.state);
    await dialog.getByTestId("new-matter-forum-high-court").selectOption(court.entryId);
  }
  const create = dialog.getByRole("button", { name: "Create matter" });
  await expect(create).toBeEnabled();
  const created = page.waitForResponse(isPost(/^\/api\/matters\/?$/));
  await create.click();
  const matter = await json<{ id: string; matter_code: string; court_name: string | null;
    court_website_url: string | null }>(await created, "Create matter through the Matters page");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter;
}

async function disposeThroughUi(page: Page, rt: Runtime, matterId: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  await page.getByTestId("matter-dispose-trigger").click();
  await page.getByTestId("matter-lifecycle-reason").fill("Nov 27 workbook journey retires its own test matter.");
  const disposed = page.waitForResponse((r) => r.request().method() === "PATCH"
    && new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status`);
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await json<{ status: string }>(await disposed, "Dispose the journey matter")).status).toBe("disposed");
}

// Row 5: the court badge above Team Assigned opens the court's official site.
test("row 5 court badge opens the official court website in a new tab", async ({ page, request, baseURL, context }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 1366, height: 900 });
  await signIn(page, rt, rt.credentials);
  // Never load the government site from the test runner: answer it locally.
  await context.route("https://delhihighcourt.nic.in/**", (route) =>
    route.fulfill({ status: 200, contentType: "text/html", body: "<title>High Court of Delhi</title>" }));
  const matter = await createMatterThroughUi(page, rt, stamp("NOV27-CRT").replace(/\s+/g, "-"), DELHI_HC);
  try {
    expect(matter.court_name).toBe("Delhi High Court");
    // Mutation responses render no badge, so they never pay for the lookup.
    expect(matter.court_website_url, "Create response carries no website").toBeNull();
    const detail = await json<{ court_website_url: string | null }>(
      await request.get(`${rt.api.origin}/api/matters/${matter.id}`, { headers: rt.headers }), "Matter detail oracle");
    expect(detail.court_website_url, "Server resolves the site from the catalogue identity").toBe(DELHI_HC_SITE);
    // The matter list resolves it in its batched lookup too.
    // Production keeps every earlier run's Matters, so find this run's row by
    // its own code (server-side search) rather than trusting the first page.
    await page.goto(`${rt.web.origin}/app/matters`);
    await page.getByRole("searchbox", { name: "Search all rows" }).fill(matter.matter_code);
    await expect(page.getByTestId(`matter-court-${matter.id}`)).toHaveAttribute("href", DELHI_HC_SITE);
    await page.goto(`${rt.web.origin}/app/matters/${matter.id}`);
    const badge = page.getByTestId("matter-court-badge");
    await expect(badge).toHaveAccessibleName("Open Delhi High Court website (opens in new tab)");
    await expect(badge).toHaveAttribute("href", DELHI_HC_SITE);
    await expect(badge).toHaveAttribute("target", "_blank");
    await expect(badge).toHaveAttribute("rel", "noopener noreferrer");
    await expect(badge).toContainText("Delhi High Court");
    const popupPromise = page.waitForEvent("popup");
    await badge.click();
    const popup = await popupPromise;
    await popup.waitForLoadState();
    expect(popup.url()).toBe(DELHI_HC_SITE);
    await expect(page).toHaveURL(`${rt.web.origin}/app/matters/${matter.id}`);
    await popup.close();
  } finally {
    await disposeThroughUi(page, rt, matter.id);
  }
  await rt.release();
});

test("row 5 a court without a verified website is plain text, not a dead link", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 1366, height: 900 });
  await signIn(page, rt, rt.credentials);
  // Allahabad's official site is not on a government domain, so it is not linked.
  const matter = await createMatterThroughUi(page, rt, stamp("NOV27-ALD").replace(/\s+/g, "-"), ALLAHABAD_HC);
  try {
    expect(matter.court_website_url).toBeNull();
    const detail = await json<{ court_website_url: string | null }>(
      await request.get(`${rt.api.origin}/api/matters/${matter.id}`, { headers: rt.headers }), "Matter detail oracle");
    expect(detail.court_website_url).toBeNull();
    await page.goto(`${rt.web.origin}/app/matters/${matter.id}`);
    const badge = page.getByTestId("matter-court-badge");
    await expect(badge).toContainText("Allahabad High Court");
    await expect(badge).toHaveAttribute("data-court-link", "none");
    expect(await badge.evaluate((node) => node.closest("a"))).toBeNull();
  } finally {
    await disposeThroughUi(page, rt, matter.id);
  }
  await rt.release();
});

// Row 7: Start session must not be an impossible action.
test("row 7 mock hearing shows its prerequisites, runs affidavit intelligence, then starts", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 1366, height: 900 });
  await signIn(page, rt, rt.credentials);
  const matter = await createMatterThroughUi(page, rt, stamp("NOV27-MH").replace(/\s+/g, "-"), null);
  const readiness = async () => json<{ ready: boolean; next_action: string }>(
    await request.get(`${rt.api.origin}/api/matters/${matter.id}/mock-hearing-readiness`, { headers: rt.headers }),
    "Readiness oracle");
  let sessionId: string | null = null;
  try {
    await page.goto(`${rt.web.origin}/app/matters/${matter.id}/hearings`);
    const section = page.getByTestId("mock-hearing-section");
    const start = section.getByTestId("mock-hearing-start");
    const panel = section.getByTestId("mock-hearing-readiness");
    // Before any click: disabled, with the reason and the next action.
    await expect(panel).toHaveAttribute("data-ready", "false");
    await expect(start).toBeDisabled();
    await expect(panel).toContainText("Before you can start a session");
    await expect(panel.getByTestId("mock-hearing-check-affidavit_run")).toHaveAttribute("data-status", "missing");
    expect((await readiness()).next_action).toBe("upload_affidavit");

    // Primary action: lands on documents with the affidavit type chosen and focused.
    await panel.getByTestId("mock-hearing-upload-affidavit").click();
    await expect(page).toHaveURL(`${rt.web.origin}/app/matters/${matter.id}/documents?affidavit=upload`);
    const typeSelect = page.getByTestId("matter-attachment-document-type");
    await expect(typeSelect).toHaveValue("affidavit");
    await expect(typeSelect).toBeFocused();
    const uploaded = page.waitForResponse(isPost(new RegExp(`^/api/matters/${matter.id}/attachments$`)));
    await page.setInputFiles('[data-testid="matter-attachment-file-input"]', {
      name: "affidavit-in-support.txt", mimeType: "text/plain", buffer: Buffer.from(AFFIDAVIT_TEXT, "utf8"),
    });
    await json(await uploaded, "Upload the affidavit through the Documents page");
    await expect.poll(async () => (await readiness()).next_action, { timeout: 90_000 })
      .toBe("run_affidavit_intelligence");

    await page.goto(`${rt.web.origin}/app/matters/${matter.id}/hearings`);
    await expect(start).toBeDisabled();
    const run = panel.getByTestId("mock-hearing-run-affidavit");
    await expect(run).toBeEnabled();
    const analysed = page.waitForResponse(isPost(/\/affidavit-intelligence\/analyze$/));
    await run.click();
    await json(await analysed, "Run affidavit intelligence from the checklist");
    await expect(start).toBeEnabled();
    expect((await readiness()).ready).toBe(true);

    const started = page.waitForResponse(isPost(new RegExp(`^/api/matters/${matter.id}/mock-hearings$`)));
    await start.click();
    const session = await json<{ id: string; questions: unknown[] }>(await started, "Start the mock hearing session");
    sessionId = session.id;
    expect(session.questions.length).toBeGreaterThan(0);
    await expect(section.getByTestId("mock-hearing-current-question")).toBeVisible();
  } finally {
    if (sessionId) {
      await request.post(`${rt.api.origin}/api/matters/${matter.id}/mock-hearings/${sessionId}/complete`,
        { headers: rt.headers });
    }
    await disposeThroughUi(page, rt, matter.id);
  }
  await rt.release();
});

// Row 8: the admin sees the exact Redirect URI and Tenant ID guidance.
test("row 8 Microsoft 365 setup shows the redirect URI the flow uses and tenant ID guidance", async ({ page, request, baseURL }) => {
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 1366, height: 900 });
  await signIn(page, rt, rt.credentials);
  const expected = `${rt.api.origin}${OUTLOOK_CALLBACK}`;
  const oracle = await json<{ expected_redirect_uri: string }>(
    await request.get(`${rt.api.origin}/api/admin/microsoft365-configuration`, { headers: rt.headers }), "M365 oracle");
  expect(oracle.expected_redirect_uri).toBe(expected);

  await page.goto(`${rt.web.origin}/app/admin/microsoft365`);
  const redirect = page.getByLabel("Redirect URI", { exact: true });
  await expect(redirect).toHaveValue(expected);
  await expect(redirect).toHaveAttribute("readonly", "");
  await expect(page.getByRole("button", { name: "Copy Redirect URI" })).toBeVisible();
  await expect(page.getByTestId("m365-setup-steps")).toContainText("Directory (tenant) ID");
  await expect(page.getByTestId("m365-permissions")).toContainText("Calendars.ReadWrite");
  // No sign-in reads this configuration: the page says so and points to Outlook.
  const scope = page.getByTestId("m365-scope-note");
  await expect(scope).toContainText("No CaseOps sign-in reads them yet");
  await expect(scope.getByRole("link", { name: "Outlook calendar" })).toHaveAttribute("href", "/app/admin/outlook");
  const tenant = page.getByLabel("Directory (tenant) ID");
  const before = await tenant.inputValue();
  await tenant.fill("common");
  await expect(page.getByText(/is a sign-in mode, not your directory/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save" })).toBeDisabled();
  await tenant.fill(before); // never saved; production configuration stays unchanged

  // The Outlook page shows the same single value.
  await page.goto(`${rt.web.origin}/app/admin/outlook`);
  await expect(page.getByLabel("Redirect URI to register in Microsoft Entra", { exact: true })).toHaveValue(expected);
  await rt.release();
});

test("row 8 [local-only] saving valid values and Test reports a complete setup", async ({ page, request, baseURL }) => {
  const rt = await runtimeFor(baseURL, request);
  // Excluded from production by the [local-only] grep: it writes tenant configuration.
  if (!rt.local) throw new Error("Production never writes the shared tester Microsoft 365 configuration.");
  await page.setViewportSize({ width: 1366, height: 900 });
  await signIn(page, rt, rt.credentials);
  await page.goto(`${rt.web.origin}/app/admin/microsoft365`);
  await page.getByLabel("Application (client) ID").fill("0b6f2a4e-1c3d-4e5f-8a9b-0c1d2e3f4a5b");
  await page.getByLabel("Client secret").fill(`local-${randomUUID()}`);
  await page.getByLabel("Directory (tenant) ID").fill("72f988bf-86f1-41af-91ab-2d7cd011db47");
  await page.getByLabel("Admin consent granted in Microsoft Entra").check();
  await page.getByLabel("Graph permissions reviewed for review-first workflows").check();
  const saved = page.waitForResponse((r) => r.request().method() === "PATCH"
    && new URL(r.url()).pathname === "/api/admin/microsoft365-configuration");
  await page.getByRole("button", { name: "Save" }).click();
  const response = await saved;
  if (response.status() === 403) {
    // Credential changes need a recent step-up; the inline errors above are the row's contract.
    throw new Error("Saving Microsoft 365 values required step-up in this local workspace.");
  }
  const body = await json<{ redirect_uri_matches_expected: boolean }>(response, "Save Microsoft 365 values");
  expect(body.redirect_uri_matches_expected).toBe(true);
  await page.getByTestId("m365-test").click();
  const results = page.getByTestId("m365-test-results");
  await expect(results).toContainText("All values and approvals saved");
  await expect(results).toContainText("Nothing is connected by this test");
  await expect(results.getByTestId("m365-check-redirect_uri_matches_deployment")).toHaveAttribute("data-status", "passed");
  await rt.release();
});

// Row 9: the sidebar keeps its place and scrolls on its own.
const VIEWPORTS = [
  { width: 1366, height: 768, label: "1366x768" },
  { width: 1280, height: 720, label: "1280x720" },
  { width: 1920, height: 1080, label: "1920x1080" },
  { width: 1707, height: 960, label: "1366 at 80%" },
  { width: 1093, height: 614, label: "1366 at 125%" },
  { width: 911, height: 512, label: "1366 at 150%" },
];

async function expandAllGroups(page: Page) {
  for (const toggle of await page.locator('[data-testid^="sidebar-group-"]').all()) {
    if ((await toggle.getAttribute("aria-expanded")) === "false") await toggle.click();
  }
}

for (const viewport of VIEWPORTS) {
  test(`row 9 sidebar stays fixed and scrolls independently at ${viewport.label}`, async ({ page, request, baseURL }) => {
    const rt = await runtimeFor(baseURL, request);
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await signIn(page, rt, rt.credentials);
    // A long admin page: the main column must scroll past the viewport.
    await page.goto(`${rt.web.origin}/app/admin/microsoft365`);
    await expect(page.getByTestId("m365-setup-steps")).toBeVisible();
    const sidebar = page.getByTestId("app-sidebar");
    const nav = sidebar.getByTestId("sidebar-nav-scroller");
    await expandAllGroups(page);
    const pageScrolls = await page.evaluate(() => document.documentElement.scrollHeight > window.innerHeight);
    expect(pageScrolls, "The test page must be taller than the viewport").toBe(true);

    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    const box = await sidebar.boundingBox();
    if (!box) throw new Error("Sidebar geometry unavailable");
    expect(Math.abs(box.y), "Sidebar top stays at 0 after the main content scrolls").toBeLessThanOrEqual(1);
    expect(Math.abs(box.height - viewport.height), "Sidebar is one viewport tall").toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    // The site footer under the shell is visible at the bottom and not hidden behind the sidebar.
    const footer = page.getByRole("complementary", { name: "CaseOps product ownership" }).locator("p").first();
    await expect(footer).toBeInViewport();
    const f = await footer.boundingBox();
    if (!f) throw new Error("Footer geometry unavailable");
    expect(f.x, "Footer text starts right of the fixed sidebar").toBeGreaterThanOrEqual(box.x + box.width - 1);

    const metrics = await nav.evaluate((node) => ({ scrollHeight: node.scrollHeight, clientHeight: node.clientHeight }));
    const lastLink = nav.getByRole("link").last();
    if (metrics.scrollHeight > metrics.clientHeight) {
      const windowY = await page.evaluate(() => window.scrollY);
      const navBox = await nav.boundingBox();
      if (!navBox) throw new Error("Nav geometry unavailable");
      await page.mouse.move(navBox.x + navBox.width / 2, navBox.y + navBox.height / 2);
      for (let i = 0; i < 30; i += 1) await page.mouse.wheel(0, 400);
      await expect.poll(() => nav.evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
      expect(await nav.evaluate((node) => Math.ceil(node.scrollTop + node.clientHeight) >= node.scrollHeight - 1)).toBe(true);
      expect(await page.evaluate(() => window.scrollY), "Scrolling the sidebar does not move the page").toBe(windowY);
    }
    // The last navigation item is reachable and is the element under the pointer.
    await lastLink.scrollIntoViewIfNeeded();
    const last = await lastLink.boundingBox();
    if (!last) throw new Error("Last nav item geometry unavailable");
    expect(last.y + last.height).toBeLessThanOrEqual(viewport.height + 1);
    const hit = await page.evaluate(([x, y]) => {
      const element = document.elementFromPoint(x, y);
      return element?.closest("a")?.getAttribute("href") ?? null;
    }, [last.x + last.width / 2, last.y + last.height / 2]);
    expect(hit).toBe(await lastLink.getAttribute("href"));
    await rt.release();
  });
}

test("row 9 full-height pages keep the sidebar fixed without horizontal overflow", async ({ page, request, baseURL }) => {
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 1366, height: 768 });
  await signIn(page, rt, rt.credentials);
  for (const path of ["/app/calendar", "/app/research", "/app/drafting", "/app/matters"]) {
    await page.goto(`${rt.web.origin}${path}`);
    await expect(page.locator("main#main")).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const box = await page.getByTestId("app-sidebar").boundingBox();
    if (!box) throw new Error(`Sidebar geometry unavailable on ${path}`);
    expect(Math.abs(box.y), `Sidebar top on ${path}`).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), path).toBe(true);
    const main = await page.locator("main#main").boundingBox();
    if (!main) throw new Error(`Main geometry unavailable on ${path}`);
    expect(main.x, `Main starts after the sidebar on ${path}`).toBeGreaterThanOrEqual(box.x + box.width - 1);
  }
  await rt.release();
});

test("[mobile] row 9 the phone navigation drawer still opens and scrolls to its last item", async ({ page, request, baseURL }) => {
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize({ width: 375, height: 812 });
  await signIn(page, rt, rt.credentials);
  await page.goto(`${rt.web.origin}/app`);
  await expect(page.getByTestId("app-sidebar")).toBeHidden();
  await page.getByTestId("mobile-nav-trigger").click();
  const drawer = page.getByRole("dialog", { name: "Workspace navigation" });
  await expect(drawer).toBeVisible();
  const nav = drawer.getByTestId("sidebar-nav-scroller");
  const lastLink = nav.getByRole("link").last();
  await lastLink.scrollIntoViewIfNeeded();
  const last = await lastLink.boundingBox();
  if (!last) throw new Error("Last drawer item geometry unavailable");
  expect(last.y + last.height).toBeLessThanOrEqual(812 + 1);
  const href = await lastLink.getAttribute("href");
  await lastLink.click();
  await expect(page).toHaveURL(new RegExp(`${href}$`));
  await expect(drawer).toBeHidden();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await rt.release();
});
