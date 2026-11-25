/**
 * Tester workbook "Caseops Bugs (1).xlsx" dated 24 Nov 2026, six rows.
 *
 * Rows 1-3 were reported by the Nova Legal Associates tester (nova-legal),
 * rows 4-6 by the Test Legal LLP tester (test-legal). Each journey signs in as
 * that tester through the sign-in page and drives the reported screen. API
 * calls below are oracles only (what the server says the page must show) and,
 * on a loopback stack, the seeding of an empty local database.
 *
 * Production runs need CASEOPS_EXPECTED_RELEASE_SHA and the testers'
 * credentials in CASEOPS_RAM_PROD_* / CASEOPS_NOVA_PROD_* (never committed).
 * Missing setup fails; nothing here skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const REPORTED_COUNSEL_MATTER = "142d194a-2484-4d8c-b42b-1ff788e5d459";
const REPORTED_NEXT_ACTION_MATTER = "43352e31-164e-4f7f-8082-d595c0c866cd";
const PAGE = 50;
const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);

type Tester = "ram" | "nova";
type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. UI journeys never use them to act as the user. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};
type MatterRow = { id: string; matter_code: string; title: string; client_name: string | null; status: string };
type MatterPage = { matters: MatterRow[]; next_cursor: string | null; total_count: number | null };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

function localCredentials(tester: Tester): TesterCredentials {
  const prefix = tester === "ram" ? "CASEOPS_RAM_LOCAL" : "CASEOPS_NOVA_LOCAL";
  const slug = process.env[`${prefix}_SLUG`]?.trim();
  const email = process.env[`${prefix}_EMAIL`]?.trim();
  const password = process.env[`${prefix}_PASSWORD`]?.trim();
  if (slug && email && password) return { slug, email, password };
  return { slug: `nov24-${tester}-${randomUUID()}`, email: `${tester}-${randomUUID()}@example.com`,
    password: `Synthetic!${randomUUID()}` };
}

async function runtimeFor(tester: Tester, baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
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
  const credentials: TesterCredentials = local ? localCredentials(tester) : tester === "ram"
    ? { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: required("CASEOPS_RAM_PROD_PASSWORD") }
    : { slug: process.env.CASEOPS_NOVA_PROD_SLUG?.trim() || "nova-legal", email: required("CASEOPS_NOVA_PROD_EMAIL"),
      password: required("CASEOPS_NOVA_PROD_PASSWORD") };
  if (!local && credentials.slug !== (tester === "ram" ? "test-legal" : "nova-legal")) {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: tester === "ram" ? "Test Legal LLP" : "Nova Legal Associates", company_slug: credentials.slug,
      company_type: "law_firm", owner_full_name: tester === "ram" ? "Ram Gupta" : "Riya Gupta",
      owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` }, release };
}

async function listPage(request: APIRequestContext, rt: Runtime, params: Record<string, string>): Promise<MatterPage> {
  const query = new URLSearchParams({ limit: String(PAGE), include_total: "true", ...params });
  return json<MatterPage>(await request.get(`${rt.api.origin}/api/matters/?${query}`, { headers: rt.headers }),
    "Matter list oracle");
}

async function oraclePages(request: APIRequestContext, rt: Runtime, count: number) {
  const pages: MatterPage[] = [];
  let cursor: string | null = null;
  for (let index = 0; index < count; index += 1) {
    const page = await listPage(request, rt, cursor ? { cursor } : {});
    pages.push(page);
    cursor = page.next_cursor;
    if (!cursor) break;
  }
  return pages;
}

async function createMatter(request: APIRequestContext, rt: Runtime, data: Record<string, unknown>) {
  if (!rt.local) throw new Error("API matter creation is local seeding only.");
  return json<MatterRow>(await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
    practice_area: "Commercial Litigation", forum_level: "high_court", status: "intake", ...data,
  } }), "Local seed matter");
}

/** Local only: the reported tenant holds more than three pages of matters. */
async function seedLocalPortfolio(request: APIRequestContext, rt: Runtime) {
  const total = (await listPage(request, rt, {})).total_count ?? 0;
  for (let index = total; index < 175; index += 1) {
    const n = String(index + 1).padStart(3, "0");
    await createMatter(request, rt, { matter_code: `NOV24-${n}`, title: `Recovery suit ${n} v. Respondent ${n}`,
      client_name: `Client Holdings ${n}` });
  }
}

