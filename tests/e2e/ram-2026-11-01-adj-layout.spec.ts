/**
 * Batch-4 adjacent defects, layout and test hygiene (Ram, CaseOps_Bugs (4).xlsx,
 * 2026-10-30 audit):
 *
 * B4-ADJ-13: wide IP and billing tables put row actions past the right edge at
 * 1024px (beside the 256px sidebar) and on a phone. Each check below brings a
 * row action into view by scrolling the page vertically only, never a table
 * sideways, and requires it inside the viewport and hit-testable. The older
 * specs used scrollIntoViewIfNeeded, which scrolls the table sideways first
 * and so could never see this defect.
 *
 * B4-ADJ-16: addLocalColleague logged the colleague in on the caller's request
 * context, so that context then acted as the colleague.
 *
 * Production runs sign in as Ram on test-legal and only read his existing
 * portfolio and tracker; the invoice check creates one stamped QA Matter and a
 * stamped draft through the UI and voids and disposes both, as the BUG-016
 * journey does. Local runs import their records through the portfolio import
 * page. A portfolio import job cannot be retired, so the import-table checks
 * are local-only; the colleague check creates a user, so it is local-only.
 */
import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

import { commitImportThroughUi, uploadImportThroughUi } from "./support/ip-portfolio-import";
import {
  addLocalColleague, expectNoPageOverflow, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const DESKTOP = { width: 1024, height: 768 };
const MOBILE = { width: 393, height: 851 };

type PortfolioRow = { docket_id: string; docket_title: string; asset_title: string | null; is_active: boolean };
type TrackerRow = { docket_id: string; docket_title: string; docket_operational: boolean };

function code(prefix: string): string {
  return stamp(prefix).replace(/[^A-Za-z0-9]+/g, "-").toUpperCase();
}

/**
 * The control is reachable: on screen after a vertical page scroll only, with
 * no ancestor scrolled sideways, and the topmost element at its centre.
 */
async function expectReachable(control: Locator, what: string, { sideways = false } = {}) {
  await expect(control, what).toBeVisible();
  await control.evaluate((element) => {
    const box = element.getBoundingClientRect();
    window.scrollBy({ top: box.top - window.innerHeight / 3, behavior: "instant" });
  });
  const geometry = await control.evaluate((element) => {
    const box = element.getBoundingClientRect();
    const scrolled: string[] = [];
    for (let node = element.parentElement; node; node = node.parentElement) {
      if (node.scrollLeft > 0) scrolled.push(node.tagName.toLowerCase());
    }
    // A wrapped inline link spans line boxes; probe the centre of its first one.
    const line = element.getClientRects()[0] ?? box;
    const hit = document.elementFromPoint(line.left + line.width / 2, line.top + line.height / 2);
    return {
      left: Math.round(box.left), right: Math.round(box.right), top: Math.round(box.top), bottom: Math.round(box.bottom),
      width: document.documentElement.clientWidth, height: window.innerHeight,
      hit: hit !== null && (hit === element || element.contains(hit)), scrolled,
    };
  });
  if (!sideways) expect(geometry.scrolled, `${what}: no table was scrolled sideways`).toEqual([]);
  expect(geometry.left, `${what}: left edge on screen (${JSON.stringify(geometry)})`).toBeGreaterThanOrEqual(0);
  expect(geometry.right, `${what}: right edge on screen (${JSON.stringify(geometry)})`).toBeLessThanOrEqual(geometry.width);
  expect(geometry.top, `${what}: top on screen`).toBeGreaterThanOrEqual(0);
  expect(geometry.bottom, `${what}: bottom on screen`).toBeLessThanOrEqual(geometry.height);
  expect(geometry.hit, `${what}: nothing covers or clips it (${JSON.stringify(geometry)})`).toBe(true);
}

/** Local records for the portfolio and tracker checks, created through the import page. */
async function importLocalRecords(page: Page, rt: TesterRuntime): Promise<void> {
  const due = `${new Date().getUTCFullYear() + 2}-03-31`;
  const rows = [["Trademark", "Application No.", "Class", "Applicant Name(s)", "Renewal Due Date"]];
  for (let index = 1; index <= 3; index += 1) {
    rows.push([`Layout mark ${index} ${rt.run}`, code(`ADJL${index}`), "9", "Layout Holdings LLP", due]);
  }
  const preview = await uploadImportThroughUi(page, rt, `adj-layout-${fileTag(rt)}.csv`, rows);
  await commitImportThroughUi(page, rt, preview.job.id, 3);
}

function fileTag(rt: TesterRuntime): string {
  return rt.run.replace(/[^A-Za-z0-9]+/g, "-");
}

async function importRowsJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const number = code("ADJDUP");
  const mark = `Import reach ${rt.run}`;
  const preview = await uploadImportThroughUi(page, rt, `adj-import-${fileTag(rt)}.csv`, [
    ["Trademark", "Application No.", "Class", "Applicant Name(s)", "Renewal Due Date"],
    [mark, number, "9", "Reach Holdings LLP", `${new Date().getUTCFullYear() + 3}-03-31`],
    [`${mark} repeat`, number, "9", "Reach Holdings LLP", ""],
  ]);
  const duplicate = preview.rows.find(row => row.row_number === 2)!;
  expect(duplicate.duplicate_candidates.length, "the repeated number is offered as a duplicate").toBeGreaterThan(0);
  const rowsRegion = page.locator("main table");
  await expectReachable(rowsRegion.getByLabel("Decision for row 2"), "Duplicate decision for row 2");

  const committed = await commitImportThroughUi(page, rt, preview.job.id, 1);
  const created = committed.rows.find(row => row.row_number === 1)!;
  expect(created.created_docket_id).toBeTruthy();
  const row = rowsRegion.locator("tbody > tr").filter({ hasText: number }).filter({ has: page.getByRole("button", { name: "Open record" }) });
  await expect(row).toHaveCount(1);
  await expectReachable(row.getByRole("button", { name: "Open record" }), "Open record on the committed row");
  await expectReachable(row.getByRole("button", { name: "Edit source renewal date" }), "Edit source renewal date");
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj13-import-rows-mobile" : "adj13-import-rows", {
    job_id: preview.job.id, docket_id: created.created_docket_id,
  });
}

