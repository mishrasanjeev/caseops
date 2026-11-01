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
 * from a connected provider calendar that drifted, so these two journeys
 * create nothing. Locally the server total is always 0, so only the empty
 * branch runs here; the card's partial ("newest 100 of N") branch is proven
 * by the web unit test and the API test, not by this browser journey.
 *
 * The same sweep made the docket control report read the whole visible
 * population instead of the first 100 dockets. The [local-only] journey proves
 * that reader (the report preview, not the calendar-copy card) past the first page,
 * and it does create records: it imports 105 dockets through the portfolio
 * import page (the product's own bulk path, three commit batches), then
 * generates the Deadline control report and holds it to the server's docket
 * total, with the docket the server sorts last present. It is
 * local-only because an import job cannot be retired and production
 * test-legal must not receive 105 records.
 */
import { expect, test, type Page, type Response, type TestInfo } from "@playwright/test";

import { commitImportThroughUi, uploadImportThroughUi } from "./support/ip-portfolio-import";
import {
  deadSelects, expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester,
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

const POPULATION = 105;

type ReportPreview = { report_kind: string; row_count: number; truncated: boolean; rows: { docket_title: string }[] };

async function generateDeadlineControl(page: Page, rowLimit: number): Promise<ReportPreview> {
  await page.locator("#report-kind").selectOption("deadline_control");
  await page.getByLabel("Row limit").fill(String(rowLimit));
  const generated = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/ip/reports/preview"
    && response.request().method() === "POST");
  await page.getByRole("button", { name: "Generate", exact: true }).click();
  const body = await json<ReportPreview>(await generated, `Deadline control report at row limit ${rowLimit}`);
  expect(body.report_kind).toBe("deadline_control");
  return body;
}

test("DOCKET-SWEEP [local-only] 105 dockets imported through the portfolio import: the deadline control report counts every one, not the first 100", async ({ page, request, baseURL }, info) => {
  test.setTimeout(600_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "An import job cannot be retired; production test-legal must not receive 105 records").toBe(true);
  const marks = Array.from({ length: POPULATION }, (_, index) => `Sweep ${String(index + 1).padStart(3, "0")} ${rt.run}`);
  const serial = rt.run.replace(/[^0-9]+/g, "");
  const rows = [["Trademark", "Application No.", "Class", "Applicant Name(s)"],
    ...marks.map((mark, index) => [mark, `SWEEP-${serial}-${index + 1}`, "9", "Sweep Holdings LLP"])];
  const preview = await uploadImportThroughUi(page, rt, "docket-sweep-population.csv", rows);
  await commitImportThroughUi(page, rt, preview.job.id, POPULATION);

  const listed = await json<{ total_count: number; has_more: boolean }>(await request.get(
    `${rt.api.origin}/api/ip/dockets`, { headers: rt.headers, params: { limit: 100 } }), "Docket list oracle");
  expect(listed.total_count, "the tenant holds exactly the imported population").toBe(POPULATION);
  expect(listed.has_more, "a one-page reader would stop at 100").toBe(true);

  await page.goto(`${rt.web.origin}/app/ip/reports`);
  const full = await generateDeadlineControl(page, 200);
  expect(full.row_count, "every visible docket is a report row").toBe(POPULATION);
  expect(full.truncated).toBe(false);
  expect([...full.rows.map((row) => row.docket_title)].sort()).toEqual([...marks].sort());
  // The docket the server sorts last lies past the first 100: the one a
  // first-page reader would have dropped.
  const last = full.rows[POPULATION - 1].docket_title;
  const result = page.getByTestId("ip-report-result");
  await expect(result.getByText(`${POPULATION} rows`, { exact: true })).toBeVisible();
  await expect(result.locator("tbody > tr")).toHaveCount(POPULATION);
  await expect(result.locator("tbody > tr").last()).toContainText(last);
  await expect(result.getByText("Result truncated at the selected row limit", { exact: false })).toHaveCount(0);

  const capped = await generateDeadlineControl(page, 100);
  expect(capped.row_count).toBe(100);
  expect(capped.truncated, "a capped preview says it is partial").toBe(true);
  expect(capped.rows.map((row) => row.docket_title)).not.toContain(last);
  await expect(result.getByText("100 rows", { exact: true })).toBeVisible();
  await expect(result.getByText("Result truncated at the selected row limit", { exact: false })).toBeVisible();
  await markPositive(info, "docket-sweep-population-over-100", { population: POPULATION, job_id: preview.job.id });
  await rt.release();
});