async function visibleCodes(table: Locator): Promise<string[]> {
  return table.locator("tbody tr td:first-child").allInnerTexts();
}

async function openWorkspace(page: Page, rt: Runtime, path: string) {
  await signIn(page, { web: rt.web }, rt.credentials);
  await page.goto(`${rt.web.origin}${path}`);
}

// Row 1 (nova-legal): the Workspace label, firm name and avatar sit at the
// header's right edge, label above name, avatar beside them.
for (const width of [1920, 1536, 1365, 1024]) {
  test(`row 1 header workspace group is at the right edge at ${width}px`, async ({ page, request, baseURL }) => {
    const rt = await runtimeFor("nova", baseURL, request);
    await page.setViewportSize({ width, height: 900 });
    await openWorkspace(page, rt, "/app");
    const header = page.locator("header").filter({ has: page.getByLabel("Open user menu") });
    const group = header.getByTestId("topbar-workspace");
    const label = group.getByText("Workspace", { exact: true });
    const avatar = group.getByLabel("Open user menu");
    await expect(label).toBeVisible();
    const [h, g, l, a] = await Promise.all([header, group, label, avatar].map((item) => item.boundingBox()));
    if (!h || !g || !l || !a) throw new Error("Header geometry unavailable");
    const padRight = await header.evaluate((node) => parseFloat(getComputedStyle(node).paddingRight));
    expect(Math.abs(h.x + h.width - padRight - (g.x + g.width)), "Group ends at the header's right padding").toBeLessThanOrEqual(1);
    expect(a.x, "Avatar is to the right of the workspace text").toBeGreaterThan(l.x + l.width - 1);
    const name = group.getByTestId("topbar-workspace-name");
    const n = await name.boundingBox();
    if (!n) throw new Error("Firm name geometry unavailable");
    expect(n.y, "Firm name is stacked below the Workspace label").toBeGreaterThanOrEqual(l.y + l.height - 1);
    expect(Math.abs(n.x + n.width - (l.x + l.width)), "Label and firm name are right-aligned").toBeLessThanOrEqual(1);
    const search = header.getByRole("search");
    const s = await search.boundingBox();
    if (!s) throw new Error("Search geometry unavailable");
    expect(g.x, "Workspace group no longer sits against the search box").toBeGreaterThan(s.x + s.width + 8);
    await rt.release();
  });
}

