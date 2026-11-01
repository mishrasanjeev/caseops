/**
 * Ram batch-4 adjacent defects, truncation class (EH-B4-02): lists that
 * stopped at their first page with no total and no way to the rest.
 *
 * - B4-ADJ-18: the Documents "Linked docket" field on /app/ip listed the IP
 *   home page's first 100 dockets and chose the first one itself.
 * - B4-ADJ-05: the journal watch workspace stopped at 250 rows with no total.
 * - B4-ADJ-03: the drafting and recommendations hubs read one page of
 *   Matters and filtered it in the browser; the portfolio page counted one
 *   page; the notice register's Matter filter offered the first 100.
 * - B4-ADJ-15: the Matter timeline stopped at 200 events.
 *
 * Signed in as the tester in their own tenant. Every expected count comes
 * from the response the page itself received, and the row that matters is
 * the one the server sorts last (the oldest), found through the product's
 * own search. Locally a fresh tenant is given more dockets and Matters than
 * one picker page so the journey crosses a page boundary; production reads
 * test-legal's real portfolio and creates nothing, so nothing needs retiring.
 */
import {
  expect, test, type APIRequestContext, type Page, type Response, type TestInfo,
} from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const PICKER_PAGE = 50;
const MOBILE = { width: 393, height: 851 };

type Docket = { id: string; title: string };
type DocketPage = { dockets: Docket[]; has_more: boolean; next_cursor: string | null; total_count: number };
type MatterRow = { id: string; matter_code: string; title: string };
type MatterPage = { matters: MatterRow[]; next_cursor: string | null };
type WatchPage = {
  limit: number; offset: number;
  profiles: { id: string }[]; profile_total: number;
  hits: { id: string }[]; hit_total: number;
  publications: { id: string }[]; publication_total: number;
};

const count = (value: number) => value.toLocaleString("en-IN");

/** A response the UI itself made; body intentionally not logged. */
async function uiJson<T>(response: Promise<Response>, operation: string): Promise<T> {
  const received = await response;
  expect(received.status(), `${operation} returned ${received.status()}`).toBe(200);
  return received.json() as Promise<T>;
}

function apiRead(page: Page, rt: TesterRuntime, path: string, match: (url: URL) => boolean): Promise<Response> {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.origin === rt.api.origin && url.pathname === path && response.request().method() === "GET" && match(url);
  });
}

function particulars(mark: string) {
  return {
    form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
    representation: { text: mark, evidence_reference: `e2e:${mark.toLowerCase().replace(/\s+/g, "-")}` },
    classes: [{ class_number: 9, specification: "Downloadable legal software" }],
    use_priority: null, parties: [{ role: "applicant", name: "Test Legal Clients LLP" }], agent: null,
    filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: "e2e:adj-lists" }],
  };
}

/** Local only: more dockets than one picker page. The first is the oldest. */
async function seedLocalDockets(rt: TesterRuntime, request: APIRequestContext): Promise<Docket[]> {
  expect(rt.local, "Seeding is for a fresh local tenant only").toBe(true);
  const created: Docket[] = [];
  for (let index = 0; index < PICKER_PAGE + 3; index += 1) {
    const title = stamp(`B4 ADJ DOCKET ${index}`);
    created.push(await json<Docket>(await request.post(`${rt.api.origin}/api/ip/dockets`, {
      headers: rt.headers, data: { title, restricted: false, particulars: particulars(title) },
    }), `Local docket ${index}`, 201));
  }
  return created;
}

/** Local only: more Matters than one hub page. The first is the oldest. */
async function seedLocalMatters(rt: TesterRuntime, request: APIRequestContext): Promise<void> {
  expect(rt.local, "Seeding is for a fresh local tenant only").toBe(true);
  for (let index = 0; index < PICKER_PAGE + 2; index += 1) {
    await json(await request.post(`${rt.api.origin}/api/matters/`, {
      headers: rt.headers,
      data: {
        title: stamp(`B4 ADJ MATTER ${index}`), matter_code: `ADJ-${Date.now()}-${index}`,
        practice_area: "Commercial", forum_level: "high_court", status: "active",
      },
    }), `Local matter ${index}`);
  }
}

/** API oracle: every visible docket, newest change first. */
async function everyDocket(rt: TesterRuntime, request: APIRequestContext): Promise<Docket[]> {
  const rows: Docket[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "200", ...(cursor ? { cursor } : {}) });
    const page: DocketPage = await json<DocketPage>(
      await request.get(`${rt.api.origin}/api/ip/dockets?${query}`, { headers: rt.headers }), "Docket oracle page");
    rows.push(...page.dockets);
    cursor = page.has_more ? page.next_cursor : null;
  } while (cursor);
  return rows;
}

