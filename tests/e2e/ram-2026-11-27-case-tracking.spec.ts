/**
 * Tester workbook dated 27 Nov 2026, Case Tracking Bookmarks (/app/case-tracking).
 *
 * Row 6: "Search option by Matter Code is not available in Case Tracking
 * Bookmarks. Users have to scroll the whole list to find e.g. MTR-2026-200."
 * Expected: a search field in Bookmarks; entering a Matter Code filters the
 * bookmarked cases to matches without manual scrolling.
 *
 * Row 10: "Delete action button does not display tooltip on hover in
 * Bookmarks." Expected: a tooltip such as "Delete bookmark" on hover and an
 * accessible label; delete functionality unchanged.
 *
 * The rows were reported in nova-legal. By owner decision every production run
 * signs in as the test-legal tester (CASEOPS_RAM_PROD_SLUG / _EMAIL /
 * _PASSWORD, never committed) and is read-only there: it finds an existing
 * Matter-linked bookmark (preferring one past the first page) through the API
 * oracle and fails, never skips, when there is none. When every such bookmark
 * sits on the first page it records a "caveat" annotation instead of
 * claiming the page-boundary half of row 6.
 * On a loopback stack the spec bootstraps its own workspace and seeds more
 * bookmarks than two pages with the searched one sorted last. Deleting a
 * bookmark is exercised only locally ([local-only]).
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const PAGE = 50;
const LOCAL_BOOKMARKS = 120;
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. UI journeys never use them to act as the user. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};
type Bookmark = {
  id: string;
  matter_code: string | null;
  name: string | null;
  tracked_case: { case_title: string; cnr_number: string | null; case_number: string | null };
};
type BookmarkPage = { bookmarks: Bookmark[]; next_cursor: string | null; total_count: number | null };
type Target = { bookmark: Bookmark; needle: string; beyondFirstPage: boolean };

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
  return { slug: `nov27-ram-${randomUUID()}`, email: `ram-${randomUUID()}@example.com`,
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
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` }, release };
}

async function bookmarkPage(request: APIRequestContext, rt: Runtime, params: Record<string, string>) {
  const query = new URLSearchParams({ limit: String(PAGE), include_total: "true", ...params });
  return json<BookmarkPage>(await request.get(`${rt.api.origin}/api/case-tracking/bookmarks?${query}`,
    { headers: rt.headers }), "Bookmark list oracle");
}

async function allBookmarkPages(request: APIRequestContext, rt: Runtime): Promise<BookmarkPage[]> {
  const pages: BookmarkPage[] = [];
  let cursor: string | null = null;
  do {
    const page = await bookmarkPage(request, rt, cursor ? { cursor, include_total: "false" } : {});
    pages.push(page);
    cursor = page.next_cursor;
  } while (cursor && pages.length < 40);
  return pages;
}

/**
 * Local only: one bookmark linked to a Matter (auto-linked when the Matter is
 * created with its CNR), then more than two pages of newer bookmarks, so the
 * linked one sorts last.
 */
async function seedLocalBookmarks(request: APIRequestContext, rt: Runtime): Promise<string> {
  if (!rt.local) throw new Error("API seeding is local only.");
  const serial = stamp("NOV27").replace(/\D/g, "").slice(-12);
  const matterCode = `MTR-2026-${serial}`;
  const matter = await json<{ id: string }>(await request.post(`${rt.api.origin}/api/matters/`, {
    headers: rt.headers,
    data: {
      title: `Saraswati Exports ${serial} v Union of India`, matter_code: matterCode,
      practice_area: "Commercial Litigation", forum_level: "high_court", status: "active",
      court_name: "Delhi High Court", client_name: "Saraswati Exports", opposing_party: "Union of India",
      cnr_number: `DLHC01${serial.slice(-6)}2026`,
    },
  }), "Local seed matter");
  const linked = await bookmarkPage(request, rt, { q: matterCode });
  if (!linked.bookmarks.some((bookmark) => bookmark.matter_code === matterCode)) {
    throw new Error(`Creating Matter ${matter.id} did not auto-link a case tracking bookmark; local seed is unusable.`);
  }
  const existing = (await bookmarkPage(request, rt, {})).total_count ?? 0;
  for (let index = existing; index <= LOCAL_BOOKMARKS; index += 1) {
    const n = String(index).padStart(4, "0");
    await json(await request.post(`${rt.api.origin}/api/case-tracking/bookmarks`, { headers: rt.headers, data: {
      provider: "ecourtsindia", cnr_number: `MHHC01${serial.slice(-4)}${n}26`, case_number: `COMAP ${n}/2026`,
      case_title: `Routine Petitioner ${n} v State`, party_names: [`Routine Petitioner ${n}`, "State"],
    } }), "Local seed bookmark", 201);
  }
  return matterCode;
}