test("[mobile] row 1 header avatar stays at the right edge on a phone", async ({ page, request, baseURL }) => {
  const rt = await runtimeFor("nova", baseURL, request);
  await page.setViewportSize({ width: 393, height: 851 });
  await openWorkspace(page, rt, "/app");
  const header = page.locator("header").filter({ has: page.getByLabel("Open user menu") });
  const [h, a] = await Promise.all([header.boundingBox(), header.getByLabel("Open user menu").boundingBox()]);
  if (!h || !a) throw new Error("Header geometry unavailable");
  const padRight = await header.evaluate((node) => parseFloat(getComputedStyle(node).paddingRight));
  expect(Math.abs(h.x + h.width - padRight - (a.x + a.width))).toBeLessThanOrEqual(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

// Row 2 (nova-legal): Today task/deadline and the Next action "Open" button go
// to the exact item. The journey creates its own task and deadline through the
// Tasks page and retires both (Complete) at the end.
test("row 2 Today and Next action open the exact task and deadline", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor("nova", baseURL, request);
  await page.setViewportSize({ width: 1365, height: 900 });
  let matterId = process.env.CASEOPS_NOVA_NEXT_ACTION_MATTER_ID?.trim() || REPORTED_NEXT_ACTION_MATTER;
  if (rt.local) {
    matterId = (await createMatter(request, rt, { matter_code: `NOV24-NA-${randomUUID().slice(0, 8)}`,
      title: "Next action journey" })).id;
  }
  const today = (await json<{ today: string }>(await request.get(`${rt.api.origin}/api/me/today`,
    { headers: rt.headers }), "Today oracle")).today;
  const taskTitle = stamp("Nov24 open task");
  const deadlineTitle = stamp("Nov24 open deadline");
  await openWorkspace(page, rt, `/app/matters/${matterId}/tasks`);

  // Each created item is retired on its own, even when a later step fails.
  const created: { kind: "task" | "deadline"; id: string }[] = [];
  try {
    const taskForm = page.locator("form").filter({ has: page.getByLabel("Task", { exact: true }) });
    await taskForm.getByLabel("Task", { exact: true }).fill(taskTitle);
    await taskForm.getByLabel("Due").fill(today);
    const createdTask = page.waitForResponse((r) => r.request().method() === "POST" && /\/tasks$/.test(new URL(r.url()).pathname));
    await taskForm.getByRole("button", { name: /Add/ }).click();
    const task = await json<{ id: string }>(await createdTask, "Create task through the Tasks page");
    created.push({ kind: "task", id: task.id });
    const deadlineForm = page.locator("form").filter({ has: page.getByLabel("Deadline", { exact: true }) });
    await deadlineForm.getByLabel("Deadline", { exact: true }).fill(deadlineTitle);
    await deadlineForm.getByLabel("Due").fill(today);
    const createdDeadline = page.waitForResponse((r) => r.request().method() === "POST" && /\/deadlines$/.test(new URL(r.url()).pathname));
    await deadlineForm.getByRole("button", { name: /Add/ }).click();
    const deadline = await json<{ id: string }>(await createdDeadline, "Create deadline through the Tasks page");
    created.push({ kind: "deadline", id: deadline.id });

    // Today -> task.
    await page.goto(`${rt.web.origin}/app/today`);
    const taskLink = page.getByTestId(`today-task-${task.id}`).getByRole("link");
    await expect(taskLink).toBeVisible();
    await taskLink.click();
    await expect(page).toHaveURL(new RegExp(`/app/matters/${matterId}/tasks\\?task=${task.id}$`));
    const taskRow = page.getByTestId(`matter-task-${task.id}`);
    await expect(taskRow).toHaveAttribute("aria-current", "true");
    await expect(taskRow).toBeFocused();
    await expect(taskRow).toContainText(taskTitle);
    await expect(taskRow).toBeInViewport();

    // Today -> deadline.
    await page.goto(`${rt.web.origin}/app/today`);
    const deadlineLink = page.getByTestId(`today-deadline-${deadline.id}`).getByRole("link");
    await expect(deadlineLink).toBeVisible();
    await deadlineLink.click();
    await expect(page).toHaveURL(new RegExp(`/app/matters/${matterId}/tasks\\?deadline=${deadline.id}$`));
    const deadlineRow = page.getByTestId(`matter-deadline-${deadline.id}`);
    await expect(deadlineRow).toHaveAttribute("aria-current", "true");
    await expect(deadlineRow).toBeFocused();
    await expect(deadlineRow).toContainText(deadlineTitle);

    // Overview -> Next action -> Open. The card shows the matter's most urgent
    // item, which may be an older overdue item rather than this run's.
    await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
    const card = page.getByTestId("matter-next-action");
    await expect(card).toBeVisible();
    const open = card.getByTestId("matter-next-action-go");
    const href = (await open.getAttribute("href")) ?? "";
    expect(href, "Open goes to the item's own page, never the overview it is shown on").toMatch(
      new RegExp(`^/app/matters/${matterId}/(?:tasks\\?(?:task|deadline)=[0-9a-f-]{36}$|hearings$|billing$|drafts/[0-9a-f-]{36}$)`),
    );
    const label = (await card.locator("p").nth(1).innerText()).trim();
    await open.click();
    await expect(page).toHaveURL(`${rt.web.origin}${href}`);
    if (href.includes("/tasks?")) {
      const focused = page.locator('[aria-current="true"][id^="task-"], [aria-current="true"][id^="deadline-"]');
      await expect(focused).toHaveCount(1);
      await expect(focused).toBeFocused();
      await expect(focused).toContainText(label);
      await expect(focused).toBeInViewport();
    }
  } finally {
    // Retire what this run created, through the page, each independently.
    const failures: string[] = [];
    if (created.length) await page.goto(`${rt.web.origin}/app/matters/${matterId}/tasks`).catch(() => undefined);
    for (const item of created) {
      try {
        const row = page.getByTestId(`matter-${item.kind}-${item.id}`);
        await row.getByRole("button", { name: "Complete" }).click();
        await expect(row.getByRole("button", { name: "Reopen" })).toBeVisible();
      } catch (error) {
        failures.push(`${item.kind} ${item.id}: ${(error as Error).message.split("\n")[0]}`);
      }
    }
    if (failures.length) throw new Error(`Could not retire created items: ${failures.join("; ")}`);
  }
  await rt.release();
});

// Row 3 (nova-legal): every sidebar group expands and collapses its pages.
for (const phone of [false, true]) {
  test(`${phone ? "[mobile] " : ""}row 3 sidebar groups expand and collapse`, async ({ page, request, baseURL }) => {
    const rt = await runtimeFor("nova", baseURL, request);
    await page.setViewportSize(phone ? { width: 393, height: 851 } : { width: 1365, height: 900 });
    await openWorkspace(page, rt, "/app");
    await page.evaluate(() => window.localStorage.removeItem("caseops.sidebar.collapsed-groups"));
    await page.reload();
    if (phone) await page.getByTestId("mobile-nav-trigger").click();
    const nav = phone ? page.getByRole("dialog") : page.getByRole("complementary", { name: "Primary navigation" });
    const toggles = nav.locator('[data-testid^="sidebar-group-"]');
    const count = await toggles.count();
    expect(count, "Every visible group has a disclosure").toBeGreaterThanOrEqual(4);
    const overview = nav.getByTestId("sidebar-group-overview");
    const overviewList = nav.locator(`#${await overview.getAttribute("aria-controls")}`);
    await expect(overviewList.getByRole("link")).toHaveText(["Home", "Today"]);
    for (let index = 0; index < count; index += 1) {
      const toggle = toggles.nth(index);
      const list = nav.locator(`#${await toggle.getAttribute("aria-controls")}`);
      const links = await list.getByRole("link").count();
      expect(links, "A group lists at least one page").toBeGreaterThan(0);
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "false");
      await expect(list).toBeHidden();
      await toggle.click();
      await expect(toggle).toHaveAttribute("aria-expanded", "true");
      await expect(list.getByRole("link")).toHaveCount(links);
    }
    if (!phone) {
      await nav.getByTestId("sidebar-group-schedule").click();
      await page.reload();
      await expect(nav.getByTestId("sidebar-group-schedule")).toHaveAttribute("aria-expanded", "false");
      await page.goto(`${rt.web.origin}/app/hearings`);
      await expect(nav.getByTestId("sidebar-group-schedule")).toHaveAttribute("aria-expanded", "true");
      await expect(nav.getByRole("link", { name: "Hearings" })).toHaveAttribute("aria-current", "page");
      await page.evaluate(() => window.localStorage.removeItem("caseops.sidebar.collapsed-groups"));
    }
  });
}

// Row 4 (test-legal): Next fetches the following 50 matters itself.
test("row 4 Next reaches page four without Load more", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor("ram", baseURL, request);
  if (rt.local) await seedLocalPortfolio(request, rt);
  const oracle = await oraclePages(request, rt, 4);
  const total = oracle[0].total_count ?? 0;
  expect(total, "The reported tenant holds more than three pages").toBeGreaterThan(3 * PAGE);
  await page.setViewportSize({ width: 1365, height: 900 });
  await openWorkspace(page, rt, "/app/matters");
  const table = page.getByRole("table");
  await expect(page.getByTestId("data-table-range")).toHaveText(`1-${PAGE} of ${total}`);
  await expect(page.getByRole("button", { name: /load more/i })).toHaveCount(0);
  const seen = new Set<string>();
  for (let index = 0; index < 4; index += 1) {
    if (index > 0) await page.getByRole("button", { name: "Next page" }).click();
    const from = index * PAGE + 1;
    const to = Math.min((index + 1) * PAGE, total);
    await expect(page.getByTestId("data-table-range")).toHaveText(`${from}-${to} of ${total}`);
    await expect(page.getByTestId("data-table-page")).toHaveText(`Page ${index + 1} of ${Math.ceil(total / PAGE)}`);
    const codes = await visibleCodes(table);
    // Re-read the oracle now: test-legal is a live tenant and edits reorder pages.
    const fresh = (await oraclePages(request, rt, index + 1))[index];
    expect(codes, `Page ${index + 1} shows the server's page ${index + 1}`).toEqual(fresh.matters.map((m) => m.matter_code));
    for (const code of codes) {
      expect(seen.has(code), `${code} appears once`).toBe(false);
      seen.add(code);
    }
  }
  await page.getByRole("button", { name: "Previous page" }).click();
  await expect(page.getByTestId("data-table-range")).toHaveText(`${2 * PAGE + 1}-${3 * PAGE} of ${total}`);
  await rt.release();
});

