/**
 * Tester workbook dated 27 Nov 2026, BUG-003 (High, Ram, test-legal):
 * "The KYC form only asks users to enter document names or numbers. There is
 * no option to upload actual KYC documents, so the admin cannot check the
 * documents submitted by the client."
 *
 * Expected: users upload PAN, Aadhaar / address proof and other KYC documents;
 * the admin views and verifies each uploaded document before approving or
 * rejecting the KYC.
 *
 * The journey signs in as the reporting tester through the sign-in page,
 * creates its own clock+serial client through the Clients page, then on
 * /app/clients/<id> uploads a PAN (PDF) and a masked Aadhaar (PDF) as files,
 * submits, rejects as the reviewer after opening the Aadhaar, uses
 * "Re-submit verification" to replace the Aadhaar with a masked Aadhaar image,
 * re-submits, opens each document inline (asserting the exact uploaded bytes
 * come back and that the PDF actually renders: page canvas and text, not just
 * a frame element), marks each reviewed and approves. API calls are oracles
 * only; before each open, an oracle approval naming every file must be refused
 * by the server (review round 2: the server, not the tick box, enforces "open
 * each file before approving").
 * The client it created is archived in a finally block; reviewed KYC files
 * stay retained under the archived client as decision evidence.
 *
 * Production runs need CASEOPS_EXPECTED_RELEASE_SHA and the tester's
 * credentials in CASEOPS_RAM_PROD_EMAIL / CASEOPS_RAM_PROD_PASSWORD (never
 * committed). The tester's role must hold clients:kyc_submit and
 * clients:kyc_review; missing setup or capability fails, nothing skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page, type Response } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const DESKTOP = { width: 1365, height: 900 };

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. The UI journey never uses them to act as the user. */
  headers: Record<string, string>;
};
type KycDocument = { id: string; document_type: string; original_filename: string; review_decision: string | null };
type KycList = { kyc_status: string; documents: KycDocument[]; requirements_met: boolean };

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

/** A small, well-formed PDF whose single page carries a visible label. */
function syntheticPdf(label: string): Buffer {
  const text = `BT /F1 18 Tf 72 720 Td (${label.replace(/[()\\]/g, "")}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    `<< /Length ${text.length} >>\nstream\n${text}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let body = "%PDF-1.4\n";
  const offsets: number[] = [];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(body));
    body += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xref = Buffer.byteLength(body);
  body += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  body += offsets.map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`).join("");
  body += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(body, "latin1");
}

// 1x1 opaque PNG: a decodable image the reviewer's inline preview must render.
const MASKED_AADHAAR_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
  "base64",
);

async function runtimeFor(baseURL: string | undefined, request: APIRequestContext): Promise<Runtime> {
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
  const credentials: TesterCredentials = local ? {
    slug: process.env.CASEOPS_RAM_LOCAL_SLUG?.trim() || `nov27-kyc-${randomUUID()}`,
    email: process.env.CASEOPS_RAM_LOCAL_EMAIL?.trim() || `ram-${randomUUID()}@example.com`,
    password: process.env.CASEOPS_RAM_LOCAL_PASSWORD?.trim() || `Synthetic!${randomUUID()}`,
  } : {
    slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal",
    email: required("CASEOPS_RAM_PROD_EMAIL"),
    password: required("CASEOPS_RAM_PROD_PASSWORD"),
  };
  if (!local && credentials.slug !== "test-legal") {
    throw new Error("Production acceptance runs only in the reporting tester's own workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Test Legal LLP", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Ram Kumar", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  const headers = { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` };
  const me = await json<{ capabilities: string[] }>(
    await request.get(`${api.origin}/api/auth/me`, { headers }), "Tester capabilities");
  for (const capability of ["clients:create", "clients:kyc_submit", "clients:kyc_review", "clients:archive"]) {
    expect(me.capabilities, `The reporting tester's role must hold ${capability}`).toContain(capability);
  }
  return { web, api, local, credentials, headers };
}

async function kycList(request: APIRequestContext, rt: Runtime, clientId: string): Promise<KycList> {
  return json<KycList>(await request.get(`${rt.api.origin}/api/clients/${clientId}/kyc/documents`,
    { headers: rt.headers }), "KYC documents oracle");
}

const isRequest = (method: string, pattern: RegExp) => (r: Response) =>
  r.request().method() === method && pattern.test(new URL(r.url()).pathname);

