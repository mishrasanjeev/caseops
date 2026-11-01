/**
 * Ram batch-4 adjacent defects, truncation class (EH-B4-02): lists that
 * stopped at their first page with no total and no way to the rest.
 *
 * - B4-ADJ-18: the Documents "Linked docket" field on /app/ip listed the IP
 *   home page's first 100 dockets and chose the first one itself.
 * - B4-ADJ-05: the journal watch workspace stopped at 250 rows with no total;
 *   locally the journey seeds more than one page and loads the next.
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
  ingestion_run_total: number; ingestion_run_limit: number; paused_profile_total: number;
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

/** Clicks Load more and holds the picker to the second page the server returned. */
async function loadNextDocketPage(page: Page, rt: TesterRuntime, first: DocketPage) {
  const nextRead = apiRead(page, rt, "/api/ip/dockets", (url) => url.searchParams.get("cursor") === first.next_cursor);
  await page.getByTestId("ip-docket-picker").getByRole("button", { name: "Load more", exact: true }).click();
  const next = await uiJson<DocketPage>(nextRead, "Linked docket picker next page");
  const linked = page.getByLabel("Linked docket", { exact: true });
  const loaded = first.dockets.length + next.dockets.length;
  // Every docket on the second page is now offered.
  for (const row of next.dockets) await expect(linked.locator(`option[value="${row.id}"]`)).toHaveCount(1);
  await expect(page.locator("#ip-document-docket-status > span").first()).toHaveText(next.has_more
    ? `Showing ${count(loaded)} of ${count(first.total_count)} dockets — refine your search or load more.`
    : `${count(first.total_count)} ${first.total_count === 1 ? "docket" : "dockets"}.`);
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
  const status = page.locator("#ip-document-docket-status > span").first();
  await expect(status).toHaveText(first.has_more
    ? `Showing ${count(first.dockets.length)} of ${count(first.total_count)} dockets — refine your search or load more.`
    : `${count(first.total_count)} ${first.total_count === 1 ? "docket" : "dockets"}.`);
  const oldestOption = linked.locator(`option[value="${oldest.id}"]`);
  await expect(oldestOption).toHaveCount(first.dockets.some((row) => row.id === oldest.id) ? 1 : 0);

  // Load more reads the next cursor page; a complete first page offers no button.
  const loadMore = page.getByTestId("ip-docket-picker").getByRole("button", { name: "Load more", exact: true });
  await (first.has_more ? loadNextDocketPage(page, rt, first) : expect(loadMore).toHaveCount(0));

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

const WATCH_PAGE = 100;
// Local seed: one more profile, hit and recorded entry than one watch page,
// and one more ingestion run than the runs list shows. One ingestion compares
// at most 100 active profiles and 2,500 profile/entry pairs, so the profiles
// are created in two batches and the first batch is paused before the second
// batch's capture (which also gives the paused count something to say).
const SEED_BATCH_A = 50;
const SEED_BATCH_B = WATCH_PAGE + 1 - SEED_BATCH_A;
const SEED_PROFILES = SEED_BATCH_A + SEED_BATCH_B;
const SEED_FILLER_RUNS = 19;
// Batch B's capture: 51 profiles x 49 entries stays within 2,500 pairs.
const SEED_BATCH_B_ENTRIES = 2500 / SEED_BATCH_A - 1;
const SEED_ENTRIES = SEED_BATCH_A + SEED_BATCH_B_ENTRIES + SEED_FILLER_RUNS * 3;

function journalEntry(mark: string, applicationNumber: string) {
  return {
    application_id: null, journal_number: "2190", journal_date: "2026-10-27", publication_kind: "advertisement",
    application_number: applicationNumber, mark_text: mark, device_reference: null, proprietor_name: null,
    office: "IP India", jurisdiction: "IN", class_numbers: [9], goods_services: { "9": ["Software"] },
    publication_scope: { scope_kind: "full" }, source_url: "https://search.ipindia.gov.in/IPOJournal/Journal/ViewJournal",
    source_page: "12", source_status: "available", source_retrieved_at: null, parser_version: "manual-journal-v1",
    attribution: { publisher: "IP India", capture_method: "manual" },
    raw_evidence: { extract_text: `Journal 2190 page 12: ${mark}, class 9.`, capture_method: "manual" },
    supersedes_publication_id: null, correction_reason: null,
  };
}

/**
 * Local only: more than one watch page of profiles, hits and recorded entries,
 * and more runs than the runs list shows. Every profile watches ADJLISTS and
 * one entry per batch carries it, so there is one hit per profile; the filler
 * entries ("QZ n") share no word, class or proprietor with any profile.
 */
async function seedLocalWatch(rt: TesterRuntime, request: APIRequestContext) {
  expect(rt.local, "Seeding is for a fresh local tenant only").toBe(true);
  // One docket per profile: a hit records a publication event on its docket,
  // and two profiles on one docket matching one entry would be a duplicate event.
  const createProfiles = async (from: number, total: number) => {
    const rows: { id: string; version: number }[] = [];
    for (let index = from; index < from + total; index += 1) {
      const title = stamp(`B4 ADJ WATCH ${index}`);
      const docket = await json<Docket>(await request.post(`${rt.api.origin}/api/ip/dockets`, {
        headers: rt.headers, data: { title, restricted: false, particulars: particulars(title) },
      }), `Local watch docket ${index}`, 201);
      rows.push(await json<{ id: string; version: number }>(await request.post(`${rt.api.origin}/api/ip/watch/profiles`, {
        headers: rt.headers,
        data: { docket_id: docket.id, name: `ADJLISTS word watch ${index}`, word_terms: ["ADJLISTS"], frequency: "publication",
          recipient_membership_ids: [rt.actor.membership.id] },
      }), `Local watch profile ${index}`, 201));
    }
    return rows;
  };
  const runKey = `adj-lists-${Date.now()}`;
  const ingest = async (key: string, publications: ReturnType<typeof journalEntry>[]) =>
    json(await request.post(`${rt.api.origin}/api/ip/watch/journal-ingestions`, {
      headers: rt.headers,
      data: { idempotency_key: key, provider_key: "ipindia-journal-manual", external_call: false, cost_minor: 0, currency: "INR", publications },
    }), `Local journal ingestion ${key}`, 201);
  const fillers = (prefix: string, length: number) =>
    Array.from({ length }, (_, index) => journalEntry(`QZ ${prefix} ${index}`, `${runKey}-${prefix}-${index}`));

  const batchA = await createProfiles(0, SEED_BATCH_A);
  await ingest(`${runKey}-match-a`, [journalEntry("ADJLISTS", `${runKey}-MA`), ...fillers("A", SEED_BATCH_A - 1)]);
  // The capture moves each profile's version; pause from the current one.
  const current = await json<{ profiles: { id: string; version: number }[] }>(await request.get(
    `${rt.api.origin}/api/ip/watch?limit=${WATCH_PAGE}&offset=0`, { headers: rt.headers }), "Watch profiles after batch one");
  const versions = new Map(current.profiles.map((row) => [row.id, row.version]));
  for (const profile of batchA) {
    expect(versions.has(profile.id), "Every first-batch profile is listed").toBe(true);
    await json(await request.post(`${rt.api.origin}/api/ip/watch/profiles/${profile.id}/status`, {
      headers: rt.headers, data: { expected_version: versions.get(profile.id), poll_status: "paused", reason: "Batch one is complete." },
    }), "Pause a first-batch watch profile");
  }
  await createProfiles(SEED_BATCH_A, SEED_BATCH_B);
  await ingest(`${runKey}-match-b`, [journalEntry("ADJLISTS", `${runKey}-MB`), ...fillers("B", SEED_BATCH_B_ENTRIES - 1)]);
  for (let run = 0; run < SEED_FILLER_RUNS; run += 1) await ingest(`${runKey}-filler-${run}`, fillers(`R${run}`, 3));
}

function watchCount(loaded: number, total: number, noun: [string, string]): string {
  const word = total === 1 ? noun[0] : noun[1];
  return loaded < total ? `Showing ${count(loaded)} of ${count(total)} ${word}.` : `${count(total)} ${word}.`;
}

/** Clicks Load more and holds every list to the second offset the server returned. */
async function loadNextWatchPage(page: Page, rt: TesterRuntime, first: WatchPage): Promise<WatchPage> {
  const nextRead = apiRead(page, rt, "/api/ip/watch", (url) => url.searchParams.get("offset") === String(first.limit));
  const button = page.getByRole("button", { name: "Load more hits", exact: true });
  await button.scrollIntoViewIfNeeded();
  await expectOnScreen(button, "Load more hits is on screen beside the review queue count");
  await button.click();
  const next = await uiJson<WatchPage>(nextRead, "Watch workspace second page");
  expect(next.offset).toBe(first.limit);
  expect([next.profile_total, next.hit_total, next.publication_total])
    .toEqual([first.profile_total, first.hit_total, first.publication_total]);
  return next;
}

async function watchJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  if (rt.local) await seedLocalWatch(rt, request);
  const read = apiRead(page, rt, "/api/ip/watch", (url) => url.searchParams.get("offset") === "0");
  await page.goto(`${rt.web.origin}/app/ip/watch`);
  const body = await uiJson<WatchPage>(read, "Watch workspace first page");
  for (const total of [body.profile_total, body.hit_total, body.publication_total, body.ingestion_run_total]) {
    expect(Number.isInteger(total), "Every watch list states its total").toBe(true);
  }
  expect(body.limit).toBe(WATCH_PAGE);
  expect(body.hits.length).toBeLessThanOrEqual(Math.min(body.limit, body.hit_total));
  expect(body.profiles.length).toBeLessThanOrEqual(Math.min(body.limit, body.profile_total));
  if (rt.local) {
    expect([body.profile_total, body.hit_total, body.publication_total, body.ingestion_run_total])
      .toEqual([SEED_PROFILES, SEED_PROFILES, SEED_ENTRIES, SEED_FILLER_RUNS + 2]);
    expect(body.paused_profile_total).toBe(SEED_BATCH_A);
    expect([body.profiles.length, body.hits.length], "Locally the first page is full").toEqual([WATCH_PAGE, WATCH_PAGE]);
  }

  // Each list's count is the server total; an empty list shows no count and
  // says it is empty. Both answers are asserted; markPositive records which ran.
  const hits = page.getByTestId("watch-count-hits");
  await (body.hit_total
    ? expect(hits).toContainText(watchCount(body.hits.length, body.hit_total, ["hit", "hits"]))
    : expect(page.getByText("No watch hits", { exact: true })).toBeVisible());
  await expect(hits).toHaveCount(body.hit_total ? 1 : 0);
  if (mobile) await expectNoPageOverflow(page);

  // Load more reads the next offset of every list; a complete page offers none.
  const crosses = body.hits.length < body.hit_total;
  const next = crosses ? await loadNextWatchPage(page, rt, body) : null;
  const unique = <T extends { id: string }>(rows: T[]) => new Set(rows.map((row) => row.id)).size;
  const loadedHits = unique([...body.hits, ...(next?.hits ?? [])]);
  const loadedProfiles = unique([...body.profiles, ...(next?.profiles ?? [])]);
  const loadedEntries = unique([...body.publications, ...(next?.publications ?? [])]);
  if (rt.local) expect([loadedHits, loadedProfiles, loadedEntries]).toEqual([SEED_PROFILES, SEED_PROFILES, SEED_ENTRIES]);
  await expect(page.getByRole("button", { name: "Load more hits", exact: true }))
    .toHaveCount(loadedHits < body.hit_total ? 1 : 0);
  await (body.hit_total
    ? expect(hits).toContainText(watchCount(loadedHits, body.hit_total, ["hit", "hits"]))
    : expect(hits).toHaveCount(0));
  if (mobile) await expectNoPageOverflow(page);

  await page.getByRole("button", { name: "Profiles", exact: true }).click();
  const profiles = page.getByTestId("watch-count-watch-profiles");
  await (body.profile_total
    ? expect(profiles).toContainText(watchCount(loadedProfiles, body.profile_total, ["watch profile", "watch profiles"]))
    : expect(page.getByText("No watch profiles", { exact: true })).toBeVisible());
  await expect(profiles).toHaveCount(body.profile_total ? 1 : 0);

  await page.getByRole("button", { name: "Journal intake", exact: true }).click();
  const entries = page.getByTestId("watch-count-recorded-entries");
  await (body.publication_total
    ? expect(entries).toContainText(watchCount(
      Math.min(loadedEntries, body.publication_total), body.publication_total, ["recorded entry", "recorded entries"]))
    : expect(page.getByText(/No journal entry is recorded yet/)).toBeVisible());
  await expect(entries).toHaveCount(body.publication_total ? 1 : 0);
  if (mobile) await expectNoPageOverflow(page);

  // Runs: the newest runs are listed and the cap names the server total.
  await page.getByRole("button", { name: "Runs", exact: true }).click();
  const runsCap = page.getByTestId("watch-runs-cap");
  const runsShown = Math.min(body.ingestion_run_total, body.ingestion_run_limit);
  await (body.ingestion_run_total > runsShown
    ? expect(runsCap).toHaveText(`The ${runsShown} most recent of ${count(body.ingestion_run_total)} runs are shown.`)
    : expect(runsCap).toHaveCount(0));
  const paused = page.getByText(/^\d+ profiles? paused$/);
  await (body.paused_profile_total
    ? expect(paused).toHaveText(`${body.paused_profile_total} ${body.paused_profile_total === 1 ? "profile" : "profiles"} paused`)
    : expect(paused).toHaveCount(0));
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj05-watch-mobile" : "adj05-watch", {
    local: rt.local, profiles: body.profile_total, hits: body.hit_total, entries: body.publication_total,
    runs: body.ingestion_run_total, paused: body.paused_profile_total, crossedPage: crosses,
  });
}

