/**
 * BUG-016 (Ram, CaseOps_Bugs (4).xlsx, 2026-10-30): invoice PDF line items and
 * details were unreadable (dark text on a dark fill) and every invoice carried
 * a blank second page.
 *
 * Signed in as the reporting tester, the journey creates a draft invoice with
 * clock-stamped line items through the New invoice dialog, downloads it from
 * the billing page, and proves the downloaded file is a legible one-page draft:
 * pdfjs text extraction finds every line item, and an in-browser raster of the
 * file (pdfjs rendered to a canvas) measures the WCAG contrast of every text
 * run against its own pixels. The draft is then voided through the product's
 * "Void draft" action so retained production data is retired.
 *
 * Local runs need a matter on the freshly bootstrapped tenant; it is created
 * through the API because matter creation is not the workflow under test.
 * Production uses the matter the tester reported (server identity).
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

const REPORTED_MATTER_ID = "56264441-dd0d-48e6-9c57-691892c63912";
const MIN_CONTRAST = 4.5;
const LONG_TAIL = "drafting and settling the written statement with a para-wise reply, the list of documents, "
  + "the affidavit of admission and denial and the application for condonation of delay before the "
  + "Commercial Division of the High Court of Delhi at New Delhi";

const compact = (value: string) => value.replace(/\s+/g, "");

async function pageJson(response: Response, operation: string): Promise<any> {
  expect(response.status(), `${operation} returned ${response.status()}`).toBe(200);
  return response.json();
}

async function matterFor(rt: TesterRuntime, request: APIRequestContext): Promise<string> {
  if (!rt.local) return REPORTED_MATTER_ID;
  const code = `B16-${Date.now().toString(36).toUpperCase()}`;
  const matter = await json(await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
    title: `Satish Kumar Mehani v Punjab National Bank ${rt.run}`, matter_code: code, client_name: "Punjab National Bank",
    opposing_party: "Respondent Ltd", practice_area: "Banking", forum_level: "high_court", court_name: "Delhi High Court",
    status: "intake",
  } }), "Local matter prerequisite");
  return matter.id as string;
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

/** Renders the PDF with pdfjs on a browser canvas and measures every text run's own pixels. */
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
      const lum = (d: Uint8ClampedArray, i: number) => 0.2126 * channel(d[i]) + 0.7152 * channel(d[i + 1]) + 0.0722 * channel(d[i + 2]);
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
          let low = 1;
          let high = 0;
          if (x1 - x0 >= 2 && y1 - y0 >= 2) {
            const pixels = ctx.getImageData(x0, y0, x1 - x0, y1 - y0).data;
            for (let i = 0; i < pixels.length; i += 4) {
              const value = lum(pixels, i);
              if (value < low) low = value;
              if (value > high) high = value;
            }
          }
          const [, , , , tx, ty] = item.transform;
          runs.push({
            page: number, text: item.str,
            contrast: high >= low ? (high + 0.05) / (low + 0.05) : 1,
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

async function draftInvoiceJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, baseURL, viewport);
  const matterId = await matterFor(rt, request);
  const lines = [stamp("BUG016 drafting charges"), `${stamp("BUG016 pleadings")} ${LONG_TAIL}`];

  await page.goto(`${rt.web.origin}/app/matters/${matterId}/billing`);
  const trigger = page.getByTestId("new-invoice-trigger");
  await trigger.scrollIntoViewIfNeeded();
  await expectOnScreen(trigger, "New invoice is reachable on the billing page");
  await expectNoPageOverflow(page);
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "New invoice" });
  await expect(dialog).toBeVisible();
  // Real uninvoiced time on the tester's matter must not be swept into a test draft.
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
  expect(invoice.line_items.map((line: { description: string }) => line.description)).toEqual(lines);
  await expect(page.getByText("Draft invoice created")).toBeVisible();

  const pdfButton = page.getByTestId(`invoice-pdf-${invoice.id}`);
  await pdfButton.scrollIntoViewIfNeeded();
  await expect(pdfButton).toHaveText("Draft PDF");
  await expectOnScreen(pdfButton, "Draft PDF action is on screen");
  await expectNoPageOverflow(page);
  // The API imports fpdf2 lazily on its first PDF; measured 31.8 s cold on the
  // shared Windows host (and a Cloud Run cold instance pays it too), so the
  // first download gets one bounded allowance instead of the 15 s action default.
  const downloadResponse = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/invoices/${invoice.id}/download`, { timeout: 60_000 });
  const download = page.waitForEvent("download", { timeout: 60_000 });
  await pdfButton.click();
  const response = await downloadResponse;
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("application/pdf");
  const file = await readFile((await (await download).path())!);
  expect(file.subarray(0, 5).toString()).toBe("%PDF-");

  const pages = await pdfText(file);
  expect(pages, "a one-page draft has no blank trailing page").toHaveLength(1);
  const text = compact(pages.join(" "));
  for (const description of lines) expect(text, `line item ${description}`).toContain(compact(description));
  expect(text).toContain(compact("DRAFT - NOT A TAX INVOICE"));
  expect(text).toContain(compact("Status: Draft"));
  expect(text).toContain(compact("Page 1 of 1"));
  expect(text).not.toContain("TaxInvoice/Receipt");

  const raster = await rasterRuns(page.context(), file);
  expect(raster.pages).toBe(1);
  expect(raster.runs.length).toBeGreaterThan(20);
  const illegible = raster.runs.filter(run => run.contrast < MIN_CONTRAST).map(run => `${run.text} (${run.contrast.toFixed(2)})`);
  expect(illegible, "every text run reaches WCAG AA contrast against its own fill").toEqual([]);
  expect(raster.runs.filter(run => !run.inside).map(run => run.text)).toEqual([]);
  const lineRuns = raster.runs.filter(run => lines.some(line => compact(line).includes(compact(run.text))));
  expect(lineRuns.length).toBeGreaterThanOrEqual(lines.length);
  await markPositive(info, "bug016-draft-invoice-pdf-legible", {
    invoice_id: invoice.id, invoice_number: invoice.invoice_number, runs: raster.runs.length,
    min_contrast: Math.min(...raster.runs.map(run => run.contrast)),
  });

  // Retire the draft through the product's own action.
  await page.getByTestId(`invoice-void-${invoice.id}`).click();
  const confirm = page.getByTestId(`invoice-void-confirm-${invoice.id}`);
  await expectOnScreen(confirm, "Confirm void is on screen");
  const voided = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/invoices/${invoice.id}/void`);
  await confirm.click();
  const record = await pageJson(await voided, "Void the draft through the billing page");
  expect(record.status).toBe("void");
  await expect(page.getByText(`Draft ${invoice.invoice_number} voided.`)).toBeVisible();
  await expect(page.getByTestId(`invoice-void-${invoice.id}`)).toHaveCount(0);
  const workspace = await json(await request.get(`${rt.api.origin}/api/matters/${matterId}/workspace`, { headers: rt.headers }),
    "Workspace read-back");
  expect(workspace.invoices.find((item: { id: string }) => item.id === invoice.id)?.status).toBe("void");
  await markPositive(info, "bug016-draft-voided", { invoice_id: invoice.id });
  await rt.release();
}

test("BUG-016 draft invoice PDF downloaded from the billing page is legible, one page and marked DRAFT", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(240_000);
  await draftInvoiceJourney(page, request, baseURL, info, { width: 1440, height: 900 });
});

test("BUG-016 [mobile] draft invoice PDF journey works at 393px without page overflow", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(240_000);
  await draftInvoiceJourney(page, request, baseURL, info, { width: 393, height: 851 });
});
