/**
 * ENH-017 / US-064 / FT-097 / FT-098 (J08, M08): calendar Year view.
 *
 * Signed in as the reporting tester in their own tenant (test-legal in
 * production, a freshly bootstrapped tenant locally), Ram creates a matter, a
 * hearing and a task through the product UI, opens the calendar, chooses Year,
 * and must see the year straight away, then both items on their own days with
 * distinct, defined legend colours. The day counts must equal the server's
 * year summary for those dates, each quarterly export must be a real calendar,
 * a click must open the day in Day view, a reload must keep the Year view, and
 * the Week and Month views must keep every chip legible. The matter is disposed
 * afterwards, which retires both items.
 */
import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import {
  expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type Created = { hearingId: string; taskId: string };

const TRANSPARENT = /^(?:rgba\(0, 0, 0, 0\)|transparent)$/;

function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

/**
 * Hearing and task dates 40 and 47 days out, always inside one calendar year
 * so one Year view holds both. From 15 to 21 November the pair would straddle
 * 31 December, so both move to the first fortnight of the new year.
 */
function targetDates(today: Date): { year: number; hearingOn: string; taskOn: string } {
  const at = (offset: number) => new Date(today.getFullYear(), today.getMonth(), today.getDate() + offset);
  let hearing = at(40);
  let task = at(47);
  if (hearing.getFullYear() !== task.getFullYear()) {
    hearing = new Date(task.getFullYear(), 0, 4);
    task = new Date(task.getFullYear(), 0, 11);
  }
  return { year: hearing.getFullYear(), hearingOn: isoDay(hearing), taskOn: isoDay(task) };
}

async function createMatterThroughUi(page: Page, rt: TesterRuntime, title: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const matterDialog = page.getByRole("dialog");
  await matterDialog.getByLabel("Title").fill(title);
  await matterDialog.getByLabel("Matter code").fill(`YR-${rt.run.replace(/[^0-9A-Za-z]/g, "").slice(-14)}`);
  await matterDialog.getByLabel("Practice area").fill("Commercial");
  await matterDialog.getByLabel("Client name").fill("Year View Client");
  const matterResponse = page.waitForResponse((r) => /\/api\/matters\/?$/.test(new URL(r.url()).pathname)
    && r.request().method() === "POST");
  await matterDialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await json<{ id: string }>(await matterResponse, "Create matter through the UI");
  await expect(matterDialog).toBeHidden();
  return matter.id;
}

async function createItemsThroughUi(page: Page, rt: TesterRuntime, matterId: string, title: string,
  dates: { hearingOn: string; taskOn: string }): Promise<Created> {
  // Hearing: the matter's Schedule hearing dialog.
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/hearings`);
  await page.getByTestId("schedule-hearing-open").click();
  const hearingDialog = page.getByRole("dialog");
  await hearingDialog.getByTestId("schedule-hearing-date").fill(dates.hearingOn);
  await hearingDialog.getByLabel(/Forum \/ bench/i).fill("Delhi High Court");
  await hearingDialog.getByLabel(/Purpose \/ stage/i).fill(`${title} final hearing`);
  const hearingResponse = page.waitForResponse((r) => r.url().includes(`/api/matters/${matterId}/hearings`)
    && r.request().method() === "POST");
  await hearingDialog.getByTestId("schedule-hearing-submit").click();
  const hearing = await json<{ id: string }>(await hearingResponse, "Schedule hearing through the UI");
  await expect(hearingDialog).toBeHidden();

  // Task: the matter's task form.
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/tasks`);
  const taskTitle = page.getByPlaceholder("Prepare reply affidavit");
  const taskForm = page.locator("form").filter({ has: taskTitle });
  await taskTitle.fill(`${title} brief counsel`);
  await taskForm.getByLabel("Due").fill(dates.taskOn);
  const taskResponse = page.waitForResponse((r) => r.url().includes(`/api/matters/${matterId}/tasks`)
    && r.request().method() === "POST");
  await taskForm.getByRole("button", { name: "Add" }).click();
  const task = await json<{ id: string }>(await taskResponse, "Create task through the UI");
  return { hearingId: hearing.id, taskId: task.id };
}

