/**
 * Tester workbook dated 27 Nov 2026 (reported by the nova-legal tester).
 *
 * Row 1: "Canonical Bench dropdown is empty while adding a Bench Alias"
 *   (/app/admin/judge-aliases, Aliases tab, Bench alias form). No migration,
 *   seed job or route had ever written a canonical bench, so the picker had
 *   nothing to offer anywhere. The release now carries every seat of each
 *   catalogued High Court from official sources (a single-seat court such as
 *   Delhi as its Principal Seat), and the picker states its count, a search
 *   with no match, a searched court with no catalogued seat, or a failed read.
 *   The journey reads the release-owned catalogue only; it never creates the
 *   benches it tests.
 * Row 4: "Unverified Act entries are not selectable in Add Reference". The
 *   disabled state is intended (only source-verified text is attached), so
 *   the journey proves the dialog says so, to sighted and screen-reader users,
 *   for every Act the API reports without verified text, and that a verified
 *   provision of a partially verified Act is still attached end to end.
 *
 * Production signs in as the test-legal tester (CASEOPS_RAM_PROD_SLUG,
 * CASEOPS_RAM_PROD_EMAIL, CASEOPS_RAM_PROD_PASSWORD) on the exact expected
 * release (CASEOPS_EXPECTED_RELEASE_SHA). In production the bench alias form is
 * filled but not submitted: bench aliases are a shared cross-tenant catalogue
 * with no retire route, so a production write would leave permanent residue in
 * every tenant. The row 4 journey creates its own clock-stamped matter through
 * the UI and disposes it. Missing setup fails; nothing here skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";
import { seedVerifiedLocalStatute } from "./support/verified-statute-fixture";

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
  /** API oracle headers only; the journeys act through the page. */
  headers: Record<string, string>;
};
type BenchRow = { id: string; court_id: string; court_short_name: string; name: string; source_url: string | null };
type BenchPage = { benches: BenchRow[]; returned_count: number; total_count: number; has_more: boolean;
  courts_without_benches: { id: string; name: string; short_name: string }[]; courts_without_benches_total: number };
const BENCH_HINT = "Search by court (Delhi), seat city (Nagpur) or bench name. A court that sits only at its principal seat lists one Principal Seat.";
type StatuteRow = { id: string; short_name: string; section_count: number; catalog_section_count: number };
type CatalogSection = { id: string; section_number: string; selection_state: string };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