/** A bookmark the first page does not show, preferring one with a visible Matter code. */
async function deepTarget(request: APIRequestContext, rt: Runtime): Promise<Target> {
  const pages = await allBookmarkPages(request, rt);
  const all = pages.flatMap((page) => page.bookmarks);
  if (!all.length) {
    throw new Error("The tester has no case tracking bookmarks, so the Bookmarks search cannot be exercised. "
      + "Bookmark a case in this workspace before the release run.");
  }
  const firstPage = new Set(pages[0].bookmarks.map((bookmark) => bookmark.id));
  const ordered = [...all.filter((b) => !firstPage.has(b.id)).reverse(), ...[...pages[0].bookmarks].reverse()];
  // Row 6 is about Matter Code search: a CNR or title stand-in would prove something else.
  const coded = ordered.find((bookmark) => bookmark.matter_code);
  if (!coded) {
    throw new Error(`None of the tester's ${all.length} bookmarks is linked to a Matter visible to them, `
      + "so Matter Code search cannot be exercised. Link a bookmark to a Matter in this workspace.");
  }
  return { bookmark: coded, needle: coded.matter_code!, beyondFirstPage: !firstPage.has(coded.id) };
}

/** The painted tooltip, not only its screen-reader copy, is on screen. */
async function expectTooltipShown(page: Page, label: string) {
  const content = page.locator("[data-radix-popper-content-wrapper] > div").filter({ hasText: label });
  await expect(content).toHaveCount(1);
  await expect(content).toBeVisible();
  const box = await content.boundingBox();
  expect(box !== null && box.width > 40 && box.height > 12, "tooltip is painted at a readable size").toBe(true);
}

async function openTracking(page: Page, rt: Runtime, search = "") {
  await page.setViewportSize({ width: 1365, height: 900 });
  await signIn(page, { web: rt.web }, rt.credentials);
  await page.goto(`${rt.web.origin}/app/case-tracking${search}`);
  await expect(page.getByTestId("case-tracking-bookmarks")).toBeVisible();
}

test("row 6 bookmark search finds a Matter Code on an unloaded page", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  const seededCode = rt.local ? await seedLocalBookmarks(request, rt) : null;
  const target = await deepTarget(request, rt);
  if (rt.local) expect(target.needle, "the seeded Matter-linked bookmark is the deep target").toBe(seededCode);
  if (!target.beyondFirstPage) {
    // Not a skip: every assertion below still runs. The page-boundary half of
    // row 6 is then proven only by the local run, and the evidence says so.
    info.annotations.push({ type: "caveat", description: "The tester's Matter-linked bookmarks all sit on "
      + "the first page, so this run cannot show a match from an unloaded page." });
  }
  const first = await bookmarkPage(request, rt, {});
  const total = first.total_count ?? 0;
  const expected = await bookmarkPage(request, rt, { q: target.needle });
  expect(expected.bookmarks.map((bookmark) => bookmark.id), "the server search finds the target").toContain(target.bookmark.id);

  await openTracking(page, rt);
  const bookmarks = page.getByTestId("case-tracking-bookmarks");
  const count = page.getByTestId("case-tracking-bookmark-count");
  await expect(count).toHaveText(`Showing ${Math.min(PAGE, total)} of ${total} ${total === 1 ? "bookmark" : "bookmarks"}.`);
  if (rt.local) expect(target.beyondFirstPage, "the local seed puts the target past two page boundaries").toBe(true);
  if (target.beyondFirstPage) {
    await expect(bookmarks.getByTestId(`case-tracking-bookmark-${target.bookmark.id}`), "target starts off-page").toHaveCount(0);
  }

  await bookmarks.getByRole("searchbox", { name: "Search bookmarks" }).fill(target.needle);
  const matches = expected.total_count ?? 0;
  await expect(count).toHaveText(
    `${matches} ${matches === 1 ? "bookmark matches" : "bookmarks match"} "${target.needle}". Showing ${expected.bookmarks.length}.`,
  );
  const row = bookmarks.getByTestId(`case-tracking-bookmark-${target.bookmark.id}`);
  await expect(row).toBeVisible();
  await expect(row.getByTestId("case-tracking-bookmark-matter-code")).toHaveText(target.needle);
  const list = bookmarks.getByTestId("case-tracking-bookmark-list");
  await expect(list.getByTestId("case-tracking-bookmark-delete")).toHaveCount(expected.bookmarks.length);
  await expect.poll(() => new URL(page.url()).searchParams.get("bookmarkSearch")).toBe(target.needle);

  // The search survives a reload.
  await page.reload();
  await expect(bookmarks.getByRole("searchbox", { name: "Search bookmarks" })).toHaveValue(target.needle);
  await expect(bookmarks.getByTestId(`case-tracking-bookmark-${target.bookmark.id}`)).toBeVisible();

  // An unmatched search says so and Clear returns to the full list.
  const missing = `NOMATCH-${randomUUID().slice(0, 8)}`;
  await bookmarks.getByRole("searchbox", { name: "Search bookmarks" }).fill(missing);
  await expect(bookmarks.getByTestId("case-tracking-bookmark-search-empty")).toContainText(`No bookmarks match "${missing}".`);
  await bookmarks.getByTestId("case-tracking-bookmark-search-empty").getByRole("button", { name: "Clear search" }).click();
  await expect(count).toHaveText(`Showing ${Math.min(PAGE, total)} of ${total} ${total === 1 ? "bookmark" : "bookmarks"}.`);
  await rt.release();
});