async function retire(rt: TesterRuntime, request: APIRequestContext, matterId: string) {
  const matter = await json(await request.get(`${rt.api.origin}/api/matters/${matterId}`, { headers: rt.headers }),
    "Read created matter");
  await json(await request.patch(`${rt.api.origin}/api/matters/${matterId}/lifecycle/status`, {
    headers: rt.headers,
    data: {
      to_status: "disposed", expected_from_status: matter.status, expected_updated_at: matter.updated_at,
      reason: "Year view acceptance record retired after verification",
    },
  }), "Retire the acceptance matter");
}

async function backgroundOf(page: Page, selector: string): Promise<string> {
  return page.locator(selector).first().evaluate((element) => getComputedStyle(element).backgroundColor);
}

/** Chips a lawyer can see whose text is clipped to (almost) nothing. */
async function clippedChips(page: Page, cellTestId: RegExp): Promise<string[]> {
  return page.getByTestId("calendar-view-region").evaluate((region, source) => {
    const pattern = new RegExp(source);
    return Array.from(region.querySelectorAll<HTMLElement>("[data-testid]"))
      .filter((cell) => pattern.test(cell.dataset.testid ?? ""))
      .flatMap((cell) => Array.from(cell.querySelectorAll<HTMLElement>('a[data-testid^="calendar-event-"]')))
      .filter((chip) => chip.getClientRects().length > 0)
      .filter((chip) => (chip.querySelector<HTMLElement>(":scope > span:nth-child(2)")?.getBoundingClientRect().width ?? 0) < 24)
      .map((chip) => chip.dataset.testid ?? "");
  }, cellTestId.source);
}