/** API oracle: every visible Matter, most recently updated first. */
async function everyMatter(rt: TesterRuntime, request: APIRequestContext): Promise<MatterRow[]> {
  const rows: MatterRow[] = [];
  let cursor: string | null = null;
  do {
    const query = new URLSearchParams({ limit: "200", ...(cursor ? { cursor } : {}) });
    const page: MatterPage = await json<MatterPage>(
      await request.get(`${rt.api.origin}/api/matters/?${query}`, { headers: rt.headers }), "Matter oracle page");
    rows.push(...page.matters);
    cursor = page.next_cursor;
  } while (cursor);
  return rows;
}

async function linkedDocketJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  if (rt.local) await seedLocalDockets(rt, request);
  const all = await everyDocket(rt, request);
  expect(all.length, "The tester must see at least one docket").toBeGreaterThan(0);
  const oldest = all[all.length - 1];

  const firstRead = apiRead(page, rt, "/api/ip/dockets",
    (url) => url.searchParams.get("limit") === String(PICKER_PAGE) && !url.searchParams.has("query") && !url.searchParams.has("cursor"));
  await page.goto(`${rt.web.origin}/app/ip?tab=documents`);
  const first = await uiJson<DocketPage>(firstRead, "Linked docket picker first page");
  expect(first.total_count, "The picker reads the server total of every visible docket").toBe(all.length);
  if (rt.local) expect(first.has_more, "Locally the portfolio is larger than one picker page").toBe(true);

  const linked = page.getByLabel("Linked docket", { exact: true });
  await linked.scrollIntoViewIfNeeded();
  await expectOnScreen(linked, "The Linked docket field is on screen");
  await expect(linked).toBeEnabled();
  await expect(linked, "No docket is chosen for the tester").toHaveValue("");
  const status = page.locator("#ip-document-docket-status");
  await expect(status).toHaveText(first.has_more
    ? `Showing ${count(first.dockets.length)} of ${count(first.total_count)} dockets — refine your search or load more.`
    : `${count(first.total_count)} ${first.total_count === 1 ? "docket" : "dockets"}.`);
  const oldestOption = linked.locator(`option[value="${oldest.id}"]`);
  await expect(oldestOption).toHaveCount(first.dockets.some((row) => row.id === oldest.id) ? 1 : 0);

  // The oldest docket is reached through the server search.
  const searched = apiRead(page, rt, "/api/ip/dockets", (url) => url.searchParams.get("query") === oldest.title);
  await page.getByLabel("Find the linked docket", { exact: true }).fill(oldest.title);
  const found = await uiJson<DocketPage>(searched, "Linked docket search");
  expect(found.dockets.map((row) => row.id)).toContain(oldest.id);
  await expect(oldestOption).toHaveCount(1);
  await linked.selectOption(oldest.id);
  await expect(linked).toHaveValue(oldest.id);
  expect(await deadSelects(page, page.getByTestId("ip-docket-picker"))).toEqual([]);
  if (mobile) await expectNoPageOverflow(page);

  // A deep link chooses its docket, even one past the first page.
  await page.goto(`${rt.web.origin}/app/ip?docket=${encodeURIComponent(oldest.id)}&tab=documents`);
  await expect(page.getByLabel("Linked docket", { exact: true })).toHaveValue(oldest.id);
  await markPositive(info, mobile ? "adj18-linked-docket-mobile" : "adj18-linked-docket", {
    local: rt.local, total: first.total_count, firstPage: first.dockets.length, oldestOnFirstPage: first.dockets.some((row) => row.id === oldest.id),
  });
}