// Row 5 (test-legal): search reaches matters on pages nobody has opened.
for (const field of ["title", "code", "client"] as const) {
  test(`row 5 search by ${field} finds a matter on an unloaded page`, async ({ page, request, baseURL }) => {
    test.setTimeout(240_000);
    const rt = await runtimeFor("ram", baseURL, request);
    if (rt.local) await seedLocalPortfolio(request, rt);
    const oracle = await oraclePages(request, rt, 4);
    const deep = oracle.at(-1)!.matters.find((m) => (field !== "client" || m.client_name?.trim()));
    if (!deep) throw new Error("No matter on the last oracle page carries the searched field.");
    const needle = field === "title" ? deep.title : field === "code" ? deep.matter_code : deep.client_name!;
    const expected = await listPage(request, rt, { q: needle });
    await page.setViewportSize({ width: 1365, height: 900 });
    await openWorkspace(page, rt, "/app/matters");
    const table = page.getByRole("table");
    await expect(page.getByTestId("data-table-range")).toContainText(`1-${PAGE} of`);
    expect(await visibleCodes(table)).not.toContain(deep.matter_code);
    await page.getByRole("searchbox", { name: "Search all rows" }).fill(needle);
    const count = expected.total_count ?? 0;
    await expect(page.getByTestId("data-table-range")).toHaveText(`1-${Math.min(count, PAGE)} of ${count}`);
    expect(await visibleCodes(table)).toEqual(expected.matters.map((m) => m.matter_code));
    expect(await visibleCodes(table)).toContain(deep.matter_code);
    await expect(page.getByText("Nothing to show yet.")).toHaveCount(0);
    await rt.release();
  });
}

