/**
 * BUG-016 (Ram, CaseOps_Bugs (4).xlsx, 2026-10-30): invoice PDF line items and
 * details were unreadable (dark text on a dark fill) and every invoice carried
 * a blank second page.
 *
 * Signed in as the reporting tester, each journey creates its own clock-stamped
 * QA matter through the New matter dialog (never the tester's real matters),
 * creates a draft invoice with stamped line items and a stamped invoice number
 * (so the shared billing profile's number sequence is never consumed), and
 * downloads the PDF from the billing page. pdfjs text extraction must find
 * every line item, and an in-browser raster of the file (pdfjs rendered to a
 * canvas) measures each text run's glyph ink against the dominant background
 * of its own box. The draft is then voided through the product, the money
 * figures return to their starting values, the tester's billing profiles are
 * unchanged, and the QA matter is disposed through the matter page.
 *
 * Issuing creates a final invoice, so the issue journey is [local-only]. The
 * two reported invoices are read (downloaded, never changed) in production.
 */
import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  expect, test, type APIRequestContext, type BrowserContext, type Page, type Response, type TestInfo,
} from "@playwright/test";

import { repoRoot } from "./support/env";
import {
  expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 393, height: 851 };
const MIN_CONTRAST = 4.5;
const LONG_TAIL = "drafting and settling the written statement with a para-wise reply, the list of documents, "
  + "the affidavit of admission and denial and the application for condonation of delay before the "
  + "Commercial Division of the High Court of Delhi at New Delhi";
// The tester's reported matter and invoices (server identity; production only).
const REPORTED_MATTER_ID = "56264441-dd0d-48e6-9c57-691892c63912";
const REPORTED_INVOICE_IDS = ["e3e9b137-ede7-4383-8974-19cec0221ff5", "92f40c62-d7c9-47c9-8515-9b1223d68aa0"];
const STATUS_DOCUMENT: Record<string, { label: string; banner: string }> = {
  draft: { label: "Draft PDF", banner: "DRAFT - NOT A TAX INVOICE" },
  needs_review: { label: "Review copy PDF", banner: "OUTSIDE COUNSEL INVOICE - SUBMITTED FOR REVIEW" },
  void: { label: "Void PDF", banner: "VOID - CANCELLED INVOICE" },
  issued: { label: "PDF", banner: "Invoice" },
};