function localCredentials(): TesterCredentials {
  const slug = process.env.CASEOPS_RAM_LOCAL_SLUG?.trim();
  const email = process.env.CASEOPS_RAM_LOCAL_EMAIL?.trim();
  const password = process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim();
  if (slug && email && password) return { slug, email, password };
  return { slug: `nov27-${randomUUID()}`, email: `nov27-${randomUUID()}@example.com`,
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
  await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  // Local only: the release statute seed, so the journey does not depend on spec order.
  seedVerifiedLocalStatute(local);
  const credentials: TesterCredentials = local ? localCredentials() : {
    slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal",
    email: required("CASEOPS_RAM_PROD_EMAIL"),
    password: required("CASEOPS_RAM_PROD_PASSWORD"),
  };
  if (!local && credentials.slug !== "test-legal") {
    throw new Error("Production acceptance runs only in the test-legal tester workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Test Legal LLP", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Ram Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` } };
}

const isRequest = (method: string, pattern: RegExp) => (r: { url(): string; request(): { method(): string } }) =>
  r.request().method() === method && pattern.test(new URL(r.url()).pathname);

async function benchOracle(request: APIRequestContext, rt: Runtime, q: string): Promise<BenchPage> {
  const query = new URLSearchParams({ q, limit: "200" });
  return json<BenchPage>(await request.get(`${rt.api.origin}/api/judge-mapping/catalog/benches?${query}`,
    { headers: rt.headers }), "Bench catalogue oracle");
}

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}row 1 the Canonical bench picker offers the searched court's benches`, async ({ page, request, baseURL }) => {
    test.setTimeout(180_000);
    await page.setViewportSize(phone ? PHONE : DESKTOP);
    const rt = await runtimeFor(baseURL, request);
    const bombay = await benchOracle(request, rt, "Bombay");
    expect(bombay.total_count, "The release catalogue holds the Bombay High Court benches").toBeGreaterThanOrEqual(5);
    const nagpur = bombay.benches.find((row) => row.court_id === "bombay-hc" && row.name === "Bench at Nagpur");
    expect(nagpur, "Bench at Nagpur is a release-owned bench").toBeTruthy();

    await signIn(page, { web: rt.web }, rt.credentials);
    await page.goto(`${rt.web.origin}/app/admin/judge-aliases`);
    await page.getByRole("tab", { name: "Aliases" }).click();
    const form = page.getByRole("heading", { name: "Bench alias" }).locator("..");
    const select = form.getByLabel("Canonical bench", { exact: true });
    const status = form.getByTestId("bench-alias-catalog-status");
    await expect(status).toContainText("canonical benches shown");

    // The tester's step: type in "Search benches", then open the dropdown.
    const searched = page.waitForResponse((r) => isRequest("GET", /^\/api\/judge-mapping\/catalog\/benches$/)(r)
      && new URL(r.url()).searchParams.get("q") === "Bombay");
    await form.getByLabel("Search benches").fill("Bombay");
    await json(await searched, "Bench search from the page");
    await expect(status).toHaveText(
      `${bombay.returned_count} of ${bombay.total_count} canonical benches shown. ${BENCH_HINT}`,
    );
    const offered = await select.locator("option").evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value).filter(Boolean));
    expect(offered, "The picker offers exactly the server catalogue for the search").toEqual(
      bombay.benches.map((row) => row.id));
    await expect(select.locator(`option[value="${nagpur!.id}"]`)).toHaveText("Bench at Nagpur · Bombay HC");
    await select.selectOption(nagpur!.id);
    await expect(select).toHaveValue(nagpur!.id);

    const alias = stamp("Nov27 Nagpur alias");
    await form.getByLabel("Alias").fill(alias);
    await form.getByLabel("Official source URL").fill(nagpur!.source_url ?? "https://bombayhighcourt.gov.in/bhc/");
    const add = form.getByRole("button", { name: /add bench alias/i });
    await expect(add).toBeEnabled();
    if (rt.local) {
      const saved = page.waitForResponse(isRequest("POST", new RegExp(`^/api/judge-mapping/benches/${nagpur!.id}/aliases$`)));
      await add.click();
      const created = await json<{ alias_text: string; is_active: boolean }>(await saved, "Add bench alias");
      expect([created.alias_text, created.is_active]).toEqual([alias, true]);
      await expect(page.getByText("Bench alias added.")).toBeVisible();
    }

    // A search with no match explains itself instead of leaving an empty list.
    const none = `No Such Bench ${randomUUID().slice(0, 6)}`;
    await form.getByLabel("Search benches").fill(none);
    await expect(status).toHaveText(
      `No canonical bench matches “${none}”. ${BENCH_HINT}`);
    await expect(select.locator("option")).toHaveCount(1);
    await expect(add).toBeDisabled();

    // The tester most likely searched a single-seat court: Delhi offers its principal seat.
    const delhi = await benchOracle(request, rt, "Delhi High Court");
    expect(delhi.benches.map((row) => [row.court_id, row.name]),
      "Delhi High Court is catalogued as one principal seat").toEqual([["delhi-hc", "Principal Seat at Delhi"]]);
    const delhiSearched = page.waitForResponse((r) => isRequest("GET", /^\/api\/judge-mapping\/catalog\/benches$/)(r)
      && new URL(r.url()).searchParams.get("q") === "Delhi High Court");
    await form.getByLabel("Search benches").fill("Delhi High Court");
    await json(await delhiSearched, "Delhi bench search from the page");
    await expect(status).toHaveText(`1 of 1 canonical benches shown. ${BENCH_HINT}`);
    await expect(select.locator(`option[value="${delhi.benches[0].id}"]`)).toHaveText("Principal Seat at Delhi · Delhi HC");
    await select.selectOption(delhi.benches[0].id);
    await form.getByLabel("Alias").fill(stamp("Nov27 Delhi seat alias"));
    await form.getByLabel("Official source URL").fill("https://delhihighcourt.nic.in/");
    await expect(add).toBeEnabled();
    if (rt.local) {
      const delhiSaved = page.waitForResponse(isRequest("POST",
        new RegExp(`^/api/judge-mapping/benches/${delhi.benches[0].id}/aliases$`)));
      await add.click();
      expect((await json<{ is_active: boolean }>(await delhiSaved, "Add Delhi principal seat alias")).is_active).toBe(true);
    }

    // A court the catalogue holds without any seat is named, with the next step.
    const all = await benchOracle(request, rt, "");
    expect(all.courts_without_benches.length, "The release leaves at least the Supreme Court without seats")
      .toBeGreaterThan(0);
    const bare = all.courts_without_benches[0];
    const bareOracle = await benchOracle(request, rt, bare.name);
    expect(bareOracle.benches, `${bare.name} has no catalogued bench`).toEqual([]);
    await form.getByLabel("Search benches").fill(bare.name);
    await expect(status).toContainText(`No canonical benches are catalogued for ${bare.name}`);
    await expect(status).toContainText("Ask your platform administrator to have its benches catalogued");
    await expect(select.locator("option")).toHaveCount(1);
    await expect(add).toBeDisabled();
    if (phone) {
      expect(await page.evaluate(() => document.documentElement.scrollWidth
        <= document.documentElement.clientWidth + 1), "No horizontal overflow on a phone").toBe(true);
    }
  });
}

async function createMatterThroughUi(page: Page, rt: Runtime): Promise<string> {
  const code = `N27S-${randomUUID().slice(0, 8).toUpperCase()}`;
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(stamp("Nov27 unverified Act matter"));
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Direct Tax");
  const created = page.waitForResponse(isRequest("POST", /^\/api\/matters\/?$/));
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await json<{ id: string; matter_code: string }>(await created, "Create matter through the Matters page");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter.id;
}