const FOLLOW_UP_PAGE = 50;
type FollowUpPage = {
  overdue_count: number; missing_date_count: number; offset: number; limit: number;
  missing_date_matters: MatterRow[]; truncated: boolean;
};

/** Loads the next page of the missing-date queue and holds the count to the server. */
async function followUpJourney(page: Page, rt: TesterRuntime, first: FollowUpPage, mobile: boolean) {
  const card = page.getByRole("heading", { name: `Missing hearing date (${first.missing_date_count})`, exact: true })
    .locator("xpath=ancestor::*[.//ul][1]");
  await expectOnScreen(card.getByRole("heading"), "The missing-date queue is on screen");
  expect(first.limit).toBe(FOLLOW_UP_PAGE);
  const loadMore = card.getByRole("button", { name: "Load more matters missing a date", exact: true });
  const status = card.getByRole("status");
  await expect(card.getByRole("link", { name: "open the matter list" })).toHaveCount(0);
  if (first.missing_date_matters.length >= first.missing_date_count) {
    await expect(loadMore).toHaveCount(0);
    await expect(status).toHaveCount(0);
    return;
  }
  await expect(status).toHaveText(`Showing ${first.missing_date_matters.length} of ${first.missing_date_count}.`);
  const nextRead = apiRead(page, rt, "/api/matters/hearing-follow-up",
    (url) => url.searchParams.get("queue") === "missing_date" && url.searchParams.get("offset") === String(first.missing_date_matters.length));
  await loadMore.click();
  const next = await uiJson<FollowUpPage>(nextRead, "Missing hearing date queue next page");
  expect(next.offset).toBe(first.missing_date_matters.length);
  const loaded = new Set([...first.missing_date_matters, ...next.missing_date_matters].map((row) => row.id)).size;
  for (const row of next.missing_date_matters) await expect(card.locator(`a[href="/app/matters/${row.id}/hearings"]`)).toHaveCount(1);
  await expect(status).toHaveCount(loaded < next.missing_date_count ? 1 : 0);
  await expect(loadMore).toHaveCount(loaded < next.missing_date_count ? 1 : 0);
  if (mobile) await expectNoPageOverflow(page);
}