test("row 10 delete bookmark icon shows its tooltip on hover and keyboard focus", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor(baseURL, request);
  if (rt.local) await seedLocalBookmarks(request, rt);
  const target = await deepTarget(request, rt);
  await openTracking(page, rt, `?bookmarkSearch=${encodeURIComponent(target.needle)}`);
  const row = page.getByTestId(`case-tracking-bookmark-${target.bookmark.id}`);
  await expect(row).toBeVisible();

  const remove = row.getByRole("button", { name: "Delete bookmark", exact: true });
  await expect(remove).toHaveAccessibleName("Delete bookmark");
  await expect(remove).not.toHaveAttribute("title", /./);
  await remove.hover();
  const tooltip = page.getByRole("tooltip", { name: "Delete bookmark" });
  await expect(tooltip).toBeAttached();
  await expectTooltipShown(page, "Delete bookmark");
  // A real pointer leaves through several moves; Radix closes once the pointer is
  // outside the trigger-to-tooltip grace area.
  await page.mouse.move(10, 10, { steps: 10 });
  await page.mouse.move(20, 20, { steps: 2 });
  await expect(tooltip).toHaveCount(0);

  // Keyboard: Tab from the notification toggle lands on delete and shows the tooltip.
  await row.getByRole("button", { name: /^(Disable|Enable) notifications$/ }).focus();
  await page.keyboard.press("Tab");
  await expect(remove).toBeFocused();
  await expectTooltipShown(page, "Delete bookmark");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("tooltip", { name: "Delete bookmark" })).toHaveCount(0);

  // Never clicked: production stays read-only and the bookmark is still active.
  const still = await bookmarkPage(request, rt, { q: target.needle });
  expect(still.bookmarks.map((bookmark) => bookmark.id)).toContain(target.bookmark.id);
  await rt.release();
});

test("[local-only] row 10 delete bookmark still deletes the bookmark", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor(baseURL, request);
  if (!rt.local) throw new Error("Deleting a bookmark is exercised only on a loopback stack.");
  const code = await seedLocalBookmarks(request, rt);
  const target = await deepTarget(request, rt);
  expect(target.needle).toBe(code);
  await openTracking(page, rt, `?bookmarkSearch=${encodeURIComponent(code)}`);
  const row = page.getByTestId(`case-tracking-bookmark-${target.bookmark.id}`);
  await expect(row).toBeVisible();
  const archived = page.waitForResponse((response) => response.request().method() === "PATCH"
    && new URL(response.url()).pathname === `/api/case-tracking/bookmarks/${target.bookmark.id}`);
  await row.getByRole("button", { name: "Delete bookmark", exact: true }).click();
  expect((await archived).status()).toBe(200);
  await expect(row).toHaveCount(0);
  await expect(page.getByTestId("case-tracking-bookmark-search-empty")).toContainText(`No bookmarks match "${code}".`);
  const after = await bookmarkPage(request, rt, { q: code });
  expect(after.bookmarks.map((bookmark) => bookmark.id)).not.toContain(target.bookmark.id);
});
