import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";
import { noPaidProviderHeaders } from "./support/cost-controls";

type Matter = { id: string; status: string; updated_at: string; court_name: string;
  matter_code: string; title: string;
  forum_catalog_entry_id: string; forum_district: string | null; forum_city: string | null };
type HearingSource = {
  id: string; matter_id: string; hearing_on: string; purpose: string;
  time_status: "exact" | "session"; hearing_time: string | null;
  session_label: string | null; timezone: string;
};
type Event = {
  id: string; kind: string; occurs_on: string; matter_id: string; title: string;
  matter_code: string; matter_title: string;
  court_label: string | null; court_identity: string | null;
  forum_display_order: number | null; hearing_time: string | null;
  time_status: string | null; session_label: string | null; timezone: string | null;
};
type Forum = { id: string; forum_type: string; forum_level: string; name: string;
  district: string | null; display_order: number };

const web = process.env.PROD_BASE_URL ?? process.env.CASEOPS_WEB_BASE_URL ?? "http://127.0.0.1:3100";
const isLoopback = (value: string) => ["localhost", "127.0.0.1", "[::1]"].includes(new URL(value).hostname);
const webLocal = isLoopback(web);
const origin = process.env.PROD_API_BASE_URL ?? (webLocal
  ? `http://127.0.0.1:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}` : "https://api.caseops.ai");
const apiLocal = isLoopback(origin);
if ([web, origin].some(value => new URL(value).username || new URL(value).password)) {
  throw new Error("Credential-bearing acceptance origins are prohibited");
}
if (webLocal !== apiLocal) throw new Error("Mixed local/remote acceptance targets are prohibited");
const local = webLocal && apiLocal;
if (!local && (new URL(web).origin !== "https://caseops.ai" || new URL(origin).origin !== "https://api.caseops.ai")) {
  throw new Error("Production acceptance must use the authorized CaseOps origins");
}
const slug = process.env.CASEOPS_RAM_PROD_SLUG ?? "test-legal";
const email = process.env.CASEOPS_RAM_PROD_EMAIL ?? "ram@testfirm.com";
const password = process.env.CASEOPS_RAM_PROD_PASSWORD ?? process.env.CASEOPS_RAM_LOCAL_PASSWORD
  ?? (local ? "CalendarOct13Local!" : "");
