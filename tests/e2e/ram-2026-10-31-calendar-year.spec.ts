/**
 * ENH-017 / US-064 / FT-097 / FT-098 (J08, M08): calendar Year view.
 *
 * Signed in as the reporting tester in their own tenant (test-legal in
 * production, a freshly bootstrapped tenant locally), Ram creates a matter, a
 * hearing and a task through the product UI, opens the calendar, chooses Year,
 * and must see both items on their own days with distinct, defined legend
 * colours. The day counts must equal the server's year summary for those
 * dates, a click must open the day in Day view, and a reload must keep the
 * Year view. The matter is disposed afterwards, which retires both items.
 */
import { expect, test, type Page, type TestInfo } from "@playwright/test";

import {
  expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type Created = { matterId: string; hearingId: string; taskId: string; hearingOn: string; taskOn: string };

function isoDay(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function daysFromToday(days: number): string {
  const date = new Date();
  date.setDate(date.getDate() + days);
  return isoDay(date);
}

async function createThroughUi(page: Page, rt: TesterRuntime, title: string): Promise<Created> {
  // Matter: the product's New matter dialog.
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

  // Hearing: the matter's Schedule hearing dialog.
  const hearingOn = daysFromToday(40);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/hearings`);
  await page.getByTestId("schedule-hearing-open").click();
  const hearingDialog = page.getByRole("dialog");
  await hearingDialog.getByTestId("schedule-hearing-date").fill(hearingOn);
  await hearingDialog.getByLabel(/Forum \/ bench/i).fill("Delhi High Court");
  await hearingDialog.getByLabel(/Purpose \/ stage/i).fill(`${title} final hearing`);
  const hearingResponse = page.waitForResponse((r) => r.url().includes(`/api/matters/${matter.id}/hearings`)
    && r.request().method() === "POST");
  await hearingDialog.getByTestId("schedule-hearing-submit").click();
  const hearing = await json<{ id: string }>(await hearingResponse, "Schedule hearing through the UI");
  await expect(hearingDialog).toBeHidden();

  // Task: the matter's task form.
  const taskOn = daysFromToday(47);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/tasks`);
  const taskTitle = page.getByPlaceholder("Prepare reply affidavit");
  const taskForm = page.locator("form").filter({ has: taskTitle });
  await taskTitle.fill(`${title} brief counsel`);
  await taskForm.getByLabel("Due").fill(taskOn);
  const taskResponse = page.waitForResponse((r) => r.url().includes(`/api/matters/${matter.id}/tasks`)
    && r.request().method() === "POST");
  await taskForm.getByRole("button", { name: "Add" }).click();
  const task = await json<{ id: string }>(await taskResponse, "Create task through the UI");
  return { matterId: matter.id, hearingId: hearing.id, taskId: task.id, hearingOn, taskOn };
}

async function retire(rt: TesterRuntime, request: import("@playwright/test").APIRequestContext, matterId: string) {
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

async function yearJourney(page: Page, request: import("@playwright/test").APIRequestContext, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, info.project.use.baseURL, viewport);
  const title = stamp("Year view");
  const created = await createThroughUi(page, rt, title);
  try {
    const year = Number(created.hearingOn.slice(0, 4));
    const summaryResponse = page.waitForResponse((r) => r.url().includes("/api/calendar/summary")
      && new URL(r.url()).searchParams.get("from") === `${year}-01-01`);
    await page.goto(`${rt.web.origin}/app/calendar`);
    await page.getByRole("tab", { name: /^year$/i }).click();
    await expect(page).toHaveURL(/[?&]view=year(?:&|$)/);
    while (Number(await page.getByTestId("calendar-month-label").innerText()) < year) {
      await page.getByRole("button", { name: "Next", exact: true }).click();
    }
    await expect(page.getByTestId("calendar-month-label")).toHaveText(String(year));
    const shown = await json<{ days: { occurs_on: string; total: number; by_display_type: Record<string, number> }[] }>(
      await summaryResponse, "Year summary the page rendered");
    expect(new URL((await summaryResponse).url()).searchParams.get("to")).toBe(`${year}-12-31`);

    // Oracle: the month list for each day must contain the created item, and the
    // server summary the page used must count exactly those day lists.
    for (const [day, id, type] of [
      [created.hearingOn, `hearing:${created.hearingId}`, "hearing"],
      [created.taskOn, `task:${created.taskId}`, "task_date"],
    ] as const) {
      const list = await json<{ events: { id: string; display_type: string }[] }>(await request.get(
        `${rt.api.origin}/api/calendar/events?from=${day}&to=${day}`, { headers: rt.headers }), `Day list ${day}`);
      expect(list.events.map((event) => event.id)).toContain(id);
      const summaryDay = shown.days.find((entry) => entry.occurs_on === day);
      expect(summaryDay?.total, `summary total for ${day}`).toBe(list.events.length);
      const cell = page.getByTestId(`calendar-year-day-${day}`);
      await cell.scrollIntoViewIfNeeded();
      await expectOnScreen(cell, `The ${type} day ${day} is visible in the Year view`);
      await expect(cell).toHaveAttribute("data-total", String(list.events.length));
      await expect(cell.locator(`[data-display-type="${type}"]`)).toHaveCount(1);
      await expect(cell).toHaveAccessibleName(new RegExp(`${list.events.length} events?`));
    }

    // Distinct, defined colours that match the legend.
    const hearingDot = await backgroundOf(page,
      `[data-testid="calendar-year-day-${created.hearingOn}"] [data-display-type="hearing"]`);
    const taskDot = await backgroundOf(page,
      `[data-testid="calendar-year-day-${created.taskOn}"] [data-display-type="task_date"]`);
    for (const colour of [hearingDot, taskDot]) expect(colour).not.toMatch(/^(?:rgba\(0, 0, 0, 0\)|transparent)$/);
    expect(hearingDot).not.toBe(taskDot);
    expect(await backgroundOf(page, '[data-legend-dot="hearing"]')).toBe(hearingDot);
    expect(await backgroundOf(page, '[data-legend-dot="task_date"]')).toBe(taskDot);
    await expect(page.getByTestId("calendar-legend").getByRole("listitem")).toHaveCount(8);

    // Range-bound actions explain themselves instead of failing.
    await expect(page.getByTestId("calendar-year-export-note")).toContainText("92 days");
    await expect(page.getByTestId("calendar-ics-quarters").getByRole("link")).toHaveText(["Q1", "Q2", "Q3", "Q4"]);
    await expect(page.getByTestId("calendar-ics-download")).toHaveCount(0);
    await expectNoPageOverflow(page);

    // Reload keeps the Year view and year.
    await page.reload();
    await expect(page.getByRole("tab", { name: /^year$/i })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByTestId("calendar-month-label")).toHaveText(String(year));
    await expect(page.getByTestId(`calendar-year-day-${created.hearingOn}`)).toHaveAttribute("data-total", /[1-9]/);

    // A day opens in Day view with the hearing listed.
    await page.getByTestId(`calendar-year-day-${created.hearingOn}`).click();
    await expect(page).toHaveURL(new RegExp(`[?&]view=day&date=${created.hearingOn}`));
    await expect(page.getByRole("tab", { name: /^day$/i })).toHaveAttribute("aria-selected", "true");
    const hearingLink = page.getByTestId(`calendar-event-hearing:${created.hearingId}`);
    await expectOnScreen(hearingLink, "The UI-created hearing is listed in Day view");
    await expect(hearingLink).toContainText(`${title} final hearing`);
    await expectNoPageOverflow(page);
    await markPositive(info, "enh-017-year-view", {
      year, hearing_on: created.hearingOn, task_on: created.taskOn, hearing_dot: hearingDot, task_dot: taskDot,
    });
  } finally {
    await retire(rt, request, created.matterId);
    await rt.release();
  }
}

test("ENH-017 Year view shows Ram's UI-created hearing and task on their days in distinct colours and survives reload", async ({ page, request }, info) => {
  await yearJourney(page, request, info, { width: 1440, height: 900 });
});

test("ENH-017 [mobile] Year view stacks months without horizontal scroll and opens a day", async ({ page, request }, info) => {
  await yearJourney(page, request, info, { width: 393, height: 851 });
});