/** Local only: one profile and one matching journal entry, so the lists are not empty. */
async function seedLocalWatch(rt: TesterRuntime, request: APIRequestContext) {
  expect(rt.local, "Seeding is for a fresh local tenant only").toBe(true);
  const title = stamp("B4 ADJ WATCH");
  const docket = await json<Docket>(await request.post(`${rt.api.origin}/api/ip/dockets`, {
    headers: rt.headers, data: { title, restricted: false, particulars: particulars(title) },
  }), "Local watch docket", 201);
  await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles`, {
    headers: rt.headers,
    data: { docket_id: docket.id, name: "ADJLISTS word watch", word_terms: ["ADJLISTS"], frequency: "publication",
      recipient_membership_ids: [rt.actor.membership.id] },
  }), "Local watch profile", 201);
  await json(await request.post(`${rt.api.origin}/api/ip/watch/journal-ingestions`, {
    headers: rt.headers,
    data: {
      idempotency_key: `adj-lists-${Date.now()}`, provider_key: "ipindia-journal-manual", external_call: false, cost_minor: 0, currency: "INR",
      publications: [{
        application_id: null, journal_number: "2190", journal_date: "2026-10-27", publication_kind: "advertisement",
        application_number: `ADJ-${Date.now()}`, mark_text: "ADJLISTS", device_reference: null, proprietor_name: null,
        office: "IP India", jurisdiction: "IN", class_numbers: [9], goods_services: { "9": ["Software"] },
        publication_scope: { scope_kind: "full" }, source_url: "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
        source_page: "12", source_status: "available", source_retrieved_at: null, parser_version: "manual-journal-v1",
        attribution: { publisher: "IP India", capture_method: "manual" },
        raw_evidence: { extract_text: "Journal 2190 page 12: ADJLISTS, class 9.", capture_method: "manual" },
        supersedes_publication_id: null, correction_reason: null,
      }],
    },
  }), "Local journal entry", 201);
}

function watchCount(loaded: number, total: number, noun: [string, string]): string {
  const word = total === 1 ? noun[0] : noun[1];
  return loaded < total ? `Showing ${count(loaded)} of ${count(total)} ${word}.` : `${count(total)} ${word}.`;
}

async function watchJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  if (rt.local) await seedLocalWatch(rt, request);
  const read = apiRead(page, rt, "/api/ip/watch", (url) => url.searchParams.get("offset") === "0");
  await page.goto(`${rt.web.origin}/app/ip/watch`);
  const body = await uiJson<WatchPage>(read, "Watch workspace first page");
  for (const total of [body.profile_total, body.hit_total, body.publication_total]) {
    expect(Number.isInteger(total), "Every watch list states its total").toBe(true);
  }
  expect(body.hits.length).toBeLessThanOrEqual(Math.min(body.limit, body.hit_total));
  expect(body.profiles.length).toBeLessThanOrEqual(Math.min(body.limit, body.profile_total));
  if (rt.local) expect([body.profile_total, body.hit_total, body.publication_total]).toEqual([1, 1, 1]);

  // Each list's count is the server total; an empty list shows no count and
  // says it is empty. Both answers are asserted; markPositive records which ran.
  const hits = page.getByTestId("watch-count-hits");
  await (body.hit_total
    ? expect(hits).toContainText(watchCount(body.hits.length, body.hit_total, ["hit", "hits"]))
    : expect(page.getByText("No watch hits", { exact: true })).toBeVisible());
  await expect(hits).toHaveCount(body.hit_total ? 1 : 0);

  await page.getByRole("button", { name: "Profiles", exact: true }).click();
  const profiles = page.getByTestId("watch-count-watch-profiles");
  await (body.profile_total
    ? expect(profiles).toContainText(watchCount(body.profiles.length, body.profile_total, ["watch profile", "watch profiles"]))
    : expect(page.getByText("No watch profiles", { exact: true })).toBeVisible());
  await expect(profiles).toHaveCount(body.profile_total ? 1 : 0);

  await page.getByRole("button", { name: "Journal intake", exact: true }).click();
  const entries = page.getByTestId("watch-count-recorded-entries");
  await (body.publication_total
    ? expect(entries).toContainText(watchCount(
      Math.min(body.publications.length, body.publication_total), body.publication_total, ["recorded entry", "recorded entries"]))
    : expect(page.getByText(/No journal entry is recorded yet/)).toBeVisible());
  await expect(entries).toHaveCount(body.publication_total ? 1 : 0);
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj05-watch-mobile" : "adj05-watch", {
    local: rt.local, profiles: body.profile_total, hits: body.hit_total, entries: body.publication_total,
  });
}

async function matterListsJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  if (rt.local) await seedLocalMatters(rt, request);
  const all = await everyMatter(rt, request);
  expect(all.length, "The tester must see at least one Matter").toBeGreaterThan(0);
  const oldest = all[all.length - 1];

  // Drafting hub: server search reaches the oldest Matter; the count is honest.
  const firstRead = apiRead(page, rt, "/api/matters/",
    (url) => url.searchParams.get("limit") === String(PICKER_PAGE) && !url.searchParams.has("q") && !url.searchParams.has("cursor"));
  await page.goto(`${rt.web.origin}/app/drafting`);
  const first = await uiJson<MatterPage>(firstRead, "Drafting hub first page");
  if (rt.local) expect(first.next_cursor, "Locally there are more Matters than one page").not.toBeNull();
  const hubCount = page.getByTestId("drafting-hub-count");
  await expect(hubCount).toHaveText(first.next_cursor
    ? `Showing the ${first.matters.length} most recently updated matters. Search, or load more.`
    : `${first.matters.length} ${first.matters.length === 1 ? "matter" : "matters"}.`);
  const searched = apiRead(page, rt, "/api/matters/", (url) => url.searchParams.get("q") === oldest.matter_code);
  await page.getByLabel("Search matters", { exact: true }).fill(oldest.matter_code);
  const found = await uiJson<MatterPage>(searched, "Drafting hub search");
  expect(found.matters.map((row) => row.id)).toContain(oldest.id);
  const open = page.getByTestId(`drafting-hub-open-${oldest.matter_code}`);
  await expectOnScreen(open, "The oldest Matter is listed on screen");
  await expect(open).toHaveAttribute("href", `/app/matters/${oldest.id}/drafts`);
  if (mobile) await expectNoPageOverflow(page);

  // Portfolio: counted on the server over every visible Matter.
  const healthRead = apiRead(page, rt, "/api/matters/portfolio-health", () => true);
  await page.goto(`${rt.web.origin}/app/portfolio`);
  const health = await uiJson<{ total_visible_count: number }>(healthRead, "Portfolio health");
  expect(health.total_visible_count, "The portfolio counts every visible Matter").toBe(all.length);
  const total = page.getByText("Total matters", { exact: true }).locator("xpath=..");
  await expect(total).toContainText(health.total_visible_count.toLocaleString());
  await expectOnScreen(total, "The total is on screen");
  if (mobile) await expectNoPageOverflow(page);

  // Notice register: the Matter filter searches every visible Matter.
  await page.goto(`${rt.web.origin}/app/notices`);
  const filter = page.getByLabel("Filter by matter", { exact: true });
  await expect(filter).toHaveValue("");
  await expect(filter.locator("option:checked")).toHaveText("All matters");
  const filterSearch = apiRead(page, rt, "/api/matters/", (url) => url.searchParams.get("q") === oldest.matter_code);
  await page.getByLabel("Find a matter to filter by", { exact: true }).fill(oldest.matter_code);
  await uiJson<MatterPage>(filterSearch, "Notice matter filter search");
  await expect(filter.locator(`option[value="${oldest.id}"]`)).toHaveCount(1);
  const filtered = apiRead(page, rt, "/api/notices/", (url) => url.searchParams.get("matter_id") === oldest.id);
  await filter.selectOption(oldest.id);
  await uiJson(filtered, "Notice register filtered by the oldest Matter");
  if (mobile) await expectNoPageOverflow(page);

  // Matter timeline: the count says whether more events exist.
  const timelineRead = apiRead(page, rt, `/api/matters/${oldest.id}/timeline`, (url) => !url.searchParams.has("cursor"));
  await page.goto(`${rt.web.origin}/app/matters/${oldest.id}/timeline`);
  const timeline = await uiJson<{ items: unknown[]; next_cursor?: string | null }>(timelineRead, "Matter timeline first page");
  const timelineCount = page.getByTestId("timeline-count");
  await (timeline.items.length
    ? expect(timelineCount).toHaveText(timeline.next_cursor
      ? `Showing the first ${timeline.items.length} events in this order. More events exist.`
      : `${timeline.items.length} ${timeline.items.length === 1 ? "event" : "events"}.`)
    : expect(page.getByText("No timeline events", { exact: true })).toBeVisible());
  await markPositive(info, mobile ? "adj03-matter-lists-mobile" : "adj03-matter-lists", {
    local: rt.local, matters: all.length, firstPage: first.matters.length, timelineEvents: timeline.items.length,
  });
}

test("B4-ADJ-18 Documents Linked docket reaches the oldest visible docket by server search, states its total and never picks one", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  try { await linkedDocketJourney(page, request, rt, info, false); } finally { await rt.release(); }
});

test("[mobile] B4-ADJ-18 Documents Linked docket works at 393px without horizontal scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  try { await linkedDocketJourney(page, request, rt, info, true); } finally { await rt.release(); }
});

test("B4-ADJ-05 journal watch states each list's server total", async ({ page, request, baseURL }, info) => {
  test.setTimeout(5 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  try { await watchJourney(page, request, rt, info, false); } finally { await rt.release(); }
});

test("[mobile] B4-ADJ-05 journal watch counts fit at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(5 * 60_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  try { await watchJourney(page, request, rt, info, true); } finally { await rt.release(); }
});

test("B4-ADJ-03 B4-ADJ-15 drafting, portfolio, notice filter and timeline reach every visible Matter", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  try { await matterListsJourney(page, request, rt, info, false); } finally { await rt.release(); }
});

test("[mobile] B4-ADJ-03 B4-ADJ-15 matter lists work at 393px without horizontal scroll", async ({ page, request, baseURL }, info) => {
  test.setTimeout(6 * 60_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  try { await matterListsJourney(page, request, rt, info, true); } finally { await rt.release(); }
});