const compact = (value: string) => value.replace(/\s+/g, "");
const isLocal = (baseURL: string | undefined) =>
  ["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseURL ?? process.env.CASEOPS_WEB_BASE_URL ?? "https://caseops.ai").hostname);
const inr = (minor: number) =>
  `INR ${new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(minor / 100)}`;
/** Matter codes and invoice numbers accept letters, digits and hyphens only. */
const stampedCode = (prefix: string) => stamp(prefix).replace(/[^A-Za-z0-9]+/g, "-").toUpperCase();

async function pageJson(response: Response, operation: string): Promise<any> {
  expect(response.status(), `${operation} returned ${response.status()}`).toBe(200);
  return response.json();
}

async function pdfText(data: Buffer): Promise<string[]> {
  const pdfjs = await import("pdfjs-dist/legacy/build/pdf.mjs");
  const document = await pdfjs.getDocument({ data: new Uint8Array(data), useSystemFonts: false }).promise;
  const pages: string[] = [];
  for (let number = 1; number <= document.numPages; number += 1) {
    const content = await (await document.getPage(number)).getTextContent();
    pages.push(content.items.map(item => ("str" in item ? item.str : "")).join(" "));
  }
  return pages;
}

type RasterRun = { page: number; text: string; contrast: number; inside: boolean };

/**
 * Renders the PDF with pdfjs on a browser canvas. A run's contrast is its
 * glyph ink (read from the box interior, so a margin or rule touching the box
 * edge cannot stand in for it) against the dominant colour of its own box.
 */
async function rasterRuns(context: BrowserContext, data: Buffer): Promise<{ pages: number; runs: RasterRun[] }> {
  const origin = "https://pdf-raster.invalid";
  const files: Record<string, string> = { "/pdf.mjs": "pdf.min.mjs", "/pdf.worker.mjs": "pdf.worker.min.mjs" };
  const raster = await context.newPage();
  try {
    await raster.route(`${origin}/**`, async (route) => {
      const name = new URL(route.request().url()).pathname;
      if (name === "/") return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>raster</title>" });
      const file = files[name];
      if (!file) return route.fulfill({ status: 404, body: "" });
      return route.fulfill({ contentType: "text/javascript",
        body: await readFile(path.join(repoRoot, "node_modules/pdfjs-dist/build", file)) });
    });
    await raster.goto(`${origin}/`);
    return await raster.evaluate(async ({ base64, scale }) => {
      const pdfjs = await import(`${location.origin}/pdf.mjs`);
      (globalThis as any).pdfjsWorker = await import(`${location.origin}/pdf.worker.mjs`);
      const bytes = Uint8Array.from(atob(base64), c => c.charCodeAt(0));
      const doc = await pdfjs.getDocument({ data: bytes, isEvalSupported: false }).promise;
      const channel = (v: number) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
      const lum = (r: number, g: number, b: number) => 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
      const runContrast = (ctx: CanvasRenderingContext2D, x0: number, y0: number, x1: number, y1: number) => {
        const w = x1 - x0;
        const h = y1 - y0;
        if (w < 2 || h < 2) return 1;
        const px = ctx.getImageData(x0, y0, w, h).data;
        const counts = new Map<number, number>();
        for (let i = 0; i < px.length; i += 4) {
          const key = (px[i] << 16) | (px[i + 1] << 8) | px[i + 2];
          counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        let background = 0;
        let most = -1;
        for (const [key, count] of counts) if (count > most) { most = count; background = key; }
        const backgroundLum = lum((background >> 16) & 255, (background >> 8) & 255, background & 255);
        const insetX = Math.floor(w / 10);
        const insetY = Math.floor(h / 5);
        let best = 1;
        for (let y = insetY; y < h - insetY; y += 1) {
          for (let x = insetX; x < w - insetX; x += 1) {
            const i = (y * w + x) * 4;
            const value = lum(px[i], px[i + 1], px[i + 2]);
            const ratio = (Math.max(value, backgroundLum) + 0.05) / (Math.min(value, backgroundLum) + 0.05);
            if (ratio > best) best = ratio;
          }
        }
        return best;
      };
      const runs: Array<{ page: number; text: string; contrast: number; inside: boolean }> = [];
      for (let number = 1; number <= doc.numPages; number += 1) {
        const page = await doc.getPage(number);
        const viewport = page.getViewport({ scale });
        const canvas = document.createElement("canvas");
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
        ctx.fillStyle = "#ffffff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        await page.render({ canvas, canvasContext: ctx, viewport }).promise;
        const [, , pageWidth, pageHeight] = page.view;
        const content = await page.getTextContent();
        for (const item of content.items as any[]) {
          if (!("str" in item) || !item.str.trim()) continue;
          const [, , c, d, e, f] = pdfjs.Util.transform(viewport.transform, item.transform);
          const size = Math.hypot(c, d);
          const x0 = Math.max(0, Math.floor(e));
          const x1 = Math.min(canvas.width, Math.ceil(e + item.width * scale));
          const y0 = Math.max(0, Math.floor(f - size * 0.8));
          const y1 = Math.min(canvas.height, Math.ceil(f + size * 0.2));
          const [, , , , tx, ty] = item.transform;
          runs.push({
            page: number, text: item.str, contrast: runContrast(ctx, x0, y0, x1, y1),
            inside: tx >= 0 && tx + item.width <= pageWidth + 0.5 && ty >= 0 && ty <= pageHeight,
          });
        }
      }
      return { pages: doc.numPages, runs };
    }, { base64: data.toString("base64"), scale: 200 / 72 });
  } finally {
    await raster.close();
  }
}

/** One page, "Page 1 of 1", and every text run legible and inside the page. */
async function expectLegiblePdf(context: BrowserContext, file: Buffer, info: TestInfo, name: string): Promise<string> {
  expect(file.subarray(0, 5).toString()).toBe("%PDF-");
  const pages = await pdfText(file);
  expect(pages, "the invoice fits one page with no blank trailing page").toHaveLength(1);
  expect(compact(pages[0])).toContain(compact("Page 1 of 1"));
  const raster = await rasterRuns(context, file);
  expect(raster.pages).toBe(1);
  expect(raster.runs.length).toBeGreaterThan(20);
  const illegible = raster.runs.filter(run => run.contrast < MIN_CONTRAST).map(run => `${run.text} (${run.contrast.toFixed(2)})`);
  expect(illegible, "every text run reaches WCAG AA contrast against its own background").toEqual([]);
  expect(raster.runs.filter(run => !run.inside).map(run => run.text)).toEqual([]);
  await info.attach(`${name}-raster.json`, {
    body: JSON.stringify({ runs: raster.runs.length, min_contrast: Math.min(...raster.runs.map(run => run.contrast)) }),
    contentType: "application/json",
  });
  return compact(pages.join(" "));
}

/** Read-only API oracle: the tester's billing profiles, compared before and after. */
async function billingProfiles(rt: TesterRuntime, request: APIRequestContext): Promise<unknown> {
  return json(await request.get(`${rt.api.origin}/api/admin/matter-billing`, { headers: rt.headers }),
    "Read billing profiles");
}

async function moneyFigures(page: Page): Promise<{ billed: string; balance: string }> {
  return {
    billed: (await page.getByTestId("billing-kpi-total-billed").textContent()) ?? "",
    balance: (await page.getByTestId("billing-kpi-balance-due").textContent()) ?? "",
  };
}

async function createQaMatterThroughUi(page: Page, rt: TesterRuntime): Promise<{ id: string; code: string }> {
  const code = stampedCode("QAB016");
  const title = stamp("BUG016 QA billing matter");
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.locator("main").getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog", { name: "New matter" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Banking");
  await dialog.getByLabel("Client name").fill("Synthetic QA client");
  await dialog.getByLabel("Opposing party").fill("Synthetic QA respondent");
  const created = page.waitForResponse(r => new URL(r.url()).pathname === "/api/matters/" && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await pageJson(await created, "Create the QA matter through the New matter dialog");
  expect(matter.matter_code).toBe(code);
  expect(matter.title).toBe(title);
  await expect(dialog).toBeHidden();
  return { id: matter.id as string, code };
}

async function disposeQaMatterThroughUi(page: Page, rt: TesterRuntime, matterId: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  const trigger = page.getByTestId("matter-dispose-trigger");
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  await page.getByTestId("matter-lifecycle-reason").fill("BUG-016 invoice PDF journey complete; retiring the synthetic QA matter.");
  const disposed = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status` && r.request().method() === "PATCH");
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await pageJson(await disposed, "Dispose the QA matter")).status).toBe("disposed");
  await expect(page.getByTestId("matter-reopen-trigger")).toBeVisible();
}

async function createDraftThroughDialog(page: Page, matterId: string, invoiceNumber: string, lines: string[]): Promise<any> {
  const trigger = page.getByTestId("new-invoice-trigger");
  await trigger.scrollIntoViewIfNeeded();
  await expectOnScreen(trigger, "New invoice is reachable on the billing page");
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Create a draft invoice" });
  await expect(dialog).toBeVisible();
  // A stamped number keeps the shared billing profile's sequence untouched.
  await dialog.getByLabel("Invoice number (optional)").fill(invoiceNumber);
  await dialog.getByLabel("Include uninvoiced billable time on this matter.").uncheck();
  for (const [index, description] of lines.entries()) {
    await dialog.getByTestId("new-invoice-add-item").click();
    await dialog.getByLabel(`Line ${index + 1} description`).fill(description);
    await dialog.getByLabel(`Line ${index + 1} amount`).fill(index === 0 ? "4000" : "175000");
  }
  const submit = dialog.getByTestId("new-invoice-submit");
  await expect(submit).toHaveText("Create draft invoice");
  await submit.scrollIntoViewIfNeeded();
  await expectOnScreen(submit, "Create draft invoice is on screen");
  const created = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matterId}/invoices`
    && r.request().method() === "POST");
  await submit.click();
  const invoice = await pageJson(await created, "Create draft invoice through the dialog");
  expect(invoice.status).toBe("draft");
  expect(invoice.invoice_number).toBe(invoiceNumber);
  expect(invoice.line_items.map((line: { description: string }) => line.description)).toEqual(lines);
  await expect(page.getByText("Draft invoice created")).toBeVisible();
  return invoice;
}

async function downloadFromBillingPage(page: Page, matterId: string, invoiceId: string, label: string): Promise<Buffer> {
  const button = page.getByTestId(`invoice-pdf-${invoiceId}`);
  await button.scrollIntoViewIfNeeded();
  await expect(button).toHaveText(label);
  await expectOnScreen(button, `${label} action is on screen`);
  await expectNoPageOverflow(page);
  // The API imports fpdf2 lazily on its first PDF; measured 31.8 s cold on the
  // shared Windows host (and a Cloud Run cold instance pays it too), so each
  // download gets one bounded allowance instead of the 15 s action default.
  const response = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/invoices/${invoiceId}/download`, { timeout: 60_000 });
  const download = page.waitForEvent("download", { timeout: 60_000 });
  await button.click();
  const downloaded = await response;
  expect(downloaded.status()).toBe(200);
  expect(downloaded.headers()["content-type"]).toBe("application/pdf");
  return readFile((await (await download).path())!);
}

function journeyLines(): string[] {
  return [stamp("BUG016 drafting charges"), `${stamp("BUG016 pleadings")} ${LONG_TAIL}`];
}

async function draftInvoiceJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, baseURL, viewport);
  const profilesBefore = await billingProfiles(rt, request);
  const matter = await createQaMatterThroughUi(page, rt);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  await expect(page.getByTestId("billing-kpi-total-billed")).toBeVisible();
  const figuresBefore = await moneyFigures(page);
  const lines = journeyLines();
  const invoice = await createDraftThroughDialog(page, matter.id, stampedCode("QA-B016"), lines);
  await expect.poll(() => moneyFigures(page), { message: "the draft is counted while it exists" }).not.toEqual(figuresBefore);

  const file = await downloadFromBillingPage(page, matter.id, invoice.id, "Draft PDF");
  const text = await expectLegiblePdf(page.context(), file, info, "draft");
  for (const description of lines) expect(text, `line item ${description}`).toContain(compact(description));
  expect(text).toContain(compact("DRAFT - NOT A TAX INVOICE"));
  expect(text).toContain(compact("Status: Draft"));
  expect(text).toContain(compact(invoice.invoice_number));
  expect(text).not.toContain("TaxInvoice/Receipt");
  await markPositive(info, "bug016-draft-invoice-pdf-legible", { invoice_id: invoice.id, invoice_number: invoice.invoice_number });

  // Retire the draft through the product's own two-step action.
  await page.getByTestId(`invoice-void-${invoice.id}`).click();
  const confirm = page.getByTestId(`invoice-void-confirm-${invoice.id}`);
  await confirm.scrollIntoViewIfNeeded();
  await expectOnScreen(confirm, "Confirm void is on screen");
  await expectNoPageOverflow(page);
  const voided = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matter.id}/invoices/${invoice.id}/void`);
  await confirm.click();
  const record = await pageJson(await voided, "Void the draft through the billing page");
  expect(record.status).toBe("void");
  expect(record.balance_due_minor).toBe(0);
  await expect(page.getByText(`Draft ${invoice.invoice_number} voided.`)).toBeVisible();
  await expect(page.getByTestId(`invoice-void-${invoice.id}`)).toHaveCount(0);
  await expect(page.getByTestId(`invoice-pdf-${invoice.id}`)).toHaveText("Void PDF");
  await expect.poll(() => moneyFigures(page), { message: "a voided draft leaves the money figures" }).toEqual(figuresBefore);
  expect(await billingProfiles(rt, request), "the shared billing profile is never written").toEqual(profilesBefore);
  await markPositive(info, "bug016-draft-voided", { invoice_id: invoice.id, figures: figuresBefore });

  await disposeQaMatterThroughUi(page, rt, matter.id);
  await markPositive(info, "bug016-qa-matter-disposed", { matter_id: matter.id });
  await rt.release();
}