// Row 6 (test-legal): Suggested Counsel cards share one width and height in a
// row at each browser zoom level. Zoom is emulated as the CSS viewport width
// the zoomed window would have (screen width / zoom).
test("row 6 Suggested Counsel cards align at 80-150% zoom", async ({ page, request, baseURL }) => {
  test.setTimeout(240_000);
  const rt = await runtimeFor("ram", baseURL, request);
  let matterId = process.env.CASEOPS_RAM_COUNSEL_MATTER_ID?.trim() || REPORTED_COUNSEL_MATTER;
  if (rt.local) {
    const matter = await createMatter(request, rt, { matter_code: `NOV24-OC-${randomUUID().slice(0, 8)}`,
      title: "Counsel layout journey" });
    matterId = matter.id;
    for (const name of ["Rao & Associates", "Chandrasekharan International Commercial Litigation Counsel",
      "Mehta Law", "Iyer Kapoor Partners LLP", "Saxena & Saxena Advocates"]) {
      await json(await request.post(`${rt.api.origin}/api/outside-counsel/profiles`, { headers: rt.headers,
        data: { name: `${name} ${randomUUID().slice(0, 4)}`, panel_status: "preferred",
          practice_areas: ["Commercial Litigation"] } }), "Local counsel profile");
    }
  }
  const results = (await json<{ results: unknown[] }>(await request.post(`${rt.api.origin}/api/outside-counsel/recommendations`,
    { headers: rt.headers, data: { matter_id: matterId, limit: 5 } }), "Counsel oracle")).results.length;
  expect(results, "The reported matter shows several counsel").toBeGreaterThanOrEqual(2);
  await page.setViewportSize({ width: 1366, height: 900 });
  await openWorkspace(page, rt, `/app/matters/${matterId}`);
  const cards = page.getByTestId("counsel-recommendation");
  await expect(cards).toHaveCount(results);
  for (const screen of [1366, 1920]) {
    for (const zoom of [0.8, 0.9, 1, 1.1, 1.25, 1.5]) {
      const width = Math.round(screen / zoom);
      await page.setViewportSize({ width, height: 900 });
      const boxes = (await Promise.all((await cards.all()).map((card) => card.boundingBox()))).map((box) => {
        if (!box) throw new Error("Card geometry unavailable");
        return box;
      });
      const rows = new Map<number, typeof boxes>();
      for (const box of boxes) {
        const key = [...rows.keys()].find((top) => Math.abs(top - box.y) <= 2) ?? box.y;
        rows.set(key, [...(rows.get(key) ?? []), box]);
      }
      const at = `${screen}px screen at ${Math.round(zoom * 100)}%`;
      if (width >= 1024) {
        // Root cause of row 6: the card sat in a one-third overview column.
        const [card, overview] = await page.getByTestId("counsel-recommendations-card").evaluate((node) =>
          [node.getBoundingClientRect().width, node.parentElement!.getBoundingClientRect().width]);
        expect(card, `Suggested Counsel spans the overview, ${at}`).toBeGreaterThan(overview - 2);
      }
      const widths = boxes.map((box) => box.width);
      expect(Math.max(...widths) - Math.min(...widths), `Equal card widths, ${at}`).toBeLessThanOrEqual(1);
      // Cards are top-aligned (not stretched), so equal heights here mean equal content.
      const heights = boxes.map((box) => box.height);
      expect(Math.max(...heights) - Math.min(...heights), `Equal card heights, ${at}`).toBeLessThanOrEqual(1);
      const scoreTops = await page.getByTestId("counsel-score-row").evaluateAll((nodes) =>
        nodes.map((node) => node.getBoundingClientRect().top));
      for (const [top, row] of rows) {
        const inRow = boxes.map((box, i) => [box, scoreTops[i]] as const).filter(([box]) => row.includes(box));
        const tops = inRow.map(([, t]) => t);
        expect(Math.max(...tops) - Math.min(...tops), `Score and status line up across the row at y=${Math.round(top)}, ${at}`).toBeLessThanOrEqual(1);
      }
      const perRow = [...rows.values()].map((row) => row.length);
      expect(perRow.slice(0, -1).every((n) => n === perRow[0]), `Full rows before the last, ${at}`).toBe(true);
      if (width >= 1366) expect(perRow[0], `One horizontal row at ${at}`).toBe(Math.min(results, 5));
      if (width >= 900) expect(perRow[0], `Side by side at ${at}`).toBeGreaterThanOrEqual(Math.min(results, 2));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `No page overflow, ${at}`).toBe(true);
      for (const card of await cards.all()) {
        expect(await card.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), `Card content fits, ${at}`).toBe(true);
      }
    }
  }
  // Opening one card shows its details and full name without stretching the others.
  await page.setViewportSize({ width: 1366, height: 900 });
  const before = await cards.nth(1).boundingBox();
  await cards.first().locator("summary").click();
  await expect(cards.first().locator("details")).toHaveAttribute("open", "");
  const after = await cards.nth(1).boundingBox();
  expect(Math.abs((after?.height ?? 0) - (before?.height ?? -10)), "Neighbour height unchanged").toBeLessThanOrEqual(1);
  await cards.first().locator("summary").click();
  await rt.release();
});
