/**
 * Tester workbook 27 Nov 2026, BUG-001 (test-legal, Ram): "OCR is not working
 * for JPG and PNG images ... displays 'Sarvam OCR could not read the pages
 * (page_missing)'. Expected: read JPG, JPEG and PNG and display extracted text."
 *
 * The tester's steps, through the UI: Matter > Documents > Upload an image
 * that contains text > OCR & Translate > choose the source language > Start,
 * then read the status and open Versions.
 *
 * Local (loopback) runs end with the extracted text on screen: the API is the
 * e2e entrypoint, whose offline Sarvam double (tests/e2e/support/oauth/
 * sarvam_ocr_emulator.py) answers in the documented archive layout named after
 * the uploaded file -- the layout that produced page_missing for images.
 *
 * Production runs carry the no-paid-provider marker, so Sarvam is never called
 * (by design, a request with the marker cannot spend). There the journey proves
 * each image is offered OCR, decoded and handed to the provider boundary, which
 * reports the explicit no-paid block instead of page_missing. Reading the text
 * in production needs a human-signed-in run; this spec does not claim it.
 *
 * Production needs CASEOPS_EXPECTED_RELEASE_SHA, CASEOPS_RAM_PROD_EMAIL and
 * CASEOPS_RAM_PROD_PASSWORD (never committed). Missing setup fails; nothing
 * here skips. Each run creates one Matter and three small images named with a
 * clock+serial stamp, because production tenants retain every run.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Browser, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const OFFLINE_OCR_TEXT = /OFFLINE SARVAM OCR\. ORDER dated 12\.03\.2023\. Page 1 of pages-1-1\.(?:png|jpg)\./;
const NO_PAID_MESSAGE = "Paid OCR is disabled for automated verification; no external request was made.";

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle and local-seeding headers only; the journey acts through the UI. */
  headers: Record<string, string>;
};
type Rendition = {
  id: string;
  kind: "ocr" | "translation";
  status: string;
  error_code: string | null;
  error_message: string | null;
  page_count: number;
  pages_ok: number;
};

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

async function runtime(baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
  const web = new URL(baseURL ?? required("CASEOPS_WEB_BASE_URL"));
  const local = loopback(web);
  const api = new URL(local ? `http://${web.hostname}:${process.env.CASEOPS_E2E_API_PORT ?? "8000"}`
    : required("PROD_API_BASE_URL"));
  if (!local && (web.origin !== "https://caseops.ai" || api.origin !== "https://api.caseops.ai")) {
    throw new Error("Remote acceptance requires the canonical production origins.");
  }
  const sha = local ? (process.env.CASEOPS_RELEASE_SHA?.trim() || e2eEnv.CASEOPS_RELEASE_SHA)
    : required("CASEOPS_EXPECTED_RELEASE_SHA");
  await assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  const credentials: TesterCredentials = local
    ? { slug: `ocr27-${randomUUID()}`, email: `ram-${randomUUID()}@example.com`, password: `Synthetic!${randomUUID()}` }
    : { slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal", email: required("CASEOPS_RAM_PROD_EMAIL"),
      password: required("CASEOPS_RAM_PROD_PASSWORD") };
  if (!local && credentials.slug !== "test-legal") {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  if (local) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Test Legal LLP", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Ram Gupta", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(
    await request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
      data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } }),
    "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
  if (local) {
    // Readiness refuses OCR until a verified Sarvam page price exists.
    await json(await request.post(`${api.origin}/_e2e/sarvam-ocr/cost-profile`, { headers }),
      "Local verified OCR price");
  }
  return { web, api, local, credentials, headers };
}

/** A scanned-looking page with printed text, encoded by the browser itself. */
async function textImage(browser: Browser, type: "png" | "jpeg"): Promise<Buffer> {
  const scratch = await browser.newPage({ viewport: { width: 620, height: 877 } });
  try {
    await scratch.setContent(`<!doctype html><html><body style="margin:0;background:#fff">
      <main style="font:22px Georgia,serif;color:#111;padding:56px">
        <h1 style="font-size:30px">IN THE HIGH COURT OF DELHI AT NEW DELHI</h1>
        <p>ORDER dated 12.03.2023</p>
        <p>The petitioner shall pay Rs. 5,00,000 within four weeks. List on 15.04.2023.</p>
      </main></body></html>`);
    return type === "png" ? await scratch.screenshot({ type: "png" })
      : await scratch.screenshot({ type: "jpeg", quality: 90 });
  } finally {
    await scratch.close();
  }
}

async function createRunMatter(request: APIRequestContext, rt: Runtime, run: string): Promise<string> {
  const code = run.replace(/\s+/g, "-").slice(0, 60);
  const matter = await json<{ id: string; matter_code: string }>(
    await request.post(`${rt.api.origin}/api/matters/`, { headers: rt.headers, data: {
      matter_code: code, title: `OCR image acceptance ${run}`, practice_area: "Commercial Litigation",
      forum_level: "high_court", status: "intake",
    } }), "Run matter");
  expect(matter.matter_code).toBe(code);
  return matter.id;
}

