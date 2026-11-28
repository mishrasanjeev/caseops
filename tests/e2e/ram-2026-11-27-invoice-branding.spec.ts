/**
 * ENH-001 (Ram, test-legal, 2026-11-27): "Generated invoices and receipts look
 * basic and do not have proper law firm branding. The logo, watermark,
 * authorised signature and document verification QR code are missing."
 *
 * Every assertion reads the downloaded PDF the way a person would: pdfjs
 * renders it on a canvas, each text run's contrast is measured, the images the
 * page paints are counted, and the QR code is decoded from the pixels with
 * jsQR. The decoded link is then opened in the browser and must show the same
 * document, and the fingerprint the verification page shows must be the
 * SHA-256 of the exact bytes downloaded.
 *
 * [local-only] The settings journey uploads a logo and a signature, names the
 * signatory, issues an invoice and checks all four branding elements. It
 * changes firm settings and issues a final invoice, so it never runs against
 * the tester's real tenant.
 *
 * Draft journey (local and production): a clock-stamped QA matter and draft
 * invoice are created through the UI, the PDF must carry the tenant's current
 * letterhead, the DRAFT watermark and a verifiable QR code, the draft is
 * voided through the product (the code must then read Revoked) and the QA
 * matter is disposed. The tester's branding settings are only read.
 */
import { readFile } from "node:fs/promises";
import { deflateSync, crc32 } from "node:zlib";

import { expect, test, type APIRequestContext, type Page, type TestInfo } from "@playwright/test";

import {
  compact, printedVerificationLink, proveBillingPdf, type BillingPdfProof,
} from "./support/billing-pdf-proof";
import {
  expectNoPageOverflow, expectOnScreen, json, markPositive, prepareTester, stamp, type TesterRuntime,
} from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const DESKTOP = { width: 1440, height: 900 };
const MOBILE = { width: 393, height: 851 };
const MIN_CONTRAST = 4.5;
const isLocal = (baseURL: string | undefined) =>
  ["localhost", "127.0.0.1", "[::1]"].includes(new URL(baseURL ?? process.env.CASEOPS_WEB_BASE_URL ?? "https://caseops.ai").hostname);
/** Matter codes and invoice numbers accept letters, digits and hyphens only. */
const stampedCode = (prefix: string) => stamp(prefix).replace(/[^A-Za-z0-9]+/g, "-").toUpperCase();

/** A small RGBA PNG drawn by `paint`, encoded without any image library. */
function png(width: number, height: number, paint: (x: number, y: number) => [number, number, number, number]): Buffer {
  const rows = Buffer.alloc((width * 4 + 1) * height);
  for (let y = 0; y < height; y += 1) {
    rows[y * (width * 4 + 1)] = 0;
    for (let x = 0; x < width; x += 1) {
      const offset = y * (width * 4 + 1) + 1 + x * 4;
      const [r, g, b, a] = paint(x, y);
      rows[offset] = r; rows[offset + 1] = g; rows[offset + 2] = b; rows[offset + 3] = a;
    }
  }
  const chunk = (type: string, body: Buffer) => {
    const length = Buffer.alloc(4);
    length.writeUInt32BE(body.length);
    const typed = Buffer.concat([Buffer.from(type, "ascii"), body]);
    const crc = Buffer.alloc(4);
    crc.writeUInt32BE(crc32(typed));
    return Buffer.concat([length, typed, crc]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(width, 0);
  header.writeUInt32BE(height, 4);
  header[8] = 8; header[9] = 6; header[10] = 0; header[11] = 0; header[12] = 0;
  return Buffer.concat([
    Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]),
    chunk("IHDR", header), chunk("IDAT", deflateSync(rows)), chunk("IEND", Buffer.alloc(0)),
  ]);
}

const LOGO = png(480, 200, (x, y) => {
  const inside = (x - 120) ** 2 / 90 ** 2 + (y - 100) ** 2 / 80 ** 2 <= 1;
  return inside || (x > 240 && x < 460 && y > 70 && y < 130) ? [24, 52, 110, 255] : [255, 255, 255, 0];
});
const SIGNATURE = png(420, 120, (x, y) =>
  Math.abs(y - (60 + 35 * Math.sin(x / 30))) < 4 ? [15, 23, 80, 255] : [255, 255, 255, 0]);

async function pageJson(response: { status(): number; json(): Promise<any> }, operation: string): Promise<any> {
  expect(response.status(), `${operation} returned ${response.status()}`).toBe(200);
  return response.json();
}

