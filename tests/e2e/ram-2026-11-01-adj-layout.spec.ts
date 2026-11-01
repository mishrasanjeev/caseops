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
 * The matter documents, SaaS invoice, recordal and Madrid checks are
 * local-only too, each for its stated reason (document uploads cannot be
 * retired yet, only the platform operator issues SaaS invoices, recordal and
 * Madrid prerequisites cannot be retired); their records are API or fixture
 * prerequisites, because the layout, not record creation, is under test.
 * The invoice journey retires its QA Matter from the moment it exists: the
 * product path voids and disposes it, and a failed run falls back to the API.
 */
import { expect, test, type Locator, type Page, type TestInfo } from "@playwright/test";

import { createRecordalFixture } from "./support/iplf058b";
import { commitImportThroughUi, uploadImportThroughUi } from "./support/ip-portfolio-import";
import {
  addLocalColleague, expectNoPageOverflow, json, markPositive, prepareTester, seedLocalSaasInvoice, stamp,
  type TesterRuntime,
} from "./support/ram-bugs4";
import { disposeMatter } from "./support/retire-records";

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
  const row = rowsRegion.locator("tbody > tr").filter({ hasText: number }).filter({ has: page.getByRole("link", { name: "Open record" }) });
  await expect(row).toHaveCount(1);
  await expectReachable(row.getByRole("link", { name: "Open record" }), "Open record on the committed row");
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

/** A stamped QA Matter through the New matter dialog; the caller retires it from the moment it exists. */
async function createQaMatter(page: Page, rt: TesterRuntime): Promise<string> {
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
  return matter.id;
}

/** A stamped draft invoice through the billing page's dialog. */
async function draftInvoice(page: Page, rt: TesterRuntime, matterId: string): Promise<{ invoiceId: string; number: string }> {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/billing`);
  await page.getByTestId("new-invoice-trigger").click();
  const invoiceDialog = page.getByRole("dialog", { name: "Create a draft invoice" });
  const number = code("QA-ADJ13");
  // A stamped number keeps the shared billing profile's sequence untouched.
  await invoiceDialog.getByLabel("Invoice number (optional)").fill(number);
  await invoiceDialog.getByLabel("Include uninvoiced billable time on this matter.").uncheck();
  await invoiceDialog.getByTestId("new-invoice-add-item").click();
  await invoiceDialog.getByLabel("Line 1 description").fill(stamp("ADJ13 drafting charges"));
  await invoiceDialog.getByLabel("Line 1 amount").fill("4000");
  const createdInvoice = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matterId}/invoices`
    && r.request().method() === "POST");
  await invoiceDialog.getByTestId("new-invoice-submit").click();
  const invoice = await json<{ id: string; status: string }>(await createdInvoice, "Create the draft through the dialog");
  expect(invoice.status).toBe("draft");
  await expect(invoiceDialog).toBeHidden();
  return { invoiceId: invoice.id, number };
}

/** The product path: void the draft on the billing page, then dispose the Matter from its page. */
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

/**
 * Fallback after a failure part-way: void the draft if one was created (a
 * draft that is already void answers 409) and dispose the Matter, by server id.
 */
async function retireInvoiceFixture(page: Page, rt: TesterRuntime, matterId: string, invoiceId: string | null) {
  if (invoiceId) {
    const voided = await page.request.post(`${rt.api.origin}/api/matters/${matterId}/invoices/${invoiceId}/void`,
      { headers: rt.headers });
    expect([200, 409], "void the QA draft after a failed run").toContain(voided.status());
  }
  await disposeMatter(page.request, rt.api.origin, rt.headers, matterId,
    "ADJ-13 invoice layout check stopped part-way; retiring the QA Matter.");
}