async function createClientThroughUi(page: Page, rt: Runtime, name: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/clients`);
  await page.locator("header").filter({ has: page.getByRole("heading", { name: "Clients & engagements" }) })
    .getByTestId("new-client-open").click();
  const dialog = page.getByRole("dialog");
  await dialog.getByTestId("new-client-name").fill(name);
  const created = page.waitForResponse(isRequest("POST", /^\/api\/clients\/?$/));
  await dialog.getByTestId("new-client-submit").click();
  const client = await json<{ id: string; name: string }>(await created, "Create client through the Clients page");
  expect(client.name).toBe(name);
  await expect(dialog).toBeHidden();
  return client.id;
}

async function uploadThroughUi(page: Page, clientId: string, type: string, file: {
  name: string; mimeType: string; buffer: Buffer;
}): Promise<KycDocument> {
  const panel = page.getByTestId("kyc-panel");
  await panel.getByTestId("kyc-upload-type").selectOption(type);
  await panel.getByTestId("kyc-upload-file").setInputFiles(file);
  const uploaded = page.waitForResponse(isRequest("POST", new RegExp(`^/api/clients/${clientId}/kyc/documents$`)));
  await panel.getByTestId("kyc-upload-submit").click();
  const doc = await json<KycDocument>(await uploaded, `Upload ${type}`, 201);
  expect(doc.document_type).toBe(type);
  await expect(panel.locator(`[data-testid="kyc-document-row"][data-document-id="${doc.id}"]`))
    .toContainText(file.name);
  return doc;
}

/** Server oracle: an approval naming every current file is refused while any
 * of them is unopened by this reviewer, and the refusal names exactly those. */
async function expectApprovalRefusedUnopened(request: APIRequestContext, rt: Runtime, clientId: string,
  ids: string[], unopened: string[], opened: string[]) {
  const response = await request.post(`${rt.api.origin}/api/clients/${clientId}/kyc/verify`,
    { headers: rt.headers, data: { reviewed_document_ids: ids } });
  expect(response.status(), "Approval of unopened KYC files must be refused by the server").toBe(409);
  const detail = String(((await response.json()) as { detail?: unknown }).detail ?? "");
  expect(detail).toContain("Open each KYC document before you approve the pack.");
  for (const label of unopened) expect(detail).toContain(label);
  for (const label of opened) expect(detail).not.toContain(label);
  expect((await kycList(request, rt, clientId)).kyc_status).toBe("submitted");
}

/** Reviewer opens one document inline, sees the exact uploaded bytes, marks it reviewed. */
async function openAndMarkReviewed(page: Page, clientId: string, doc: KycDocument, expected: {
  label: string; bytes: Buffer; mediaType: string; image: boolean; text?: string;
}) {
  const panel = page.getByTestId("kyc-panel");
  const opened = page.waitForResponse((r) => r.request().method() === "GET"
    && new URL(r.url()).pathname === `/api/clients/${clientId}/kyc/documents/${doc.id}/download`
    && new URL(r.url()).searchParams.get("inline") === "true");
  await panel.getByRole("button", { name: `Open ${expected.label}`, exact: true }).click();
  const response = await opened;
  expect(response.status(), `Open ${expected.label}`).toBe(200);
  expect(response.headers()["content-type"]).toContain(expected.mediaType);
  expect(response.headers()["content-disposition"]).toMatch(/^inline/);
  expect(response.headers()["x-content-type-options"]).toBe("nosniff");
  expect(response.headers()["content-security-policy"]).toBe("default-src 'none'; frame-ancestors 'none'; sandbox");
  expect(Buffer.compare(await response.body(), expected.bytes), "The reviewer sees the uploaded bytes").toBe(0);
  const preview = panel.locator(`[data-testid="kyc-document-preview"][data-document-id="${doc.id}"]`);
  if (expected.image) {
    const image = preview.getByTestId("kyc-document-preview-image");
    await expect(image).toBeVisible();
    await expect.poll(() => image.evaluate((el: HTMLImageElement) => el.complete && el.naturalWidth)).toBeGreaterThan(0);
  } else {
    // The PDF renders through the shared pdf.js viewer: a painted page canvas
    // and the page's text. (A blob: iframe was blocked by the app CSP while
    // still "visible", so element visibility alone proved nothing.)
    const pdf = preview.getByTestId("kyc-document-preview-pdf");
    await expect(pdf.locator("iframe")).toHaveCount(0);
    const canvas = pdf.locator("canvas").first();
    await expect(canvas).toBeVisible();
    await expect.poll(() => canvas.evaluate((el: HTMLCanvasElement) => el.width * el.height)).toBeGreaterThan(0);
    if (expected.text) await expect(pdf.locator(".textLayer, .react-pdf__Page__textContent").first()).toContainText(expected.text);
  }
  const box = panel.getByRole("checkbox", { name: `Reviewed ${expected.label}`, exact: true });
  await expect(box).toBeEnabled();
  await box.check();
}

test("BUG-003 upload PAN and masked Aadhaar, re-submit, open each document and approve", async ({
  page, request, baseURL,
}, info) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(DESKTOP);
  await signIn(page, { web: rt.web }, rt.credentials);
  const clientName = stamp("Nov27 KYC Client");
  let clientId: string | undefined;
  try {
    clientId = await createClientThroughUi(page, rt, clientName);
    await page.goto(`${rt.web.origin}/app/clients/${clientId}`);
    const panel = page.getByTestId("kyc-panel");
    await expect(panel.getByRole("heading", { name: "KYC verification" })).toBeVisible();
    await expect(panel.getByTestId("kyc-documents-empty")).toBeVisible();

    // The form asks for files, not names; Submit explains what is missing.
    await panel.getByTestId("kyc-submit-toggle").click();
    await expect(panel.getByTestId("kyc-submit-docs")).toHaveCount(0);
    await expect(panel.getByTestId("kyc-upload-file")).toHaveAttribute("type", "file");
    await expect(panel.getByTestId("kyc-aadhaar-notice")).toContainText("masked Aadhaar");
    await expect(panel.getByTestId("kyc-submit")).toBeDisabled();
    await expect(panel.getByTestId("kyc-submit-blocked")).toContainText("PAN card");

    const panPdf = syntheticPdf(`Synthetic QA PAN ${clientName}`);
    const pan = await uploadThroughUi(page, clientId, "pan",
      { name: "pan-synthetic.pdf", mimeType: "application/pdf", buffer: panPdf });
    await expect(panel.getByTestId("kyc-submit-blocked")).toContainText("Masked Aadhaar, passport or another address proof");
    const firstAadhaar = await uploadThroughUi(page, clientId, "aadhaar_masked", {
      name: "aadhaar-masked-first.pdf", mimeType: "application/pdf",
      buffer: syntheticPdf("Synthetic QA masked Aadhaar XXXX XXXX 0000"),
    });
    await expect(panel.getByTestId("kyc-requirement-pan")).toContainText("on file");
    await expect(panel.getByTestId("kyc-requirement-identity_address_proof")).toContainText("on file");
    const submitted = page.waitForResponse(isRequest("POST", new RegExp(`^/api/clients/${clientId}/kyc/submit$`)));
    await panel.getByTestId("kyc-submit").click();
    expect((await json<{ kyc_status: string }>(await submitted, "Submit for review")).kyc_status).toBe("submitted");

    // Reviewer rejects after opening the Aadhaar: the tester's starting state.
    await expect(panel.getByTestId("kyc-verify")).toBeDisabled();
    await openAndMarkReviewed(page, clientId, firstAadhaar, {
      label: "Aadhaar (masked)", bytes: syntheticPdf("Synthetic QA masked Aadhaar XXXX XXXX 0000"),
      mediaType: "application/pdf", image: false, text: "Synthetic QA masked Aadhaar XXXX XXXX 0000",
    });
    await panel.getByTestId("kyc-reject-toggle").click();
    await panel.getByTestId("kyc-reject-reason").fill("Synthetic QA: replace the Aadhaar with a clearer masked copy.");
    const rejected = page.waitForResponse(isRequest("POST", new RegExp(`^/api/clients/${clientId}/kyc/reject$`)));
    await panel.getByTestId("kyc-reject").click();
    const rejectBody = (await rejected).request().postDataJSON() as { reviewed_document_ids: string[] };
    expect(rejectBody.reviewed_document_ids).toEqual([firstAadhaar.id]);

    // "Re-submit verification": replace the Aadhaar with a masked image and re-submit.
    const resubmit = panel.getByRole("button", { name: "Re-submit verification" });
    await expect(resubmit).toBeVisible();
    await resubmit.click();
    const removed = page.waitForResponse(isRequest("DELETE",
      new RegExp(`^/api/clients/${clientId}/kyc/documents/${firstAadhaar.id}$`)));
    await panel.getByRole("button", { name: "Remove Aadhaar (masked)", exact: true }).click();
    expect((await removed).status()).toBe(204);
    await expect(panel.getByTestId("kyc-submit")).toBeDisabled();
    const aadhaar = await uploadThroughUi(page, clientId, "aadhaar_masked",
      { name: "aadhaar-masked.png", mimeType: "image/png", buffer: MASKED_AADHAAR_PNG });
    await expect(panel.getByTestId("kyc-submit")).toBeEnabled();
    const resubmitted = page.waitForResponse(isRequest("POST", new RegExp(`^/api/clients/${clientId}/kyc/submit$`)));
    await panel.getByTestId("kyc-submit").click();
    expect((await json<{ kyc_status: string }>(await resubmitted, "Re-submit")).kyc_status).toBe("submitted");

    // Reload: the reviewer starts from the persisted pack, opens each file, approves.
    await page.reload();
    await expect(panel.getByTestId("kyc-document-row")).toHaveCount(2);
    const approve = panel.getByTestId("kyc-verify");
    await expect(approve).toBeDisabled();
    await expect(panel.getByTestId("kyc-verify-blocked")).toContainText("Open and mark every document reviewed");
    const panName = "PAN card (pan-synthetic.pdf)";
    const aadhaarName = "Aadhaar (masked) (aadhaar-masked.png)";
    await expectApprovalRefusedUnopened(request, rt, clientId, [pan.id, aadhaar.id], [panName, aadhaarName], []);
    await openAndMarkReviewed(page, clientId, pan, {
      label: "PAN card", bytes: panPdf, mediaType: "application/pdf", image: false,
      text: `Synthetic QA PAN ${clientName}`,
    });
    await expect(approve).toBeDisabled();
    // The rendered PDF preview fits a phone: no sideways page scroll at 393px.
    await page.setViewportSize({ width: 393, height: 851 });
    await expect(panel.locator(`[data-testid="kyc-document-preview"][data-document-id="${pan.id}"] canvas`).first())
      .toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth))
      .toBeLessThanOrEqual(0);
    await page.setViewportSize(DESKTOP);
    await expectApprovalRefusedUnopened(request, rt, clientId, [pan.id, aadhaar.id], [aadhaarName], [panName]);
    await openAndMarkReviewed(page, clientId, aadhaar, {
      label: "Aadhaar (masked)", bytes: MASKED_AADHAAR_PNG, mediaType: "image/png", image: true,
    });
    await expect(approve).toBeEnabled();
    const verified = page.waitForResponse(isRequest("POST", new RegExp(`^/api/clients/${clientId}/kyc/verify$`)));
    await approve.click();
    const verifyResponse = await verified;
    expect((verifyResponse.request().postDataJSON() as { reviewed_document_ids: string[] }).reviewed_document_ids
      .sort()).toEqual([pan.id, aadhaar.id].sort());
    expect((await json<{ kyc_status: string }>(verifyResponse, "Approve")).kyc_status).toBe("verified");
    await expect(panel.getByText("verified", { exact: true })).toBeVisible();

    // Server oracle: the approved pack is exactly the two reviewed files.
    const after = await kycList(request, rt, clientId);
    expect(after.kyc_status).toBe("verified");
    expect(after.documents.map((d) => [d.id, d.document_type, d.review_decision]).sort()).toEqual([
      [pan.id, "pan", "approved"], [aadhaar.id, "aadhaar_masked", "approved"],
    ].sort());
    await page.reload();
    await expect(panel.locator('[data-testid="kyc-document-row"]')).toHaveCount(2);
    await expect(panel.getByTestId("kyc-documents").getByText("approved")).toHaveCount(2);
    await info.attach("positive-bug003-kyc-approved", {
      body: JSON.stringify({ positive_executed: true, client_id: clientId, local: rt.local }, null, 2),
      contentType: "application/json",
    });
  } finally {
    if (clientId) {
      // Retire the journey's own client; reviewed KYC files stay as decision evidence.
      await page.goto(`${rt.web.origin}/app/clients/${clientId}`);
      const archived = page.waitForResponse(isRequest("DELETE", new RegExp(`^/api/clients/${clientId}$`)));
      await page.getByTestId("client-archive").click();
      expect((await json<{ is_active: boolean }>(await archived, "Archive the journey client")).is_active).toBe(false);
    }
  }
});