async function createQaMatterThroughUi(page: Page, rt: TesterRuntime): Promise<{ id: string; code: string }> {
  const code = stampedCode("QAE001");
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.locator("main").getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog", { name: "New matter" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Title").fill(stamp("ENH001 QA branding matter"));
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Banking");
  await dialog.getByLabel("Client name").fill("Synthetic QA client");
  await dialog.getByLabel("Opposing party").fill("Synthetic QA respondent");
  const created = page.waitForResponse(r => new URL(r.url()).pathname === "/api/matters/" && r.request().method() === "POST");
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await pageJson(await created, "Create the QA matter through the New matter dialog");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return { id: matter.id as string, code };
}

async function disposeQaMatterThroughUi(page: Page, rt: TesterRuntime, matterId: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  const trigger = page.getByTestId("matter-dispose-trigger");
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  await page.getByTestId("matter-lifecycle-reason").fill("ENH-001 invoice branding journey complete; retiring the synthetic QA matter.");
  const disposed = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status` && r.request().method() === "PATCH");
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await pageJson(await disposed, "Dispose the QA matter")).status).toBe("disposed");
}

async function createDraftThroughDialog(page: Page, matterId: string, invoiceNumber: string, description: string) {
  const trigger = page.getByTestId("new-invoice-trigger");
  await trigger.scrollIntoViewIfNeeded();
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Create a draft invoice" });
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Invoice number (optional)").fill(invoiceNumber);
  await dialog.getByLabel("Include uninvoiced billable time on this matter.").uncheck();
  await dialog.getByTestId("new-invoice-add-item").click();
  await dialog.getByLabel("Line 1 description").fill(description);
  await dialog.getByLabel("Line 1 amount").fill("175000");
  const submit = dialog.getByTestId("new-invoice-submit");
  await submit.scrollIntoViewIfNeeded();
  const created = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matterId}/invoices`
    && r.request().method() === "POST");
  await submit.click();
  const invoice = await pageJson(await created, "Create draft invoice through the dialog");
  expect(invoice.status).toBe("draft");
  expect(invoice.invoice_number).toBe(invoiceNumber);
  return invoice;
}

async function downloadPdf(page: Page, matterId: string, invoiceId: string, label: string): Promise<Buffer> {
  const button = page.getByTestId(`invoice-pdf-${invoiceId}`);
  await button.scrollIntoViewIfNeeded();
  await expect(button).toHaveText(label);
  await expectOnScreen(button, `${label} action is on screen`);
  // The first PDF of a cold API instance imports fpdf2 lazily (measured 31.8 s).
  const response = page.waitForResponse(r =>
    new URL(r.url()).pathname === `/api/matters/${matterId}/invoices/${invoiceId}/download`, { timeout: 60_000 });
  const download = page.waitForEvent("download", { timeout: 60_000 });
  await button.click();
  expect((await response).status()).toBe(200);
  return readFile((await (await download).path())!);
}

function expectLegible(proof: BillingPdfProof) {
  expect(proof.pages, "one page with no blank trailing page").toBe(1);
  const illegible = proof.runs.filter(run => run.contrast < MIN_CONTRAST).map(run => `${run.text} (${run.contrast.toFixed(2)})`);
  expect(illegible, "every text run reaches WCAG AA contrast over the watermark").toEqual([]);
  expect(proof.runs.filter(run => !run.inside).map(run => run.text)).toEqual([]);
}

/** Opens the decoded QR link and checks the page against the downloaded bytes. */
async function verifyThroughQr(page: Page, proof: BillingPdfProof, file: Buffer, expected: {
  number: string; issuer: string; status: string; state: "Genuine document" | "Not an issued document" | "Revoked";
}) {
  expect(proof.qr, "a QR code is decoded from the rendered page").not.toBeNull();
  expect(proof.qr, "the QR code and the printed link are the same").toBe(printedVerificationLink(proof.text));
  const response = page.waitForResponse(r => new URL(r.url()).pathname.startsWith("/api/verify/billing-documents/"));
  await page.goto(proof.qr!);
  expect((await response).status()).toBe(200);
  await expect(page.getByTestId("verify-state")).toContainText(expected.state);
  if (expected.state !== "Genuine document") {
    // ENH-001 review: a draft or revoked copy is never called genuine.
    await expect(page.getByTestId("verify-state")).not.toContainText("Genuine document");
  }
  await expect(page.getByTestId("verify-number")).toHaveText(expected.number);
  await expect(page.getByTestId("verify-issued-by")).toHaveText(expected.issuer);
  await expect(page.getByTestId("verify-status-now")).toHaveText(expected.status);
  await expect(page.getByTestId("verify-sha256")).toHaveText(proof.sha256);
  await page.getByTestId("verify-file-input").setInputFiles({ name: `${expected.number}.pdf`, mimeType: "application/pdf", buffer: file });
  await expect(page.getByTestId("verify-file-result")).toHaveText(expected.state === "Not an issued document"
    ? `${expected.number}.pdf is the file generated for this link, unchanged. It is still not an issued document.`
    : `${expected.number}.pdf is the issued file, unchanged.`);
  await expectNoPageOverflow(page);
}