async function invoiceJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const matterId = await createQaMatter(page, rt);
  let invoiceId: string | null = null;
  let retired = false;
  try {
    const draft = await draftInvoice(page, rt, matterId);
    invoiceId = draft.invoiceId;
    const table = page.getByTestId("matter-invoices-table");
    await expect(table.getByText(draft.number, { exact: true })).toBeVisible();
    await expectReachable(page.getByTestId(`invoice-pdf-${invoiceId}`), "Draft PDF on the invoice row");
    await expectReachable(page.getByTestId(`invoice-issue-${invoiceId}`), "Issue invoice on the invoice row");
    await expectReachable(page.getByTestId(`invoice-void-${invoiceId}`), "Void draft on the invoice row");
    await page.getByTestId(`invoice-void-${invoiceId}`).click();
    await expectReachable(page.getByTestId(`invoice-void-confirm-${invoiceId}`), "Confirm void on the invoice row");
    await page.getByRole("button", { name: "Keep draft" }).click();
    if (mobile) await expectNoPageOverflow(page);
    await voidAndDispose(page, rt, matterId, invoiceId);
    retired = true;
    await markPositive(info, mobile ? "adj13-invoice-actions-mobile" : "adj13-invoice-actions", { invoice_id: invoiceId });
  } finally {
    if (!retired) await retireInvoiceFixture(page, rt, matterId, invoiceId);
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

/**
 * Scrolls a sideways-scrolling table to `fraction` of its overflow and returns
 * its geometry; the table must really overflow (wider than its container).
 */
async function scrollTable(scroller: Locator, fraction: number) {
  const geometry = await scroller.evaluate((element, share) => {
    element.scrollLeft = Math.round((element.scrollWidth - element.clientWidth) * share);
    return { scrollWidth: element.scrollWidth, clientWidth: element.clientWidth, scrollLeft: element.scrollLeft };
  }, fraction);
  expect(geometry.scrollWidth, `the table is wider than its container (${JSON.stringify(geometry)})`)
    .toBeGreaterThan(geometry.clientWidth);
  return geometry;
}

/** A stacked table fits its container: nothing to scroll sideways. */
async function expectStacked(scroller: Locator, what: string) {
  const geometry = await scroller.evaluate((element) => ({ scrollWidth: element.scrollWidth, clientWidth: element.clientWidth }));
  expect(geometry.scrollWidth, `${what} fits its container (${JSON.stringify(geometry)})`)
    .toBeLessThanOrEqual(geometry.clientWidth + 1);
}

type SeededDocument = { matterId: string; documentId: string; filename: string };

/** Local prerequisite for the documents table: a QA Matter with one uploaded document (not the workflow under test). */
async function seedMatterDocument(page: Page, rt: TesterRuntime): Promise<SeededDocument> {
  const matter = await json<{ id: string }>(await page.request.post(`${rt.api.origin}/api/matters/`, {
    headers: rt.headers, data: { title: stamp("ADJ13 documents matter"), matter_code: code("QADOC13"),
      practice_area: "Civil", forum_level: "high_court", status: "intake" },
  }), "Create the local QA Matter");
  const filename = `adj13-${fileTag(rt)}-written-statement-with-list-of-documents.txt`;
  const document = await json<{ id: string }>(await page.request.post(`${rt.api.origin}/api/matters/${matter.id}/attachments`, {
    headers: rt.headers,
    multipart: { file: { name: filename, mimeType: "text/plain",
      buffer: Buffer.from("Synthetic written statement for the ADJ-13 layout check. No legal effect.") } },
  }), "Upload the local QA document");
  return { matterId: matter.id, documentId: document.id, filename };
}

async function openMatterDocuments(page: Page, rt: TesterRuntime, seeded: SeededDocument): Promise<Locator> {
  await page.goto(`${rt.web.origin}/app/matters/${seeded.matterId}/documents`);
  const table = page.getByTestId("matter-documents-table");
  await expect(table.locator("tbody > tr").filter({ hasText: seeded.filename })).toHaveCount(1);
  return table;
}

/** Local prerequisite for the Madrid family table: a basic Indian application, its IR and one designation. */
async function seedMadridFamily(page: Page, rt: TesterRuntime): Promise<{ irId: string; wipo: string }> {
  const tag = fileTag(rt);
  const basic = await json<{ application: { id: string } }>(await page.request.post(
    `${rt.api.origin}/api/ip/trademark-applications/manual`, { headers: rt.headers, data: {
      title: `ADJ13 Madrid basic ${tag}`, restricted: false, asset_title: "ASTER", jurisdiction: "IN",
      office: "Trade Marks Registry Delhi", filing_phase: "filed", source_pending_identifier_allocation: false,
      application_number: { raw_value: code("TM-ADJ13"), source: "synthetic layout fixture", effective_from: "2026-08-25", is_primary: true },
      particulars: { form_key: "TM-A", form_version: "2026.1", mark_kind: "word",
        representation: { text: "ASTER", evidence_reference: `e2e:adj13:${tag}` },
        classes: [{ class_number: 9, specification: "Downloadable legal software" }], use_priority: null,
        parties: [{ role: "applicant", name: "Aster Labs Private Limited" }], agent: null,
        filing_manifest: [{ key: "representation", label: "Mark representation", required: true, evidence_reference: `e2e:adj13:${tag}` }] },
    } }), "Create the basic application", 201);
  const wipo = code("WIPO-ADJ13");
  const record = (data: Record<string, unknown>) => page.request.post(`${rt.api.origin}/api/ip/international-registrations`, {
    headers: rt.headers, data: {
      docket_title: `ADJ13 Madrid ${tag}`, restricted: false, international_application_number: null, ir_number: null,
      wipo_reference: wipo, holder_name: "Aster Labs Private Limited", mark_name: `ASTER ${tag}`, designated_office: null,
      classes: [9], goods_services: { "9": "Downloadable legal software" }, priority_claims: [], wipo_status: null,
      national_status: null, local_agent_name: "Synthetic Local Agents and Trade Mark Attorneys LLP",
      source_url: "https://www.wipo.int/madrid/monitor/fixture-adj13", source_reference: `wipo:adj13:${tag}:${Math.random()}`,
      source_retrieved_at: new Date().toISOString(), application_date: null, international_registration_date: null,
      notification_date: null, publication_date: null, statement_date: null, dependency_end_date: null, renewal_due_date: null,
      ...data,
    },
  });
  const ir = await json<{ id: string }>(await record({ record_kind: "international_registration", direction: "outbound",
    basic_application_id: basic.application.id, office_of_origin: "IP India", form_kind: "MM2", parent_registration_id: null,
    designated_member_code: null, jurisdiction: null, designation_kind: null, designation_effective_date: null,
  }), "Create the international registration", 201);
  await json(await record({ docket_title: `ADJ13 Madrid India designation ${tag}`, wipo_reference: `${wipo}-IN`,
    record_kind: "international_designation", direction: "outbound", parent_registration_id: ir.id,
    basic_application_id: null, office_of_origin: null, designated_member_code: "IN",
    designated_office: "Trade Marks Registry India", jurisdiction: "IN", designation_kind: "original",
    designation_effective_date: "2026-08-25", form_kind: null,
  }), "Create the India designation", 201);
  return { irId: ir.id, wipo };
}

async function madridJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const seeded = await seedMadridFamily(page, rt);
  // The page may auto-select the IR on load, so listen before navigating.
  const workspace = page.waitForResponse(r => new URL(r.url()).pathname
    === `/api/ip/international-registrations/${seeded.irId}/workspace` && r.request().method() === "GET");
  await page.goto(`${rt.web.origin}/app/ip/madrid`);
  await page.getByRole("button").filter({ hasText: seeded.wipo }).filter({ hasText: "IR" }).click();
  const body = await json<{ designations: { id: string }[] }>(await workspace, "Madrid workspace the page received");
  expect(body.designations.length).toBe(1);
  await page.getByRole("tab", { name: "Designations" }).click();
  const table = page.getByTestId("madrid-family-table");
  const row = table.locator("tbody > tr").filter({ hasText: "IN" });
  await expect(row).toHaveCount(1);
  await expectReachable(row.getByRole("link", { name: "Open" }), "Madrid family source link");
  if (mobile) {
    await expectStacked(table, "Madrid family table");
    await expectNoPageOverflow(page);
  }
  await markPositive(info, mobile ? "adj13-madrid-family-mobile" : "adj13-madrid-family", { ir_id: seeded.irId });
}