/**
 * Notice form: a stamped notice linked to the oldest Matter. A search with no
 * server match says 0 and still lists the link apart. Retired afterwards by
 * clearing its links and closing it (notices have no delete).
 */
async function linkedNoticeJourney(page: Page, request: APIRequestContext, rt: TesterRuntime, oldest: MatterRow, mobile: boolean) {
  const subject = stamp("B4 ADJ LINKED NOTICE");
  const notice = await json<{ id: string }>(await request.post(`${rt.api.origin}/api/notices/`, {
    headers: rt.headers, data: { subject, matter_ids: [oldest.id] },
  }), "Stamped notice linked to the oldest Matter", 201);
  try {
    await page.goto(`${rt.web.origin}/app/notices`);
    const registerRead = apiRead(page, rt, "/api/notices/", (url) => url.searchParams.get("query") === subject);
    await page.locator("#notice-search").fill(subject);
    await uiJson(registerRead, "Notice register search for the stamped notice");
    await page.getByTestId(`notice-row-${notice.id}`).getByRole("button", { name: "Manage details & links" }).click();
    const dialog = page.getByTestId("create-notice-dialog");
    const linked = dialog.getByRole("group", { name: "Linked to this notice (1)", exact: true });
    const linkedBox = linked.getByRole("checkbox", { name: new RegExp(oldest.matter_code) });
    await expect(linkedBox).toBeChecked();
    const none = `NO SUCH ${stamp("MATTER")}`;
    const noneRead = apiRead(page, rt, "/api/matters/", (url) => url.searchParams.get("q") === none);
    await dialog.getByLabel("Search accessible matters", { exact: true }).fill(none);
    const empty = await uiJson<MatterPage>(noneRead, "Notice form Matter search with no match");
    expect(empty.matters).toEqual([]);
    await expect(dialog.getByText("No accessible matters match this search.", { exact: true })).toBeVisible();
    await expect(dialog.getByTestId("notice-matter-count")).toHaveText("0 matters match this search. 1 selected.");
    await linkedBox.scrollIntoViewIfNeeded();
    await expectOnScreen(linkedBox, "The linked Matter stays listed apart from the search");
    if (mobile) await expectNoPageOverflow(page);
    await page.keyboard.press("Escape");
  } finally {
    const current = await json<{ updated_at: string }>(await request.get(`${rt.api.origin}/api/notices/${notice.id}`,
      { headers: rt.headers }), "Stamped notice before retirement");
    await json(await request.patch(`${rt.api.origin}/api/notices/${notice.id}`, {
      headers: rt.headers, data: { expected_updated_at: current.updated_at, status: "Closed", matter_ids: [] },
    }), "Retire the stamped notice");
  }
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
  const health = await uiJson<{ total_visible_count: number; practice_area_counts: { key: string | null; count: number }[] }>(
    healthRead, "Portfolio health");
  expect(health.total_visible_count, "The portfolio counts every visible Matter").toBe(all.length);
  const total = page.getByText("Total matters", { exact: true }).locator("xpath=..");
  await expect(total).toContainText(health.total_visible_count.toLocaleString());
  await expectOnScreen(total, "The total is on screen");
  // Practice areas: one row per server value; no value reads "Unspecified", once.
  const areas = new Map<string, number>();
  for (const bucket of health.practice_area_counts) {
    const label = bucket.key && bucket.key.trim() ? bucket.key : "Unspecified";
    areas.set(label, (areas.get(label) ?? 0) + bucket.count);
  }
  const areaCard = page.getByRole("heading", { name: "By practice area", exact: true }).locator("xpath=ancestor::*[.//li][1]");
  const areaTotal = [...areas.values()].reduce((sum, value) => sum + value, 0);
  await expect(areaCard.locator("li")).toHaveText([...areas].map(([label, value]) =>
    `${label}${value.toLocaleString()} · ${(areaTotal ? (value / areaTotal) * 100 : 0).toFixed(0)}%`));
  if (mobile) await expectNoPageOverflow(page);

  // Hearing follow-up: each queue pages to its last Matter in place.
  const missingRead = apiRead(page, rt, "/api/matters/hearing-follow-up",
    (url) => url.searchParams.get("queue") === "missing_date" && !url.searchParams.has("offset"));
  await page.goto(`${rt.web.origin}/app/hearings`);
  const missing = await uiJson<FollowUpPage>(missingRead, "Missing hearing date queue first page");
  if (rt.local) expect(missing.missing_date_count, "Locally the queue is longer than one page").toBeGreaterThan(FOLLOW_UP_PAGE);
  await (missing.missing_date_count
    ? followUpJourney(page, rt, missing, mobile)
    : expect(page.getByRole("heading", { name: /^Missing hearing date/ })).toHaveCount(
      missing.overdue_count ? 1 : 0));

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
  await linkedNoticeJourney(page, request, rt, oldest, mobile);

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

test("B4-ADJ-05 journal watch states each list's server total and loads the next page", async ({ page, request, baseURL }, info) => {
  test.setTimeout(5 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  try { await watchJourney(page, request, rt, info, false); } finally { await rt.release(); }
});

test("[mobile] B4-ADJ-05 journal watch counts and Load more fit at 393px", async ({ page, request, baseURL }, info) => {
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

async function providerOperationsJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  type OperationsPage = { returned_count: number; has_more: boolean; operations: { id: string }[] };
  const jobs = (resolved: boolean) => apiRead(page, rt, "/api/admin/provider-operations/jobs",
    (url) => (url.searchParams.get("include_resolved") === "true") === resolved);
  const allRead = jobs(true);
  await page.goto(`${rt.web.origin}/app/admin/provider-operations`);
  const all = await uiJson<OperationsPage>(allRead, "Provider operations, all");
  const allButton = page.getByRole("button", { name: "All operations", exact: true });
  const openButton = page.getByRole("button", { name: "Needs action only", exact: true });
  await expectOnScreen(allButton, "The operations view choice is on screen");
  await expect(allButton).toHaveAttribute("aria-pressed", "true");
  const cap = page.getByTestId("provider-operations-cap");
  await (all.has_more
    ? expect(cap).toContainText(`cover the ${all.returned_count} most recently updated operations, including resolved and ignored ones`)
    : expect(cap).toHaveCount(0));
  await expect(cap.filter({ hasText: /Resolv/ })).toHaveCount(0);
  const openRead = jobs(false);
  await openButton.click();
  const open = await uiJson<OperationsPage>(openRead, "Provider operations, needs action");
  await expect(openButton).toHaveAttribute("aria-pressed", "true");
  await (open.has_more
    ? expect(cap).toContainText("Resolving or ignoring a listed operation removes it from this view and brings the next one in.")
    : expect(cap).toHaveCount(0));
  for (const row of open.operations) await expect(page.getByTestId(`provider-operation-${row.id}`)).toHaveCount(1);
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj15-provider-operations-mobile" : "adj15-provider-operations", {
    local: rt.local, all: all.returned_count, allCapped: all.has_more, open: open.returned_count, openCapped: open.has_more,
  });
}

test("B4-ADJ-15 provider operations offers a needs-action view and only true cap advice", async ({ page, request, baseURL }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, baseURL);
  try { await providerOperationsJourney(page, rt, info, false); } finally { await rt.release(); }
});

test("[mobile] B4-ADJ-15 provider operations view choice fits at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(4 * 60_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  try { await providerOperationsJourney(page, rt, info, true); } finally { await rt.release(); }
});