async function brandingOracle(rt: TesterRuntime, request: APIRequestContext) {
  return json(await request.get(`${rt.api.origin}/api/admin/document-branding`, { headers: rt.headers }),
    "Read the firm's document branding (read-only)");
}

async function settingsJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo) {
  const rt = await prepareTester(page, request, baseURL, DESKTOP);
  const firm = `Gupta Legal Chambers LLP ${rt.run}`;
  await page.goto(`${rt.web.origin}/app/admin/matter-billing`);
  await page.getByLabel("Firm legal name", { exact: true }).fill(firm);
  await page.getByLabel("GSTIN", { exact: true }).fill("07ABCDE1234F1Z5");
  await page.getByLabel("PAN", { exact: true }).fill("ABCDE1234F");
  await page.getByLabel("Firm address", { exact: true }).fill("Chamber 12, Delhi High Court, New Delhi 110003");
  const profileSaved = page.waitForResponse(r => new URL(r.url()).pathname.startsWith("/api/admin/matter-billing")
    && ["POST", "PATCH"].includes(r.request().method()));
  await page.getByRole("button", { name: "Save default profile" }).click();
  await pageJson(await profileSaved, "Save the default billing profile");

  const card = page.getByTestId("document-branding-card");
  await card.scrollIntoViewIfNeeded();
  await expect(card.getByTestId("branding-letterhead")).toContainText(firm);
  for (const [kind, buffer] of [["logo", LOGO], ["signature", SIGNATURE]] as const) {
    const uploaded = page.waitForResponse(r => new URL(r.url()).pathname === `/api/admin/document-branding/${kind}`
      && r.request().method() === "PUT");
    await card.getByTestId(`branding-${kind}-input`).setInputFiles({ name: `${kind}.png`, mimeType: "image/png", buffer });
    expect((await pageJson(await uploaded, `Upload the ${kind}`))[`has_${kind}`]).toBe(true);
    await expect(card.getByTestId(`branding-${kind}-preview`)).toBeVisible();
  }
  await card.getByTestId("branding-signatory-name").fill("Ram Gupta");
  await card.getByTestId("branding-signatory-designation").fill("Managing Partner");
  const saved = page.waitForResponse(r => new URL(r.url()).pathname === "/api/admin/document-branding"
    && r.request().method() === "PATCH");
  await card.getByTestId("branding-save").click();
  expect((await pageJson(await saved, "Save the signatory")).signatory_name).toBe("Ram Gupta");
  await page.reload();
  await expect(page.getByTestId("branding-signatory-name")).toHaveValue("Ram Gupta");
  await expect(page.getByTestId("branding-logo-preview")).toBeVisible();
  await markPositive(info, "enh001-branding-settings-saved", { firm });

  const matter = await createQaMatterThroughUi(page, rt);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  const invoice = await createDraftThroughDialog(page, matter.id, stampedCode("QA-E001-ISSUE"), stamp("ENH001 drafting charges"));
  await page.getByTestId(`invoice-issue-${invoice.id}`).click();
  const issued = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matter.id}/invoices/${invoice.id}/issue`);
  await page.getByTestId(`invoice-issue-confirm-${invoice.id}`).click();
  expect((await pageJson(await issued, "Issue the draft")).status).toBe("issued");

  const file = await downloadPdf(page, matter.id, invoice.id, "PDF");
  const proof = await proveBillingPdf(page.context(), file);
  expectLegible(proof);
  const text = compact(proof.text);
  for (const expected of [firm, "GSTIN: 07ABCDE1234F1Z5 | PAN: ABCDE1234F", `For ${firm}`, "Ram Gupta",
    "Managing Partner | Authorised signatory", "Verify this document", "Status: Issued"]) {
    expect(text, expected).toContain(compact(expected));
  }
  expect(proof.imagesPerPage, "watermark, logo, QR code and signature are painted").toEqual([4]);
  expect(proof.qr!.startsWith(`${rt.web.origin}/verify/`)).toBe(true);
  await markPositive(info, "enh001-issued-pdf-branded", { invoice_id: invoice.id, images: proof.imagesPerPage });
  await verifyThroughQr(page, proof, file, {
    number: invoice.invoice_number, issuer: firm, status: "Issued", state: "Genuine document",
  });
  await markPositive(info, "enh001-issued-qr-verified", { invoice_id: invoice.id });
  await disposeQaMatterThroughUi(page, rt, matter.id);
  await rt.release();
}

async function draftJourney(page: Page, request: APIRequestContext, baseURL: string | undefined, info: TestInfo,
  viewport: { width: number; height: number }) {
  const rt = await prepareTester(page, request, baseURL, viewport);
  const branding = await brandingOracle(rt, request);
  const issuer: string = branding.letterhead.issuer_name;
  const matter = await createQaMatterThroughUi(page, rt);
  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  const invoice = await createDraftThroughDialog(page, matter.id, stampedCode("QA-E001"), stamp("ENH001 drafting charges"));
  const file = await downloadPdf(page, matter.id, invoice.id, "Draft PDF");
  const proof = await proveBillingPdf(page.context(), file);
  expectLegible(proof);
  const text = compact(proof.text);
  for (const expected of [issuer, "DRAFT - NOT A TAX INVOICE", "Status: Draft", "Verify this document",
    "The signature is applied when the invoice is issued."]) {
    expect(text, expected).toContain(compact(expected));
  }
  for (const line of branding.letterhead.detail_lines as string[]) expect(text, line).toContain(compact(line));
  // A draft never carries the signature: watermark + QR, plus the logo when the firm has one.
  expect(proof.imagesPerPage).toEqual([(branding.has_logo ? 1 : 0) + 2]);
  await markPositive(info, "enh001-draft-pdf-branded", { invoice_id: invoice.id, has_logo: branding.has_logo });
  await verifyThroughQr(page, proof, file, {
    number: invoice.invoice_number, issuer, status: "Draft (not issued)", state: "Not an issued document",
  });
  await expect(page.getByTestId("verify-state")).toContainText(
    "This copy was generated as: Draft (not issued). It is not an issued document");

  await page.goto(`${rt.web.origin}/app/matters/${matter.id}/billing`);
  await page.getByTestId(`invoice-void-${invoice.id}`).click();
  const voided = page.waitForResponse(r => new URL(r.url()).pathname === `/api/matters/${matter.id}/invoices/${invoice.id}/void`);
  await page.getByTestId(`invoice-void-confirm-${invoice.id}`).click();
  expect((await pageJson(await voided, "Void the draft")).status).toBe("void");
  await page.goto(proof.qr!);
  await expect(page.getByTestId("verify-state")).toContainText("Revoked");
  await expect(page.getByTestId("verify-state")).toContainText("The invoice was voided.");
  await expect(page.getByTestId("verify-status-now")).toHaveText("Void (cancelled)");
  await markPositive(info, "enh001-void-revokes-qr", { invoice_id: invoice.id });
  expect(await brandingOracle(rt, request), "the tester's branding settings are only read").toEqual(branding);
  await disposeQaMatterThroughUi(page, rt, matter.id);
  await rt.release();
}

test("ENH-001 [local-only] admin uploads a logo and signature and the issued invoice carries both with a verifiable QR code", async (
  { page, request, baseURL }, info,
) => {
  test.skip(!isLocal(baseURL), "Changes firm branding and issues a final invoice; never in the tester's tenant.");
  test.setTimeout(360_000);
  await settingsJourney(page, request, baseURL, info);
});

test("ENH-001 draft invoice PDF carries the letterhead, DRAFT watermark and a QR code that verifies until voided", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(360_000);
  await draftJourney(page, request, baseURL, info, DESKTOP);
});

test("ENH-001 [mobile] draft invoice QR code verifies and the verification page fits a phone", async (
  { page, request, baseURL }, info,
) => {
  test.setTimeout(360_000);
  await draftJourney(page, request, baseURL, info, MOBILE);
});