async function disposeMatter(page: Page, rt: Runtime, matterId: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  await page.getByTestId("matter-dispose-trigger").click();
  await page.getByTestId("matter-lifecycle-reason").fill("Nov 27 statute journey retires its own test matter.");
  const disposed = page.waitForResponse((r) => r.request().method() === "PATCH"
    && new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status`);
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await json<{ status: string }>(await disposed, "Dispose the journey matter")).status).toBe("disposed");
}

async function tap(page: Page, phone: boolean, target: ReturnType<Page["locator"]>) {
  await expect(target).toBeVisible();
  if (phone) await target.tap();
  else await target.click();
}

for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}row 4 a disabled Act says why, and a verified provision still attaches`, async ({ page, request, baseURL }) => {
    test.setTimeout(240_000);
    await page.setViewportSize(phone ? PHONE : DESKTOP);
    const rt = await runtimeFor(baseURL, request);
    const catalog = await json<{ statutes: StatuteRow[] }>(await request.get(`${rt.api.origin}/api/statutes/`,
      { headers: rt.headers }), "Act catalogue oracle");
    const pending = catalog.statutes.filter((row) => row.section_count === 0);
    const constitution = catalog.statutes.find((row) => row.id === "constitution-india");
    expect(constitution?.section_count, "The Constitution has verified Articles").toBeGreaterThan(0);
    const sections = await json<{ catalog_sections: CatalogSection[] }>(await request.get(
      `${rt.api.origin}/api/statutes/constitution-india/sections`, { headers: rt.headers }), "Constitution sections oracle");
    const article14 = sections.catalog_sections.find((row) => row.section_number === "Article 14");
    const disabled = sections.catalog_sections.find((row) => row.selection_state !== "verified_selectable");
    expect(article14?.selection_state).toBe("verified_selectable");
    expect(disabled, "The Constitution keeps omitted or withheld entries listed").toBeTruthy();

    await signIn(page, { web: rt.web }, rt.credentials);
    let matterId: string | undefined;
    try {
      matterId = await createMatterThroughUi(page, rt);
      await page.goto(`${rt.web.origin}/app/matters/${matterId}/statutes`);
      await tap(page, phone, page.getByTestId("matter-statute-add-trigger"));
      const dialog = page.getByRole("dialog", { name: "Add statute reference" });
      await expect(dialog.getByTestId("matter-statute-catalog-coverage")).toBeVisible();
      const note = dialog.getByTestId("matter-statute-pending-acts-note");
      if (pending.length > 0) {
        // The reason is on the dialog itself, before any option is opened.
        await expect(note).toContainText("Why some Acts are disabled.");
        await expect(note).toContainText("This is intentional");
        for (const act of pending.slice(0, 5)) await expect(note).toContainText(act.short_name);
      } else {
        await expect(note, "No disabled-Act explanation when every Act is attachable").toHaveCount(0);
      }

      await tap(page, phone, dialog.getByTestId("matter-statute-act-select"));
      const list = page.getByRole("listbox");
      await expect(list).toBeVisible();
      for (const act of pending) {
        const option = list.locator(`[data-value="${act.id}"]`);
        await expect(option).toHaveAttribute("aria-disabled", "true");
        await expect(option).toContainText(`(0 verified of ${act.catalog_section_count} catalogued; not attachable until verified)`);
        await expect(option).toHaveAccessibleDescription(/This is intentional/);
      }
      if (pending.length > 0) {
        await expect(page.getByTestId("matter-statute-act-group-pending-reason")).toContainText("Disabled on purpose");
      }
      await tap(page, phone, list.locator('[data-value="constitution-india"]'));
      await expect(dialog.getByTestId("matter-statute-act-select")).toContainText("The Constitution of India");

      await tap(page, phone, dialog.getByTestId("matter-statute-section-select"));
      const sectionList = page.getByRole("listbox");
      const withheld = sectionList.locator(`[data-value="${disabled!.id}"]`);
      await withheld.scrollIntoViewIfNeeded();
      await expect(withheld).toHaveAttribute("aria-disabled", "true");
      await expect(withheld).toHaveAccessibleDescription(/Disabled provisions are intentional/);
      const verified = sectionList.locator(`[data-value="${article14!.id}"]`);
      await verified.scrollIntoViewIfNeeded();
      await tap(page, phone, verified);
      const submit = dialog.getByTestId("matter-statute-add-submit");
      await expect(submit).toBeEnabled();
      const attached = page.waitForResponse(isRequest("POST", new RegExp(`^/api/matters/${matterId}/statute-references$`)));
      await tap(page, phone, submit);
      const created = await json<{ id: string; section_id: string }>(await attached, "Attach Article 14", 201);
      expect(created.section_id).toBe(article14!.id);
      await expect(page.getByTestId(`matter-statute-ref-${created.id}`)).toContainText("Article 14");
      const removed = page.waitForResponse(isRequest("DELETE",
        new RegExp(`^/api/matters/${matterId}/statute-references/${created.id}$`)));
      await tap(page, phone, page.getByRole("button", { name: /^Remove .*Article 14$/ }));
      expect((await removed).status()).toBe(204);
    } finally {
      if (matterId) await disposeMatter(page, rt, matterId);
    }
  });
}