const run = `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
const now = new Date();
const day = (n: number) => `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${n}`;
const dates = [day(15), day(16)];
const sessionDate = day(17);
let api: APIRequestContext;
let auth: Record<string, string>;
const matters: Matter[] = [];
const expectedCourt = new Map<string, { label: string; identity: string; order: number }>();
const expectedHearings = new Map<string, HearingSource>();

async function status(response: { status(): number; text(): Promise<string> }, value: number) {
  expect(response.status(), response.status() === value ? "" : await response.text()).toBe(value);
}

async function signIn(page: Page) {
  await page.goto(`${web}/sign-in`);
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(password);
  const signed = page.waitForResponse(r => new URL(r.url()).pathname === "/api/auth/login" && r.request().method() === "POST");
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await status(await signed, 200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

function sourceTimeLabel(source: HearingSource): string {
  return source.time_status === "exact"
    ? `${source.hearing_time!.slice(0, 5)} ${source.timezone}` : source.session_label!;
}

async function selectDay(page: Page, target: string) {
  const tab = page.getByRole("tab", { name: /^day$/i });
  await tab.click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  const currentPane = page.locator('[data-testid^="calendar-day-pane-"]');
  await expect(currentPane).toHaveCount(1);
  const current = (await currentPane.getAttribute("data-testid"))?.replace("calendar-day-pane-", "");
  expect(current).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  const currentTime = Date.parse(`${current}T00:00:00Z`);
  const difference = (Date.parse(`${target}T00:00:00Z`) - currentTime) / 86_400_000;
  expect(Number.isInteger(difference)).toBe(true);
  expect(Math.abs(difference), "Date navigation is bounded, not a request retry").toBeLessThanOrEqual(62);
  const direction = Math.sign(difference);
  for (let step = 1; step <= Math.abs(difference); step++) {
    await page.getByRole("button", { name: direction > 0 ? "Next" : "Previous", exact: true }).click();
    const expectedDate = new Date(currentTime + step * direction * 86_400_000).toISOString().slice(0, 10);
    await expect(page.getByTestId(`calendar-day-pane-${expectedDate}`)).toBeVisible();
  }
  const selected = page.getByTestId(`calendar-day-pane-${target}`);
  await expect(selected).toBeVisible();
  const date = new Date(`${target}T00:00:00Z`);
  const weekday = new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "UTC" }).format(date);
  const month = new Intl.DateTimeFormat("en-US", { month: "long", timeZone: "UTC" }).format(date);
  await expect(page.getByTestId("calendar-month-label"))
    .toHaveText(`${weekday}, ${date.getUTCDate()} ${month} ${date.getUTCFullYear()}`);
  return selected;
}

test.describe.serial("October 13 court Calendar acceptance", () => {
  test.beforeAll(async () => {
    expect(password, "Authorized test password must be supplied in production").not.toBe("");
    if (!local) expect(slug, "Production mutation is test-legal only").toBe("test-legal");
    api = await request.newContext({ extraHTTPHeaders: noPaidProviderHeaders });
    const sha = local ? process.env.CASEOPS_RELEASE_SHA : process.env.CASEOPS_EXPECTED_RELEASE_SHA;
    expect(sha, "Exact accepted/serving SHA required").toMatch(/^[a-f0-9]{40}$/);
    for (const endpoint of [`${origin}/api/build`, `${web}/api/release-identity`]) {
      const identity = await api.get(endpoint);
      await status(identity, 200);
      expect((await identity.json()).release_sha).toBe(sha);
    }
    let login = await api.post(`${origin}/api/auth/login`, { data: { company_slug: slug, email, password } });
    if (local && login.status() === 401) {
      const created = await api.post(`${origin}/api/bootstrap/company`, { data: {
        company_name: "Local Calendar Acceptance", company_slug: slug, company_type: "law_firm",
        owner_full_name: "Calendar Acceptance", owner_email: email, owner_password: password,
      } });
      await status(created, 200);
      login = await api.post(`${origin}/api/auth/login`, { data: { company_slug: slug, email, password } });
    }
    await status(login, 200);
    auth = { ...noPaidProviderHeaders, Authorization: `Bearer ${(await login.json()).access_token}` };
    const catalog = await api.get(`${origin}/api/courts/forum-catalog`, { headers: auth });
    await status(catalog, 200);
    const entries = (await catalog.json()).entries as Forum[];
    const forums = ["supreme_court", "high_court", "district_court", "consumer_forum"]
      .map(kind => entries.find(entry => entry.forum_type === kind));
    expect(forums.every(Boolean), "Real configured SC/HC/DC/other catalog rows required").toBe(true);
    for (const [index, forum] of forums.entries()) {
      const saved = await api.post(`${origin}/api/matters/`, { headers: auth, data: {
        matter_code: `CAL13-${run}-${index}`, title: `Calendar court ${index} ${run}`,
        practice_area: "Civil", forum_level: forum!.forum_level, forum_catalog_entry_id: forum!.id,
      } });
      await status(saved, 200);
      const matter = await saved.json() as Matter;
      matters.push(matter);
      expect(matter.forum_catalog_entry_id).toBe(forum!.id);
      expect(matter.court_name).toBe(forum!.name);
      expect(matter.forum_district).toBe(forum!.district);
      const prefixes: Readonly<Record<string, string | undefined>> = {
        supreme_court: "SC", high_court: "HC", district_court: "DC",
      };
      const prefix = prefixes[forum!.forum_type];
      const parts = [forum!.forum_type === "district_court" ? matter.forum_district : null, matter.court_name]
        .filter((part): part is string => Boolean(part));
      const label = `${prefix ? `${prefix} - ` : ""}${[...new Set(parts)].join(", ")}`;
      const identity = [...new Set([...parts, matter.forum_city].filter((part): part is string => Boolean(part)))].join(", ");
      expectedCourt.set(matter.id, { label, identity, order: forum!.display_order });
      for (const date of dates) {
        // Reverse insertion proves time order, not accidental creation order.
        for (const time of ["10:30:00", "09:30:00"]) {
          const purpose = `Next hearing ${run} ${index} ${date} ${time}`;
          const hearing = await api.post(`${origin}/api/matters/${matter.id}/hearings`, { headers: auth, data: {
            hearing_on: date, forum_name: forum!.name, purpose,
            time_status: "exact", hearing_time: time, timezone: "Asia/Kolkata",
          } });
          await status(hearing, 200);
          const stored = await hearing.json() as HearingSource;
          const source: HearingSource = {
            id: stored.id, matter_id: matter.id, hearing_on: date, purpose,
            time_status: "exact", hearing_time: time, session_label: null, timezone: "Asia/Kolkata",
          };
          expect(stored.id).toBeTruthy();
          expect(stored).toMatchObject(source);
          expectedHearings.set(`hearing:${stored.id}`, source);
        }
      }
      if (index === 0) {
        const hearing = await api.post(`${origin}/api/matters/${matter.id}/hearings`, { headers: auth, data: {
          hearing_on: sessionDate, forum_name: forum!.name, purpose: `Session hearing ${run}`,
          time_status: "session", session_label: `Afternoon session ${run}`, timezone: "Asia/Kolkata",
        } });
        await status(hearing, 200);
        const stored = await hearing.json() as HearingSource;
        const source: HearingSource = {
          id: stored.id, matter_id: matter.id, hearing_on: sessionDate, purpose: `Session hearing ${run}`,
          time_status: "session", hearing_time: null,
          session_label: `Afternoon session ${run}`, timezone: "Asia/Kolkata",
        };
        expect(stored.id).toBeTruthy();
        expect(stored).toMatchObject(source);
        expectedHearings.set(`hearing:${stored.id}`, source);
      }
    }
    expect(expectedHearings.size).toBe(17);
    for (const matter of matters) {
      const response = await api.get(`${origin}/api/matters/${matter.id}/workspace`, { headers: auth });
      await status(response, 200);
      const workspace = await response.json() as { matter: Matter; hearings: HearingSource[] };
      expect(workspace.matter).toMatchObject({ id: matter.id, matter_code: matter.matter_code, title: matter.title });
      const expected = [...expectedHearings.values()].filter(source => source.matter_id === matter.id);
      expect(workspace.hearings.map(hearing => hearing.id).sort()).toEqual(expected.map(source => source.id).sort());
      for (const source of expected) {
        expect(workspace.hearings.find(hearing => hearing.id === source.id)).toMatchObject(source);
      }
    }
  });

  test.afterAll(async () => {
    if (!api) return;
    for (const matter of matters) {
      const current = await api.get(`${origin}/api/matters/${matter.id}`, { headers: auth });
      await status(current, 200);
      const row = await current.json() as Matter;
      if (row.status !== "disposed") {
        await status(await api.patch(`${origin}/api/matters/${row.id}/lifecycle/status`, { headers: auth, data: {
          to_status: "disposed", expected_from_status: row.status, expected_updated_at: row.updated_at,
          reason: "Complete isolated October 13 Calendar acceptance fixture",
        } }), 200);
      }
    }
    await api.dispose();
  });

  for (const width of [1280, 393]) {
    test(`saved court identities and every hidden event remain reachable at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.setExtraHTTPHeaders(noPaidProviderHeaders);
      const response = await api.get(`${origin}/api/calendar/events`, { headers: auth, params: { from: dates[0], to: dates[1] } });
      await status(response, 200);
      const events = (await response.json()).events as Event[];
      const owned = events.filter(e => matters.some(m => m.id === e.matter_id));
      expect(owned).toHaveLength(16);
      for (const event of owned) {
        const expected = expectedCourt.get(event.matter_id)!;
        expect(event.court_label).toBe(expected.label);
        expect(event.court_identity).toBe(expected.identity);
        expect(event.forum_display_order).toBe(expected.order);
      }
      for (const date of dates) {
        const hearings = owned.filter(e => e.occurs_on === date);
        expect(hearings.map(e => e.forum_display_order)).toEqual(
          hearings.map(e => e.forum_display_order).sort((a, b) => a! - b!),
        );
        for (const matter of matters) {
          expect(hearings.filter(e => e.matter_id === matter.id).map(e => e.hearing_time))
            .toEqual(["09:30:00", "10:30:00"]);
        }
      }
      await signIn(page);
      await page.goto(`${web}/app/calendar`);
      for (const date of dates) {
        const expected = events.filter(e => e.occurs_on === date);
        const cell = page.getByTestId(`calendar-month-day-${date}`);
        await expect(cell.locator('[data-testid^="calendar-event-"]')).toHaveCount(3);
        expect(await cell.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes => nodes.map(n => n.getAttribute("data-testid"))))
          .toEqual(expected.slice(0, 3).map(e => `calendar-event-${e.id}`));
        const dayTrigger = cell.getByRole("button", { name: `View all events on ${date}` });
        await dayTrigger.click();
        const allDialog = page.getByRole("dialog", { name: `Events on ${date}`, exact: true });
        await expect(allDialog.getByRole("heading", { name: `Events on ${date}`, exact: true })).toBeVisible();
        await expect(allDialog.getByRole("link")).toHaveCount(expected.length);
        expect(await allDialog.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes =>
          nodes.map(node => node.getAttribute("data-testid"))))
          .toEqual(expected.map(event => `calendar-event-${event.id}`));
        for (const event of expected.filter(e => expectedCourt.has(e.matter_id))) {
          const link = allDialog.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toContainText(expectedCourt.get(event.matter_id)!.identity);
        }
        await allDialog.getByRole("button", { name: "Close", exact: true }).click();
        // Radix restores focus after unmount; finish that lifecycle before moving it.
        await expect(allDialog).toHaveCount(0);
        await expect(dayTrigger).toBeFocused();
        const trigger = cell.getByRole("button", { name: `Show ${expected.length - 3} more events on ${date}` });
        await expect(trigger).toBeVisible();
        await trigger.focus();
        await expect(trigger).toBeFocused();
        await page.keyboard.press("Enter");
        const dialog = page.getByRole("dialog", { name: `More events on ${date}`, exact: true });
        await expect(dialog).toBeVisible();
        await expect(dialog.getByRole("heading", { name: `More events on ${date}`, exact: true })).toBeVisible();
        await expect(dialog.getByRole("link")).toHaveCount(expected.length - 3);
        expect(await dialog.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes => nodes.map(n => n.getAttribute("data-testid"))))
          .toEqual(expected.slice(3).map(e => `calendar-event-${e.id}`));
        for (const event of expected.slice(3).filter(e => owned.some(own => own.id === e.id))) {
          const link = dialog.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toContainText(event.court_label!);
          await expect(link).toContainText(event.court_identity!);
          await expect(link).toHaveAttribute("href", `/app/matters/${event.matter_id}/hearings`);
        }
        await page.keyboard.press("Escape");
        await expect(dialog).toBeHidden();
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
        await trigger.click();
        await expect(dialog).toBeVisible();
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
        await expect(dialog).toHaveCount(0);
        await expect(trigger).toBeFocused();
        const selected = expected.slice(3).find(event => expectedHearings.has(event.id));
        expect(selected, "An owned overflow hearing must be followed, not only href-checked").toBeDefined();
        const source = expectedHearings.get(selected!.id)!;
        const matter = matters.find(row => row.id === source.matter_id)!;
        await trigger.click();
        const workspaceResponse = page.waitForResponse(response =>
          new URL(response.url()).pathname === `/api/matters/${matter.id}/workspace`
          && response.request().method() === "GET");
        await dialog.getByTestId(`calendar-event-${selected!.id}`).click();
        const loaded = await workspaceResponse;
        await status(loaded, 200);
        const workspace = await loaded.json() as { matter: Matter; hearings: HearingSource[] };
        expect(workspace.matter).toMatchObject({ id: matter.id, matter_code: matter.matter_code, title: matter.title });
        expect(workspace.hearings.find(hearing => hearing.id === source.id)).toMatchObject(source);
        await expect(page).toHaveURL(`${web}/app/matters/${matter.id}/hearings`);
        await expect(page.getByRole("heading", { name: matter.title, exact: true })).toBeVisible();
        await expect(page.getByText(matter.matter_code, { exact: true })).toBeVisible();
        const hearingRow = page.getByRole("listitem").filter({ has: page.getByText(source.purpose, { exact: true }) });
        await expect(hearingRow).toHaveCount(1);
        await expect(hearingRow.getByText(source.purpose, { exact: true })).toBeVisible();
        const displayedDate = await page.evaluate(value => {
          const [year, month, day] = value.split("-").map(Number);
          return new Date(year, month - 1, day).toLocaleDateString(undefined,
            { day: "2-digit", month: "short", year: "numeric" });
        }, source.hearing_on);
        await expect(hearingRow).toContainText(displayedDate);
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        await page.goto(`${web}/app/calendar`);
        await expect(page.getByTestId(`calendar-month-day-${date}`)).toBeVisible();
      }
      await page.reload();
      await expect(page.getByTestId(`calendar-month-day-${dates[0]}`).getByRole("button", { name: `View all events on ${dates[0]}` })).toBeVisible();
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      // These controls must still work and Google connection state remains readable.
      await expect(page.getByTestId("calendar-google-panel")).toBeVisible();
      const persisted = await api.get(`${origin}/api/calendar/events`, {
        headers: auth, params: { from: dates[0], to: sessionDate },
      });
      await status(persisted, 200);
      const viewEvents = (await persisted.json()).events as Event[];
      const fixtureEvents = viewEvents.filter(event => matters.some(matter => matter.id === event.matter_id));
      expect(fixtureEvents.map(event => event.id).sort()).toEqual([...expectedHearings.keys()].sort());
      for (const event of fixtureEvents) {
        const source = expectedHearings.get(event.id)!;
        const matter = matters.find(matter => matter.id === source.matter_id)!;
        expect(event).toMatchObject({
          kind: "hearing", occurs_on: source.hearing_on, matter_id: source.matter_id,
          title: source.purpose, matter_code: matter.matter_code, matter_title: matter.title,
          court_label: expectedCourt.get(matter.id)!.label,
          court_identity: expectedCourt.get(matter.id)!.identity,
          hearing_time: source.hearing_time, time_status: source.time_status,
          session_label: source.session_label, timezone: source.timezone,
        });
      }
      for (const date of [...dates, sessionDate]) {
        const expected = viewEvents.filter(event => event.occurs_on === date);
        const dayPane = await selectDay(page, date);
        await expect(dayPane.locator('[data-testid^="calendar-event-"]')).toHaveCount(expected.length);
        expect(await dayPane.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes =>
          nodes.map(node => node.getAttribute("data-testid"))))
          .toEqual(expected.map(event => `calendar-event-${event.id}`));
        for (const event of expected.filter(event => expectedHearings.has(event.id))) {
          const source = expectedHearings.get(event.id)!;
          const matter = matters.find(matter => matter.id === source.matter_id)!;
          const court = expectedCourt.get(matter.id)!;
          const link = dayPane.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toBeVisible();
          await expect(link).toHaveAttribute("href", `/app/matters/${source.matter_id}/hearings`);
          await expect(link).toContainText(matter.matter_code);
          await expect(link).toContainText(matter.title);
          const sections = link.locator(":scope > div > div");
          await expect(sections).toHaveCount(2);
          await expect(sections.nth(0).getByText(court.label, { exact: true })).toBeVisible();
          await expect(sections.nth(1).getByText(court.identity, { exact: true })).toBeVisible();
          await expect(sections.nth(1).getByText(sourceTimeLabel(source), { exact: true })).toBeVisible();
        }
        const weekTab = page.getByRole("tab", { name: /^week$/i });
        await weekTab.click();
        await expect(weekTab).toHaveAttribute("aria-selected", "true");
        const weekDay = page.getByTestId(`calendar-week-day-${date}`);
        await expect(weekDay).toBeVisible();
        await expect(weekDay.locator('[data-testid^="calendar-event-"]')).toHaveCount(expected.length);
        expect(await weekDay.locator('[data-testid^="calendar-event-"]').evaluateAll(nodes =>
          nodes.map(node => node.getAttribute("data-testid"))))
          .toEqual(expected.map(event => `calendar-event-${event.id}`));
        for (const event of expected.filter(event => expectedHearings.has(event.id))) {
          const source = expectedHearings.get(event.id)!;
          const matter = matters.find(matter => matter.id === source.matter_id)!;
          const court = expectedCourt.get(matter.id)!;
          const link = weekDay.getByTestId(`calendar-event-${event.id}`);
          await expect(link).toBeVisible();
          await expect(link.getByText(court.label, { exact: true })).toBeVisible();
          await expect(link).toHaveAttribute("href", `/app/matters/${source.matter_id}/hearings`);
          // Compact week chips retain full timing/identity in title, not visible card text.
          await expect(link).toHaveAttribute("title", ["Hearing or listing", court.identity,
            matter.matter_code, matter.title, source.purpose, sourceTimeLabel(source)].join(" · "));
        }
      }
      await page.getByTestId("calendar-view-month").click();
      await expect(page.getByTestId("calendar-view-month")).toHaveAttribute("aria-selected", "true");
      await expect(page.getByTestId(`calendar-month-day-${sessionDate}`)).toBeVisible();
    });
  }
});