async function recordalJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const fixture = await createRecordalFixture(page.request, rt.api.origin, rt.headers, rt.actor.membership.id, fileTag(rt));
  const recordalId = fixture.recordal.id as string;
  const workspace = page.waitForResponse(r => new URL(r.url()).pathname === `/api/ip/recordals/${recordalId}/workspace`
    && r.request().method() === "GET");
  await page.goto(`${rt.web.origin}/app/ip/recordals`);
  await page.locator(`button[data-recordal-id="${recordalId}"]`).click();
  const body = await json<{ transactions: { id: string }[] }>(await workspace, "Recordal workspace the page received");
  expect(body.transactions.length, "the recordal has history to show").toBeGreaterThan(0);

  await page.getByRole("tab", { name: "Title at date" }).click();
  const interests = page.locator("section", { has: page.getByRole("heading", { name: "Registry-recorded position" }) }).locator("table");
  const interest = interests.locator("tbody > tr").filter({ hasText: "Oldco Brands Limited" });
  await expect(interest).toHaveCount(1);
  await expectReachable(interest.locator('td[data-label="Source"]'), "Registry-recorded interest source");
  await page.getByRole("tab", { name: "History" }).click();
  const history = page.locator("table", { has: page.getByRole("columnheader", { name: "Sequence" }) });
  const event = history.locator("tbody > tr").first();
  await expectReachable(event.locator('td[data-label="Source"]'), "Recordal history source");
  if (mobile) {
    await expectStacked(history.locator("xpath=.."), "Recordal history table");
    await expectNoPageOverflow(page);
  }
  await markPositive(info, mobile ? "adj13-recordal-tables-mobile" : "adj13-recordal-tables", { recordal_id: recordalId });
}