async function issueInvoiceJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, baseURL, viewport);
  const matter = await createQaMatterThroughUi(page, rt);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  const lines = journeyLines();
  const invoice = await createDraftThroughDialog(page, matter.id, stampedCode("QA-B016-ISSUE"), lines);

  await expect(page.getByText("A draft is not payable until it is issued.")).toBeVisible();
  const issue = page.getByTestId(`invoice-issue-${invoice.id}`);
  await issue.scrollIntoViewIfNeeded();
  await expectOnScreen(issue, "Issue invoice is on screen");
  await issue.click();
  await expect(page.getByTestId(`invoice-confirm-note-${invoice.id}`))
    .toHaveText("Issuing is final; an issued invoice cannot be voided here.");
  const confirm = page.getByTestId(`invoice-issue-confirm-${invoice.id}`);
  await confirm.scrollIntoViewIfNeeded();
  await expectOnScreen(confirm, "Confirm issue is on screen");
  await expectNoPageOverflow(page);
  const issued = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matter.id}/invoices/${invoice.id}/issue`);
  await confirm.click();
  const record = await pageJson(await issued, "Issue the draft through the billing page");
  expect(record.status).toBe("issued");
  expect(record.invoice_number).toBe(invoice.invoice_number);
  await expect(page.getByText(`Invoice ${invoice.invoice_number} issued.`)).toBeVisible();
  await expect(page.getByTestId(`invoice-void-${invoice.id}`)).toHaveCount(0);
  await expect(page.getByTestId(`invoice-issue-${invoice.id}`)).toHaveCount(0);

  const file = await downloadFromBillingPage(page, matter.id, invoice.id, "PDF");
  const text = await expectLegiblePdf(page.context(), file, info, "issued");
  for (const description of lines) expect(text, `line item ${description}`).toContain(compact(description));
  expect(text).toContain(compact("Status: Issued"));
  expect(text).not.toContain("DRAFT");
  await markPositive(info, "bug016-issued-invoice-pdf-legible", { invoice_id: invoice.id });

  await disposeQaMatterThroughUi(page, rt, matter.id);
  await rt.release();
}

async function reportedInvoicesJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, baseURL, viewport);
  const workspace = await json(await request.get(`${rt.api.origin}/api/matters/${REPORTED_MATTER_ID}/workspace`,
    { headers: rt.headers }), "Read the reported matter");
  await page.goto(`${rt.web.origin}/app/matters/${REPORTED_MATTER_ID}/billing`);
  for (const invoiceId of REPORTED_INVOICE_IDS) {
    const invoice = workspace.invoices.find((item: { id: string }) => item.id === invoiceId);
    expect(invoice, `reported invoice ${invoiceId} is on the reported matter`).toBeTruthy();
    const document = STATUS_DOCUMENT[invoice.status];
    expect(document, `a known document kind for status ${invoice.status}`).toBeTruthy();
    const file = await downloadFromBillingPage(page, REPORTED_MATTER_ID, invoiceId, document.label);
    const text = await expectLegiblePdf(page.context(), file, info, invoice.invoice_number);
    expect(text).toContain(compact(document.banner));
    expect(text).toContain(compact(invoice.invoice_number));
    for (const line of invoice.line_items) expect(text, `line item ${line.description}`).toContain(compact(line.description));
    // INVR-2026-028 is stored with taxable value 0 and no tax; it prints its subtotal.
    const taxable = invoice.taxable_value_minor || (invoice.tax_amount_minor ? 0 : invoice.subtotal_amount_minor);
    expect(text).toContain(compact(`Taxable value ${inr(taxable)}`));
    expect(text).toContain(compact(`Grand total ${inr(invoice.total_amount_minor)}`));
    await markPositive(info, `bug016-reported-${invoice.invoice_number}`, { invoice_id: invoiceId, status: invoice.status });
  }
  await rt.release();
}

test("BUG-016 draft invoice PDF downloaded from the billing page is legible, one page and marked DRAFT", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(300_000);
  await draftInvoiceJourney(page, request, baseURL, info, DESKTOP);
});

test("BUG-016 [mobile] draft invoice PDF journey works at 393px without page overflow", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(300_000);
  await draftInvoiceJourney(page, request, baseURL, info, MOBILE);
});

test("BUG-016 [local-only] issuing a draft from the billing page produces the legible issued invoice", async (
  { page, request, baseURL }, info,
) => {
  test.skip(!isLocal(baseURL), "Issuing is final; production runs never issue an invoice in the tester's tenant.");
  test.setTimeout(300_000);
  await issueInvoiceJourney(page, request, baseURL, info, DESKTOP);
});

test("BUG-016 [local-only] [mobile] issuing a draft works at 393px without page overflow", async (
  { page, request, baseURL }, info,
) => {
  test.skip(!isLocal(baseURL), "Issuing is final; production runs never issue an invoice in the tester's tenant.");
  test.setTimeout(300_000);
  await issueInvoiceJourney(page, request, baseURL, info, MOBILE);
});

test("BUG-016 [prod-only] the reported invoices INVR-2026-028 and INVR-2026-068 download legible (read-only)", async (
  { page, request, baseURL }, info,
) => {
  test.skip(isLocal(baseURL), "The reported invoices exist only in test-legal; pytest covers their stored state.");
  test.setTimeout(300_000);
  await reportedInvoicesJourney(page, request, baseURL, info, DESKTOP);
});

test("BUG-016 [prod-only] [mobile] the reported invoices download legible at 393px (read-only)", async (
  { page, request, baseURL }, info,
) => {
  test.skip(isLocal(baseURL), "The reported invoices exist only in test-legal; pytest covers their stored state.");
  test.setTimeout(300_000);
  await reportedInvoicesJourney(page, request, baseURL, info, MOBILE);
});