async function portfolioRows(page: Page, rt: TesterRuntime): Promise<PortfolioRow[]> {
  const body = await json<{ rows: PortfolioRow[] }>(await page.request.get(`${rt.api.origin}/api/ip/portfolio`,
    { headers: rt.headers, params: { limit: 50 } }), "Portfolio oracle");
  expect(body.rows.length, "the tester's portfolio has records to show").toBeGreaterThan(0);
  return body.rows;
}

async function openPortfolio(page: Page, rt: TesterRuntime): Promise<PortfolioRow> {
  const listed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/portfolio"
    && response.request().method() === "GET");
  await page.goto(`${rt.web.origin}/app/ip/portfolio`);
  const body = await json<{ rows: PortfolioRow[] }>(await listed, "Portfolio list the page received");
  const oracle = await portfolioRows(page, rt);
  const first = body.rows[0];
  expect(oracle.map(row => row.docket_id)).toContain(first.docket_id);
  return first;
}

async function trackerRow(page: Page, rt: TesterRuntime): Promise<TrackerRow> {
  const listed = page.waitForResponse(response => new URL(response.url()).pathname === "/api/ip/portfolio/renewal-tracker"
    && response.request().method() === "GET");
  await page.getByRole("button", { name: "Deadline tracker view" }).click();
  const body = await json<{ rows: TrackerRow[] }>(await listed, "Renewal tracker the page received");
  expect(body.rows.length, "the tester's renewal tracker has records to show").toBeGreaterThan(0);
  return body.rows[0];
}

async function trackerJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  await openPortfolio(page, rt);
  const target = await trackerRow(page, rt);
  const row = page.locator("main table", { has: page.locator("caption", { hasText: "Persisted trademark renewal dates" }) })
    .locator("tbody > tr")
    .filter({ has: page.locator(`a[href="/app/ip?docket=${encodeURIComponent(target.docket_id)}"]`) });
  await expect(row).toHaveCount(1);
  await expectReachable(row.getByRole("link", { name: target.docket_title }), "Tracker record link");
  await expectReachable(row.getByRole("button", { name: `Edit dates for ${target.docket_title}` }), "Tracker Edit dates");
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj13-tracker-mobile" : "adj13-tracker", { docket_id: target.docket_id });
}

