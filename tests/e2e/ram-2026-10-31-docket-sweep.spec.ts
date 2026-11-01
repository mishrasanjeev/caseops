/**
 * DOCKET-SWEEP (adjacent defect from the batch-4 Phase 1 audit, IP UJ-50 daily
 * docket): IP lists that silently stopped at their first page. The visible
 * part is the daily docket's "External calendar copies" card: it listed at
 * most 100 calendar-copy reviews and its count said 100 even when more were
 * pending. The API now reports the full total; the card shows that total and
 * says when it holds only the newest 100.
 *
 * Signed in as the tester in their own tenant, the spec opens the daily docket
 * at its address, reads the response the page itself received, and
 * holds the card to it: the count is the server total, a partial list says so,
 * and an empty one says nothing is waiting. Calendar-copy reviews arise only
 * from a connected provider calendar that drifted, so neither run creates
 * them; nothing is created and nothing needs retiring.
 */
import { expect, test, type Page, type Response, type TestInfo } from "@playwright/test";

import {
  deadSelects, expectNoPageOverflow, expectOnScreen, markPositive, prepareTester,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

type CandidatePage = { candidates: { id: string }[]; total: number };

const CANDIDATES_PATH = "/api/ip/calendar-projections/reconciliation-candidates";

/** A browser response the UI itself made; body intentionally not logged. */
async function uiJson<T>(response: Response, operation: string): Promise<T> {
  expect(response.status(), `${operation} returned ${response.status()}`).toBe(200);
  return response.json() as Promise<T>;
}

async function openDailyDocket(page: Page, origin: string): Promise<CandidatePage> {
  const candidates = page.waitForResponse(
    (response) => new URL(response.url()).pathname === CANDIDATES_PATH
      && response.request().method() === "GET",
  );
  await page.goto(`${origin}/app/ip/docket`);
  return uiJson<CandidatePage>(await candidates, "Calendar-copy review list");
}

async function holdCardToServerTotal(page: Page, info: TestInfo, body: CandidatePage, mobile: boolean) {
  expect(Number.isInteger(body.total), "The review list must report its full total").toBe(true);
  expect(body.total).toBeGreaterThanOrEqual(body.candidates.length);
  expect(new Set(body.candidates.map((row) => row.id)).size).toBe(body.candidates.length);

  const card = page.getByTestId("ip-docket-drift");
  await card.getByRole("heading", { name: "External calendar copies" }).scrollIntoViewIfNeeded();
  await expectOnScreen(card.getByRole("heading", { name: "External calendar copies" }),
    "The calendar-copy card is on screen");
  const waiting = card.getByText("Waiting for review", { exact: true });
  await waiting.scrollIntoViewIfNeeded();
  await expectOnScreen(waiting, "The review count heading is on screen");

  const partial = card.getByTestId("ip-calendar-candidates-partial");
  const empty = card.getByTestId("ip-calendar-candidates-empty");
  const list = card.getByTestId("ip-calendar-candidates");
  // Each state is asserted in full; which one applies is the server's answer.
  if (body.total === 0) {
    await expect(empty).toHaveText("No calendar-copy reviews are waiting.");
    await expect(list).toHaveCount(0);
    await expect(partial).toHaveCount(0);
  } else {
    await expect(waiting.locator("xpath=..").getByText(String(body.total), { exact: true })).toBeVisible();
    await expect(list.locator(":scope > li")).toHaveCount(body.candidates.length);
    if (body.total > body.candidates.length) {
      await expect(partial).toHaveText(
        `Showing the ${body.candidates.length} newest of ${body.total} reviews. Decide these and the next ones load here.`,
      );
    } else {
      await expect(partial).toHaveCount(0);
    }
    await expect(empty).toHaveCount(0);
  }
  expect(await deadSelects(page, card), "No dead select in the calendar-copy card").toEqual([]);
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "docket-sweep-candidates-mobile" : "docket-sweep-candidates", {
    total: body.total, shown: body.candidates.length,
  });
}

test("DOCKET-SWEEP calendar-copy reviews: the daily docket counts every pending review the server reports, not the first 100", async ({ page, request, baseURL }, info) => {
  const rt = await prepareTester(page, request, baseURL);
  try {
    const body = await openDailyDocket(page, rt.web.origin);
    await holdCardToServerTotal(page, info, body, false);
  } finally {
    await rt.release();
  }
});

test("[mobile] DOCKET-SWEEP calendar-copy reviews: the count and list state fit at 393px without horizontal page scroll", async ({ page, request, baseURL }, info) => {
  const rt = await prepareTester(page, request, baseURL, { width: 393, height: 851 });
  try {
    const body = await openDailyDocket(page, rt.web.origin);
    await holdCardToServerTotal(page, info, body, true);
  } finally {
    await rt.release();
  }
});