async function yearJourney(page: Page, request: APIRequestContext, info: TestInfo,
  viewport: { width: number; height: number }) {
  const phone = viewport.width < 640;
  const rt = await prepareTester(page, request, info.project.use.baseURL, viewport);
  const title = stamp("Year view");
  const { year, hearingOn, taskOn } = targetDates(new Date());
  let matterId: string | undefined;
  try {
    // Retired in finally even when a later creation step fails.
    matterId = await createMatterThroughUi(page, rt, title);
    const created = await createItemsThroughUi(page, rt, matterId, title, { hearingOn, taskOn });

    // Tapping Year shows the year at once: the grid sits under its controls,
    // not below the provider panels. No programmatic scroll before this check.
    await page.goto(`${rt.web.origin}/app/calendar`);
    const { thisYear, todayKey } = await page.evaluate(() => {
      const d = new Date();
      return {
        thisYear: d.getFullYear(),
        todayKey: `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`,
      };
    });
    const summaryResponse = page.waitForResponse((r) => r.url().includes("/api/calendar/summary")
      && new URL(r.url()).searchParams.get("from") === `${year}-01-01`);
    await page.getByRole("tab", { name: /^year$/i }).click();
    await expect(page).toHaveURL(/[?&]view=year(?:&|$)/);
    await expectOnScreen(page.getByTestId(`calendar-year-month-${thisYear}-01`),
      "January is on screen right after tapping Year");
    const todayCell = page.getByTestId(`calendar-year-day-${todayKey}`);
    await expect(todayCell).toBeVisible();
    expect(await todayCell.evaluate((cell) => getComputedStyle(cell).backgroundColor), "today is highlighted")
      .not.toMatch(TRANSPARENT);

    if (year !== thisYear) await page.getByRole("button", { name: "Next", exact: true }).click();
    await expect(page.getByTestId("calendar-month-label")).toHaveText(String(year));
    const summary = await summaryResponse;
    expect(new URL(summary.url()).searchParams.get("to")).toBe(`${year}-12-31`);
    const shown = await json<{ days: { occurs_on: string; total: number; by_display_type: Record<string, number> }[] }>(
      summary, "Year summary the page rendered");

    // Oracle: the month list for each day must contain the created item, and the
    // server summary the page used must count exactly those day lists.
    for (const [day, id, type] of [
      [hearingOn, `hearing:${created.hearingId}`, "hearing"],
      [taskOn, `task:${created.taskId}`, "task_date"],
    ] as const) {
      const list = await json<{ events: { id: string; display_type: string }[] }>(await request.get(
        `${rt.api.origin}/api/calendar/events?from=${day}&to=${day}`, { headers: rt.headers }), `Day list ${day}`);
      expect(list.events.map((event) => event.id)).toContain(id);
      const n = list.events.length;
      expect(shown.days.find((entry) => entry.occurs_on === day)?.total, `summary total for ${day}`).toBe(n);
      const cell = page.getByTestId(`calendar-year-day-${day}`);
      // The lawyer scrolls the year down to the day.
      await cell.scrollIntoViewIfNeeded();
      await expectOnScreen(cell, `The ${type} day ${day} is visible in the Year view`);
      await expect(cell).toHaveAttribute("data-total", String(n));
      await expect(cell.locator(`[data-display-type="${type}"]`)).toHaveCount(1);
      await expect(cell).toHaveAccessibleName(new RegExp(
        `^\\d{1,2} [A-Z][a-z]{2} ${year}: ${n} ${n === 1 ? "event" : "events"} — .+\\. Open in Day view$`));
    }

    // Distinct, defined colours that match the legend.
    const hearingDot = await backgroundOf(page, `[data-testid="calendar-year-day-${hearingOn}"] [data-display-type="hearing"]`);
    const taskDot = await backgroundOf(page, `[data-testid="calendar-year-day-${taskOn}"] [data-display-type="task_date"]`);
    for (const colour of [hearingDot, taskDot]) expect(colour).not.toMatch(TRANSPARENT);
    expect(hearingDot).not.toBe(taskDot);
    expect(await backgroundOf(page, '[data-legend-dot="hearing"]')).toBe(hearingDot);
    expect(await backgroundOf(page, '[data-legend-dot="task_date"]')).toBe(taskDot);
    await expect(page.getByTestId("calendar-legend").getByRole("listitem")).toHaveCount(8);

    // Phones stack the months in one column; wide screens use four.
    const columns = await page.getByTestId("calendar-year-grid").evaluate((grid) => new Set(
      Array.from(grid.querySelectorAll<HTMLElement>("section[data-testid]"))
        .map((section) => Math.round(section.getBoundingClientRect().left))).size);
    expect(columns, "distinct month column positions").toBe(phone ? 1 : 4);

    // Range-bound actions explain themselves, and each quarter is a real calendar.
    await expect(page.getByTestId("calendar-year-export-note")).toContainText("92 days");
    const quarterLinks = page.getByTestId("calendar-ics-quarters").getByRole("link");
    await expect(quarterLinks).toHaveText(["Q1", "Q2", "Q3", "Q4"]);
    await expect(page.getByTestId("calendar-ics-download")).toHaveCount(0);
    const fileNames = new Set<string>();
    for (const href of await quarterLinks.evaluateAll((links) => links.map((link) => (link as HTMLAnchorElement).href))) {
      // The lawyer's own browser session, as the download link sends it.
      const ics = await page.request.get(href);
      expect(ics.status(), `quarter export ${href}`).toBe(200);
      expect(ics.headers()["content-type"]).toMatch(/^text\/calendar/);
      fileNames.add(ics.headers()["content-disposition"] ?? "");
      const body = await ics.text();
      expect(body.startsWith("BEGIN:VCALENDAR")).toBe(true);
      const range = new URL(href).searchParams;
      const holdsHearing = (range.get("from") ?? "") <= hearingOn && hearingOn <= (range.get("to") ?? "");
      expect(body.includes(`UID:hearing:${created.hearingId}@caseops.ai`), `hearing in ${href}`).toBe(holdsHearing);
    }
    expect(fileNames.size, "each quarter downloads under its own name").toBe(4);
    await expectNoPageOverflow(page);

    // Reload keeps the Year view and year.
    await page.reload();
    await expect(page.getByRole("tab", { name: /^year$/i })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("calendar-month-label")).toHaveText(String(year));
    await expect(page.getByTestId(`calendar-year-day-${hearingOn}`)).toHaveAttribute("data-total", /[1-9]/);

    // A day opens in Day view with the hearing listed.
    await page.getByTestId(`calendar-year-day-${hearingOn}`).click();
    await expect(page).toHaveURL(new RegExp(`[?&]view=day&date=${hearingOn}`));
    await expect(page.getByRole("tab", { name: /^day$/i })).toHaveAttribute("aria-selected", "true");
    const hearingLink = page.getByTestId(`calendar-event-hearing:${created.hearingId}`);
    await expectOnScreen(hearingLink, "The UI-created hearing is listed in Day view");
    await expect(hearingLink).toContainText(`${title} final hearing`);
    await expectNoPageOverflow(page);

    // Week view keeps every chip legible (phones stack the days).
    await page.getByRole("tab", { name: /^week$/i }).click();
    const weekChip = page.getByTestId(`calendar-week-day-${hearingOn}`)
      .getByTestId(`calendar-event-hearing:${created.hearingId}`);
    await expect(weekChip).toBeVisible();
    expect(await weekChip.locator(":scope > span:nth-child(2)").evaluate((text) => text.getBoundingClientRect().width),
      "hearing chip text width").toBeGreaterThan(48);
    expect(await clippedChips(page, /^calendar-week-day-/), "clipped week chips").toEqual([]);
    await expectNoPageOverflow(page);

    // Month view: phones show labelled per-type counts instead of clipped chips.
    await page.getByRole("tab", { name: /^month$/i }).click();
    const dayCount = (await json<{ events: unknown[] }>(await request.get(
      `${rt.api.origin}/api/calendar/events?from=${hearingOn}&to=${hearingOn}`, { headers: rt.headers }),
    "Hearing day list")).events.length;
    const badge = page.getByTestId(`calendar-month-count-${hearingOn}`);
    if (phone) {
      await expect(badge).toBeVisible();
      await expect(badge).toHaveAttribute("data-total", String(dayCount));
      await expect(page.getByRole("button", { name: `View all events on ${hearingOn}` }))
        .toHaveAccessibleDescription(new RegExp(`: ${dayCount} events? — .*hearing`));
    } else {
      await expect(badge).toBeHidden();
      await expect(page.getByTestId(`calendar-month-day-${hearingOn}`).locator('a[data-testid^="calendar-event-"]').first())
        .toBeVisible();
    }
    expect(await clippedChips(page, /^calendar-month-day-/), "clipped month chips").toEqual([]);
    await expectNoPageOverflow(page);
    await markPositive(info, "enh-017-year-view", {
      year, hearing_on: hearingOn, task_on: taskOn, hearing_dot: hearingDot, task_dot: taskDot, phone,
    });
  } finally {
    if (matterId) await retire(rt, request, matterId);
    await rt.release();
  }
}

test("ENH-017 Year view shows Ram's UI-created hearing and task on their days in distinct colours and survives reload", async ({ page, request }, info) => {
  await yearJourney(page, request, info, { width: 1440, height: 900 });
});

test("ENH-017 [mobile] Year view opens on screen in one column at 375 px, keeps chips legible, and opens a day", async ({ page, request }, info) => {
  await yearJourney(page, request, info, { width: 375, height: 812 });
});