/** A stamped QA Matter and draft invoice through the UI; retired by voidAndDispose. */
async function draftInvoice(page: Page, rt: TesterRuntime): Promise<{ matterId: string; invoiceId: string; number: string }> {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.locator("main").getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog", { name: "New matter" });
  await dialog.getByLabel("Title").fill(stamp("ADJ13 QA billing matter"));
  await dialog.getByLabel("Matter code").fill(code("QAADJ13"));
  await dialog.getByLabel("Practice area").fill("Banking");
  await dialog.getByLabel("Client name").fill("Synthetic QA client");
  await dialog.getByLabel("Opposing party").fill("Synthetic QA respondent");
  const createdMatter = page.waitForResponse(r => new URL(r.url()).pathname === "/api/matters/" && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await json<{ id: string }>(await createdMatter, "Create the QA Matter through the New matter dialog");
  await expect(dialog).toBeHidden();

  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  await page.getByTestId("new-invoice-trigger").click();
  const invoiceDialog = page.getByRole("dialog", { name: "Create a draft invoice" });
  const number = code("QA-ADJ13");
  // A stamped number keeps the shared billing profile's sequence untouched.
  await invoiceDialog.getByLabel("Invoice number (optional)").fill(number);
  await invoiceDialog.getByLabel("Include uninvoiced billable time on this matter.").uncheck();
  await invoiceDialog.getByTestId("new-invoice-add-item").click();
  await invoiceDialog.getByLabel("Line 1 description").fill(stamp("ADJ13 drafting charges"));
  await invoiceDialog.getByLabel("Line 1 amount").fill("4000");
  const createdInvoice = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matter.id}/invoices`
    && r.request().method() === "POST");
  await invoiceDialog.getByTestId("new-invoice-submit").click();
  const invoice = await json<{ id: string; status: string }>(await createdInvoice, "Create the draft through the dialog");
  expect(invoice.status).toBe("draft");
  await expect(invoiceDialog).toBeHidden();
  return { matterId: matter.id, invoiceId: invoice.id, number };
}

async function voidAndDispose(page: Page, rt: TesterRuntime, matterId: string, invoiceId: string) {
  await page.getByTestId(`invoice-void-${invoiceId}`).click();
  const voided = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matterId}/invoices/${invoiceId}/void`);
  await page.getByTestId(`invoice-void-confirm-${invoiceId}`).click();
  expect((await json<{ status: string }>(await voided, "Void the QA draft")).status).toBe("void");
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  await page.getByTestId("matter-dispose-trigger").click();
  await page.getByTestId("matter-lifecycle-reason").fill("ADJ-13 invoice layout check complete; retiring the QA Matter.");
  const disposed = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status` && r.request().method() === "PATCH");
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await json<{ status: string }>(await disposed, "Dispose the QA Matter")).status).toBe("disposed");
}

async function invoiceJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const { matterId, invoiceId, number } = await draftInvoice(page, rt);
  try {
    const table = page.getByTestId("matter-invoices-table");
    await expect(table.getByText(number, { exact: true })).toBeVisible();
    await expectReachable(page.getByTestId(`invoice-pdf-${invoiceId}`), "Draft PDF on the invoice row");
    await expectReachable(page.getByTestId(`invoice-issue-${invoiceId}`), "Issue invoice on the invoice row");
    await expectReachable(page.getByTestId(`invoice-void-${invoiceId}`), "Void draft on the invoice row");
    await page.getByTestId(`invoice-void-${invoiceId}`).click();
    await expectReachable(page.getByTestId(`invoice-void-confirm-${invoiceId}`), "Confirm void on the invoice row");
    await page.getByRole("button", { name: "Keep draft" }).click();
    if (mobile) await expectNoPageOverflow(page);
    await markPositive(info, mobile ? "adj13-invoice-actions-mobile" : "adj13-invoice-actions", { invoice_id: invoiceId });
  } finally {
    await voidAndDispose(page, rt, matterId, invoiceId);
  }
}

test("B4-ADJ-13 [local-only] import rows keep the duplicate decision, Open record and Edit source renewal date on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  expect(rt.local, "A portfolio import job cannot be retired; production test-legal must not gain import history").toBe(true);
  await importRowsJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 [local-only] import rows stack at 393px with every decision and record action on screen", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  expect(rt.local, "A portfolio import job cannot be retired; production test-legal must not gain import history").toBe(true);
  await importRowsJourney(page, rt, info, true);
  await rt.release();
});

test("B4-ADJ-13 portfolio keeps the Mark column, its record link and Edit dates pinned at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  if (rt.local) await importLocalRecords(page, rt);
  const target = await openPortfolio(page, rt);
  const title = target.asset_title ?? target.docket_title;

  await page.getByRole("button", { name: "Choose portfolio columns" }).click();
  const markOption = page.getByRole("checkbox", { name: "Mark (always shown)" });
  await expect(markOption).toBeChecked();
  await expect(markOption, "Mark cannot be hidden or moved to the end").toBeDisabled();
  await page.keyboard.press("Escape");

  const table = page.locator("main table").first();
  const row = table.locator("tbody > tr").filter({ has: page.locator(`a[href="/app/ip?docket=${target.docket_id}"]`) });
  await expect(row).toHaveCount(1);
  await expect(table.locator("thead th").first()).toHaveText("Mark");
  await expectReachable(row.getByRole("link", { name: title }), "Portfolio record link");
  await expectReachable(row.getByRole("button", { name: `Edit dates for ${target.docket_title}` }), "Portfolio Edit dates");

  // The table is wider than its container here, so scroll it to the far end:
  // the pinned Mark column and its actions must still be on screen.
  const scroller = table.locator("xpath=..");
  const overflow = await scroller.evaluate((element) => {
    element.scrollLeft = element.scrollWidth;
    return { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, scrollLeft: element.scrollLeft };
  });
  expect(overflow.scrollWidth, "the portfolio table is wider than its container at 1024px").toBeGreaterThan(overflow.clientWidth);
  expect(overflow.scrollLeft).toBeGreaterThan(0);
  await expectReachable(row.getByRole("link", { name: title }), "Portfolio record link after scrolling the columns", { sideways: true });
  await expectReachable(row.getByRole("button", { name: `Edit dates for ${target.docket_title}` }),
    "Portfolio Edit dates after scrolling the columns", { sideways: true });
  await markPositive(info, "adj13-portfolio-pinned-mark", { docket_id: target.docket_id, overflow });
  await rt.release();
});

test("[mobile] B4-ADJ-13 portfolio cards keep the record link and Edit dates on screen at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  if (rt.local) await importLocalRecords(page, rt);
  const target = await openPortfolio(page, rt);
  const title = target.asset_title ?? target.docket_title;
  const card = page.locator("main article").filter({ has: page.locator(`a[href="/app/ip?docket=${target.docket_id}"]`) });
  await expect(card).toHaveCount(1);
  await expectReachable(card.getByRole("link", { name: title }), "Portfolio card record link");
  await expectReachable(card.getByRole("button", { name: `Edit dates for ${target.docket_title}` }), "Portfolio card Edit dates");
  await expectNoPageOverflow(page);
  await markPositive(info, "adj13-portfolio-cards-mobile", { docket_id: target.docket_id });
  await rt.release();
});

test("B4-ADJ-13 renewal tracker rows keep Edit dates on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  if (rt.local) await importLocalRecords(page, rt);
  await trackerJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 renewal tracker rows keep Edit dates on screen at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  if (rt.local) await importLocalRecords(page, rt);
  await trackerJourney(page, rt, info, true);
  await rt.release();
});

test("B4-ADJ-13 matter invoice row actions stay on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  await invoiceJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 matter invoice row actions stay on screen at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  await invoiceJourney(page, rt, info, true);
  await rt.release();
});

test("B4-ADJ-16 [local-only] adding a colleague leaves the caller's API context signed in as the tester", async ({ page, request, baseURL }, info) => {
  test.setTimeout(240_000);
  const rt = await prepareTester(page, request, baseURL);
  expect(rt.local, "Creating a colleague adds a user; production test-legal uses existing members").toBe(true);
  const before = await json<{ membership: { id: string } }>(await request.get(`${rt.api.origin}/api/companies/current`),
    "Caller context identity before");
  expect(before.membership.id).toBe(rt.actor.membership.id);
  const colleague = await addLocalColleague(rt, request, "member", "Dev Colleague");
  expect(colleague.membershipId).not.toBe(rt.actor.membership.id);
  const after = await json<{ membership: { id: string } }>(await request.get(`${rt.api.origin}/api/companies/current`),
    "Caller context identity after");
  expect(after.membership.id, "the caller's context is still the tester, not the colleague").toBe(rt.actor.membership.id);
  await markPositive(info, "adj16-caller-context-kept", { colleague: colleague.membershipId });
  await rt.release();
});