async function uploadThroughUi(page: Page, rt: Runtime, matterId: string, file: {
  name: string; mimeType: string; buffer: Buffer;
}): Promise<string> {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}/documents`);
  const uploaded = page.waitForResponse((response) => response.request().method() === "POST"
    && new URL(response.url()).pathname === `/api/matters/${matterId}/attachments`);
  await page.getByTestId("matter-attachment-file-input").setInputFiles(file);
  const response = await uploaded;
  const attachment = await json<{ id: string; original_filename: string }>(response, `Upload ${file.name}`);
  expect(attachment.original_filename).toBe(file.name);
  return attachment.id;
}

async function latestOcr(request: APIRequestContext, rt: Runtime, matterId: string, attachmentId: string) {
  const listing = await json<{ renditions: Rendition[] }>(await request.get(
    `${rt.api.origin}/api/matters/${matterId}/attachments/${attachmentId}/renditions`, { headers: rt.headers }),
  "Rendition oracle");
  return listing.renditions.find((item) => item.kind === "ocr");
}

const CASES = [
  { label: "JPG", extension: "jpg", type: "jpeg", mimeType: "image/jpeg" },
  { label: "JPEG", extension: "jpeg", type: "jpeg", mimeType: "image/jpeg" },
  { label: "PNG", extension: "png", type: "png", mimeType: "image/png" },
] as const;

for (const item of CASES) {
  test(`BUG-001 OCR reads an uploaded ${item.label} image instead of page_missing`, async ({
    page, request, browser, baseURL,
  }) => {
    // Production drains rendition jobs on the document-processing cadence.
    test.setTimeout(420_000);
    const rt = await runtime(baseURL, request);
    const run = stamp(`OCR27-${item.label}`);
    const matterId = await createRunMatter(request, rt, run);
    const name = `${run.replace(/\s+/g, "-")}-order.${item.extension}`;
    const buffer = await textImage(browser, item.type);

    await signIn(page, { web: rt.web }, rt.credentials);
    const attachmentId = await uploadThroughUi(page, rt, matterId, { name, mimeType: item.mimeType, buffer });

    // The image row offers OCR & Translate, and the dialog does not warn that
    // only text-layer pages will be read (an image has no text layer).
    const ocrButton = page.getByTestId(`matter-attachment-ocr-${attachmentId}`);
    await expect(ocrButton).toHaveAccessibleName(`OCR & Translate ${name}`);
    await ocrButton.click();
    const dialog = page.getByTestId("ocr-translate-dialog");
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId("ocr-source-language")).toBeEnabled();
    await expect(dialog.getByTestId("ocr-provider-unavailable")).toHaveCount(0);
    await dialog.getByTestId("ocr-source-language").selectOption("en");
    const started = page.waitForResponse((response) => response.request().method() === "POST"
      && new URL(response.url()).pathname === `/api/matters/${matterId}/attachments/${attachmentId}/renditions`);
    await dialog.getByTestId("ocr-translate-start").click();
    expect((await started).status(), "OCR request accepted").toBe(202);

    // Server identity: the rendition of this attachment, not a row by name.
    await expect.poll(async () => (await latestOcr(request, rt, matterId, attachmentId))?.status,
      { timeout: rt.local ? 120_000 : 300_000, message: "OCR reaches a final state" })
      .toMatch(/^(ocr_completed|review_required|failed)$/);
    const ocr = await latestOcr(request, rt, matterId, attachmentId);
    expect(ocr?.error_code ?? "").not.toBe("provider_page_missing");
    expect(ocr?.error_message ?? "").not.toContain("page_missing");

    const status = page.getByTestId(`matter-attachment-rendition-status-${attachmentId}`);
    if (rt.local) {
      expect(ocr).toMatchObject({ status: "ocr_completed", error_code: null, page_count: 1, pages_ok: 1 });
      await expect(status).toHaveText("OCR completed", { timeout: 30_000 });
    } else {
      // No-paid marker: the image was decoded and stopped at the paid boundary.
      expect(ocr).toMatchObject({ status: "failed", error_code: "paid_provider_blocked_for_test",
        error_message: NO_PAID_MESSAGE });
      await expect(status).toHaveText("OCR failed", { timeout: 30_000 });
    }

    // Open Versions from the row and read what the tester would read.
    const versions = page.getByTestId(`matter-attachment-versions-${attachmentId}`);
    await versions.click();
    await page.waitForURL(new RegExp(`/app/matters/${matterId}/documents/${attachmentId}/renditions`));
    await expect(page.getByTestId("renditions-filename")).toContainText(name);
    await expect(page.locator("body")).not.toContainText("page_missing");
    if (rt.local) {
      await expect(page.getByTestId("renditions-ocr-text")).toContainText(OFFLINE_OCR_TEXT);
      await expect(page.getByTestId("renditions-error")).toHaveCount(0);
    } else {
      await expect(page.getByTestId("renditions-error")).toHaveText(NO_PAID_MESSAGE);
    }
  });
}