async function saasInvoicesJourney(page: Page, rt: TesterRuntime, info: TestInfo, mobile: boolean) {
  const number = `CASEOPS-SAAS-SUBSCRIPTION-${code("ADJ13")}`.slice(0, 80);
  seedLocalSaasInvoice(rt, number);
  const listed = page.waitForResponse(r => new URL(r.url()).pathname === "/api/billing/invoices" && r.request().method() === "GET");
  await page.goto(`${rt.web.origin}/app/admin/billing`);
  const body = await json<{ invoices: { id: string; invoice_number: string }[] }>(await listed, "Invoices the billing page received");
  expect(body.invoices.map(invoice => invoice.invoice_number)).toEqual([number]);
  const table = page.getByTestId("saas-invoices-table");
  const row = table.locator("tbody > tr").filter({ hasText: number });
  await expect(row).toHaveCount(1);
  await expectReachable(row.getByRole("button", { name: "Invoice" }), "SaaS invoice PDF download");
  await expectReachable(row.getByRole("button", { name: "JSON" }), "SaaS invoice data download");
  if (mobile) await expectNoPageOverflow(page);
  await markPositive(info, mobile ? "adj13-saas-invoices-mobile" : "adj13-saas-invoices", { invoice_id: body.invoices[0].id });
}

test("B4-ADJ-13 [local-only] matter document actions stay pinned on screen while the 72rem table scrolls at 1024px and 1280px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  expect(rt.local, "Matter document uploads cannot be retired yet (B4-ADJ-07); production test-legal must not gain one per run").toBe(true);
  const seeded = await seedMatterDocument(page, rt);
  try {
    for (const width of [1024, 1280]) {
      await page.setViewportSize({ width, height: 800 });
      const table = await openMatterDocuments(page, rt, seeded);
      const view = table.getByTestId(`matter-attachment-view-${seeded.documentId}`);
      await expectReachable(view, `View document at ${width}px before any sideways scroll`);
      for (const fraction of [0.5, 1]) {
        const geometry = await scrollTable(table, fraction);
        await expectReachable(view, `View document at ${width}px with the columns scrolled to ${geometry.scrollLeft}px`, { sideways: true });
      }
    }
    await markPositive(info, "adj13-matter-documents-pinned", { matter_id: seeded.matterId, document_id: seeded.documentId });
  } finally {
    await disposeMatter(page.request, rt.api.origin, rt.headers, seeded.matterId, "ADJ-13 documents layout check complete.");
  }
  await rt.release();
});

test("[mobile] B4-ADJ-13 [local-only] matter documents stack at 393px with every row action on screen", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  expect(rt.local, "Matter document uploads cannot be retired yet (B4-ADJ-07); production test-legal must not gain one per run").toBe(true);
  const seeded = await seedMatterDocument(page, rt);
  try {
    const table = await openMatterDocuments(page, rt, seeded);
    await expectStacked(table, "Matter documents table");
    await expectReachable(table.getByTestId(`matter-attachment-view-${seeded.documentId}`), "View document at 393px");
    await expectReachable(table.getByTestId(`matter-attachment-name-${seeded.documentId}`), "Document name link at 393px");
    await expectNoPageOverflow(page);
    await markPositive(info, "adj13-matter-documents-mobile", { matter_id: seeded.matterId, document_id: seeded.documentId });
  } finally {
    await disposeMatter(page.request, rt.api.origin, rt.headers, seeded.matterId, "ADJ-13 documents layout check complete.");
  }
  await rt.release();
});

test("B4-ADJ-13 [local-only] SaaS invoice downloads stay on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  expect(rt.local, "Only the platform operator issues SaaS invoices; production test-legal must not gain one").toBe(true);
  await saasInvoicesJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 [local-only] SaaS invoice downloads stay on screen at 393px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  expect(rt.local, "Only the platform operator issues SaaS invoices; production test-legal must not gain one").toBe(true);
  await saasInvoicesJourney(page, rt, info, true);
  await rt.release();
});

test("B4-ADJ-13 [local-only] recordal interest and history sources stay on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  expect(rt.local, "The recordal fixture creates a Registry snapshot and title interest that cannot be retired").toBe(true);
  await recordalJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 [local-only] recordal tables stack at 393px with their sources on screen", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  expect(rt.local, "The recordal fixture creates a Registry snapshot and title interest that cannot be retired").toBe(true);
  await recordalJourney(page, rt, info, true);
  await rt.release();
});

test("B4-ADJ-13 [local-only] Madrid family source links stay on screen at 1024px", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  expect(rt.local, "Madrid records are created through the API as a prerequisite; production test-legal must not gain them").toBe(true);
  await madridJourney(page, rt, info, false);
  await rt.release();
});

test("[mobile] B4-ADJ-13 [local-only] Madrid family table stacks at 393px with its source links on screen", async ({ page, request, baseURL }, info) => {
  test.setTimeout(300_000);
  const rt = await prepareTester(page, request, baseURL, MOBILE);
  expect(rt.local, "Madrid records are created through the API as a prerequisite; production test-legal must not gain them").toBe(true);
  await madridJourney(page, rt, info, true);
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
