/**
 * Tester workbook dated 27 Nov 2026 (Aishwarya, nova-legal), rows 2 and 3:
 *   2. "Notice Received form accepts incomplete details without validation."
 *   3. "Notice Sent form accepts incomplete details and invalid inputs."
 *
 * Each journey follows the tester's steps on /app/matters/<id>/notices: every
 * invalid submission must show its specific message on the field, send no
 * upload request and leave the server's notice count unchanged (API oracle).
 * Row 3 also proves the duplicate handling: identical bytes are refused with
 * a link to the existing notice, and same details offer an explicit override.
 *
 * Locally the spec bootstraps its own empty workspace. In production it signs
 * in as the test-legal tester (owner decision 2026-11-27: production journeys
 * run only as test-legal, CASEOPS_RAM_PROD_* from the CI secret), creates its
 * own clock+serial matter through the UI, and disposes that matter in a
 * finally block. Uploads carry the no-paid-provider header, so indexing uses
 * no paid provider. Production also needs CASEOPS_EXPECTED_RELEASE_SHA.
 * Missing setup fails; nothing here skips.
 */
import { randomUUID } from "node:crypto";
import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

import { noPaidProviderHeaders } from "./support/cost-controls";
import { e2eEnv } from "./support/env";
import { assertPublicReleaseIdentity } from "./support/public-release-identity";
import { json, signIn, stamp, type TesterCredentials } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", locale: "en-US",
  storageState: { cookies: [], origins: [] } });
test.describe.configure({ mode: "default", retries: 0 });

const loopback = (url: URL) => ["127.0.0.1", "localhost", "[::1]"].includes(url.hostname);
const DESKTOP = { width: 1365, height: 900 };

type Runtime = {
  web: URL;
  api: URL;
  local: boolean;
  credentials: TesterCredentials;
  /** API oracle headers. UI journeys never use them to act as the user. */
  headers: Record<string, string>;
  release: () => Promise<void>;
};
type NoticeAttachment = { id: string; document_type: string | null; notice_direction: string | null };
type Workspace = {
  attachments: NoticeAttachment[];
  storage_governance: { allowed_upload_extensions: string[]; max_upload_size_bytes: number };
};

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required; missing tester setup is a failure, not a skip.`);
  return value;
}

function localCredentials(): TesterCredentials {
  return { slug: `nov27-notice-${randomUUID()}`, email: `notice-${randomUUID()}@example.com`,
    password: `Synthetic!${randomUUID()}` };
}

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
  const release = () => assertPublicReleaseIdentity([`${api.origin}/api/build`, `${web.origin}/api/release-identity`], sha);
  await release();
  const credentials: TesterCredentials = local ? localCredentials() : {
    slug: process.env.CASEOPS_RAM_PROD_SLUG?.trim() || "test-legal",
    email: required("CASEOPS_RAM_PROD_EMAIL"),
    password: required("CASEOPS_RAM_PROD_PASSWORD"),
  };
  if (!local && credentials.slug !== "test-legal") {
    throw new Error("Production notice acceptance runs only in the test-legal workspace.");
  }
  const login = () => request.post(`${api.origin}/api/auth/login`, { headers: noPaidProviderHeaders,
    data: { company_slug: credentials.slug, email: credentials.email, password: credentials.password } });
  let response = await login();
  if (local && response.status() !== 200) {
    await json(await request.post(`${api.origin}/api/bootstrap/company`, { headers: noPaidProviderHeaders, data: {
      company_name: "Nova Legal Associates", company_slug: credentials.slug, company_type: "law_firm",
      owner_full_name: "Aishwarya Rao", owner_email: credentials.email, owner_password: credentials.password,
    } }), "Local tester bootstrap");
    response = await login();
  }
  const actor = await json<{ access_token: string; company: { slug: string } }>(response, "Tester API login");
  expect(actor.company.slug).toBe(credentials.slug);
  return { web, api, local, credentials,
    headers: { ...noPaidProviderHeaders, Authorization: `Bearer ${actor.access_token}` }, release };
}

async function workspace(request: APIRequestContext, rt: Runtime, matterId: string): Promise<Workspace> {
  return json<Workspace>(await request.get(`${rt.api.origin}/api/matters/${matterId}/workspace`,
    { headers: rt.headers }), "Matter workspace oracle");
}

async function noticeCount(request: APIRequestContext, rt: Runtime, matterId: string): Promise<number> {
  return (await workspace(request, rt, matterId)).attachments
    .filter((row) => row.document_type === "notice").length;
}

const isAttachmentPost = (matterId: string) => (r: { url(): string; method(): string }) =>
  r.method() === "POST" && new URL(r.url()).pathname === `/api/matters/${matterId}/attachments`;

async function createMatterThroughUi(page: Page, rt: Runtime, title: string, code: string): Promise<string> {
  await page.goto(`${rt.web.origin}/app/matters`);
  await page.getByTestId("new-matter-trigger").first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Title").fill(title);
  await dialog.getByLabel("Matter code").fill(code);
  await dialog.getByLabel("Practice area").fill("Commercial Litigation");
  const created = page.waitForResponse((r) => r.request().method() === "POST"
    && /^\/api\/matters\/?$/.test(new URL(r.url()).pathname));
  await dialog.getByRole("button", { name: "Create matter" }).click();
  const matter = await json<{ id: string; matter_code: string }>(await created, "Create matter through the Matters page");
  expect(matter.matter_code).toBe(code);
  await expect(dialog).toBeHidden();
  return matter.id;
}

async function disposeMatter(page: Page, rt: Runtime, matterId: string, journey: string) {
  await page.goto(`${rt.web.origin}/app/matters/${matterId}`);
  await page.getByTestId("matter-dispose-trigger").click();
  await page.getByTestId("matter-lifecycle-reason").fill(`${journey} retires its own test matter.`);
  const disposed = page.waitForResponse((r) => r.request().method() === "PATCH"
    && new URL(r.url()).pathname === `/api/matters/${matterId}/lifecycle/status`);
  await page.getByTestId("matter-lifecycle-confirm").click();
  expect((await json<{ status: string }>(await disposed, "Dispose the journey matter")).status).toBe("disposed");
}

function localDate(offsetDays: number): string {
  const value = new Date();
  value.setDate(value.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

function textFile(name: string, body: string) {
  return { name, mimeType: "text/plain", buffer: Buffer.from(body, "utf8") };
}

/**
 * Press the upload button and prove the refusal the tester asked for: the
 * named field is invalid, described by the exact message, focused if first,
 * no upload request left the browser, and the server still has `expected`.
 */
async function expectRefused(
  page: Page, request: APIRequestContext, rt: Runtime, matterId: string,
  field: { testId: string; message: string | RegExp }, expected: number,
) {
  let posted = 0;
  const onRequest = (r: { url(): string; method(): string }) => { if (isAttachmentPost(matterId)(r)) posted += 1; };
  page.on("request", onRequest);
  try {
    await page.getByTestId("matter-notice-upload").click();
    const input = page.getByTestId(field.testId);
    await expect(input).toHaveAttribute("aria-invalid", "true");
    const describedBy = (await input.getAttribute("aria-describedby")) ?? "";
    const errorId = describedBy.split(" ").find((id) => id.endsWith("-error"));
    expect(errorId, `${field.testId} must reference its error message`).toBeTruthy();
    await expect(page.locator(`[id="${errorId}"]`)).toHaveText(field.message);
    await expect(page.getByTestId("matter-notice-form-error")).toBeVisible();
    expect(posted, "an invalid notice must never be sent").toBe(0);
  } finally {
    page.off("request", onRequest);
  }
  expect(await noticeCount(request, rt, matterId)).toBe(expected);
}

async function fillReceived(page: Page, subject: string) {
  await page.getByTestId("matter-notice-received-on").fill(localDate(-5));
  await page.getByTestId("matter-notice-type").fill("Legal demand");
  await page.getByTestId("matter-notice-subject").fill(subject);
  await page.getByTestId("matter-notice-source").fill("Opposing counsel");
  await page.getByTestId("matter-notice-amount").fill("12500");
  await page.getByTestId("matter-notice-reply-due-on").fill(localDate(10));
}

async function fillSent(page: Page, subject: string) {
  await page.getByTestId("matter-notice-sent-on").fill(localDate(-3));
  await page.getByTestId("matter-notice-type").fill("Recovery notice");
  await page.getByTestId("matter-notice-subject").fill(subject);
  await page.getByTestId("matter-notice-authority").fill("Debtor Pvt Ltd");
  await page.getByTestId("matter-notice-dispute-amount").fill("15000");
  await page.getByTestId("matter-notice-recovered-amount").fill("2500");
}

/**
 * Types into the native date control the way a user does. Measured in
 * Chromium/Edge (2026-11-27): "02" leaves a partial date (value "" and
 * badInput), "023020" is completed on blur to 0020-03-02, and an impossible
 * 02/30 rolls over to 03/02. The first two are the invalid dates a user can
 * actually produce, and the old form accepted both.
 */
async function typeDate(page: Page, testId: string, keys: string) {
  const input = page.getByTestId(testId);
  await input.fill("");
  await input.focus();
  await page.keyboard.type(keys);
  await input.blur();
  return input.evaluate((node: HTMLInputElement) => ({ value: node.value, badInput: node.validity.badInput }));
}

test("row 2 Notice Received refuses incomplete details and creates nothing", async ({ page, request, baseURL }) => {
  test.setTimeout(300_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(DESKTOP);
  await signIn(page, { web: rt.web }, rt.credentials);
  const code = `N27R-${randomUUID().slice(0, 8).toUpperCase()}`;
  const matterId = await createMatterThroughUi(page, rt, stamp("Nov27 notice received matter"), code);
  try {
    await page.goto(`${rt.web.origin}/app/matters/${matterId}/notices`);
    await expect(page.getByRole("heading", { name: "Notices", exact: true })).toBeVisible();
    await expect(page.getByText("Upload Notice Received")).toBeVisible();
    expect(await noticeCount(request, rt, matterId)).toBe(0);

    // Upload with nothing filled: every required field is named, focus on the first.
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-received-on", message: "Enter the date of receipt." }, 0);
    await expect(page.getByTestId("matter-notice-received-on")).toBeFocused();
    await expect(page.getByTestId("notice-subject-error")).toHaveText("Enter the notice subject.");
    await expect(page.getByTestId("notice-type-error")).toHaveText("Enter the type of notice.");
    await expect(page.getByTestId("notice-file-error")).toHaveText("Attach the notice document.");

    const subject = stamp("Nov27 received demand");
    await fillReceived(page, subject);
    await page.getByTestId("matter-notice-file-input").setInputFiles(
      textFile(`${code.toLowerCase()}-received.txt`, `Received notice ${subject}`));

    // Without Date of Receipt.
    await page.getByTestId("matter-notice-received-on").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-received-on", message: "Enter the date of receipt." }, 0);
    await page.getByTestId("matter-notice-received-on").fill(localDate(-5));

    // Without Subject.
    await page.getByTestId("matter-notice-subject").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-subject", message: "Enter the notice subject." }, 0);
    await page.getByTestId("matter-notice-subject").fill(subject);

    // Invalid dates, typed: a partial date, and a year the control completed to 0020.
    expect(await typeDate(page, "matter-notice-received-on", "02")).toEqual({ value: "", badInput: true });
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-received-on", message: "Enter a real calendar date." }, 0);
    expect((await typeDate(page, "matter-notice-received-on", "023020")).value).toBe("0020-03-02");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-received-on", message: "Enter a date between 1900 and 2100." }, 0);
    // A date in the future.
    await page.getByTestId("matter-notice-received-on").fill(localDate(2));
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-received-on", message: "Date of receipt cannot be in the future." }, 0);
    await page.getByTestId("matter-notice-received-on").fill(localDate(-5));

    // Negative amount.
    await page.getByTestId("matter-notice-amount").fill("-500");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-amount", message: "Amount cannot be negative." }, 0);
    await page.getByTestId("matter-notice-amount").fill("12500");

    // Reply Required = Yes with an empty Reply Due Date.
    await expect(page.getByTestId("matter-notice-reply-required")).toBeChecked();
    await page.getByTestId("matter-notice-reply-due-on").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-reply-due-on", message: "Enter the reply due date, or clear Reply required." }, 0);

    // Reply Due Date earlier than Date of Receipt.
    await page.getByTestId("matter-notice-reply-due-on").fill(localDate(-6));
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-reply-due-on", message: "Reply due date cannot be earlier than the date of receipt." }, 0);

    // The corrected notice is accepted exactly once.
    await page.getByTestId("matter-notice-reply-due-on").fill(localDate(10));
    const uploaded = page.waitForResponse((r) => isAttachmentPost(matterId)(r.request()));
    await page.getByTestId("matter-notice-upload").click();
    const notice = await json<{ id: string; notice_subject: string; notice_received_on: string; notice_reply_due_on: string }>(
      await uploaded, "Upload the corrected received notice");
    expect(notice).toMatchObject({ notice_subject: subject, notice_received_on: localDate(-5),
      notice_reply_due_on: localDate(10) });
    await expect(page.getByTestId("matter-notice-row").filter({ hasText: subject })).toHaveCount(1);
    expect(await noticeCount(request, rt, matterId)).toBe(1);
  } finally {
    await disposeMatter(page, rt, matterId, "Nov 27 notice received validation journey");
  }
  await rt.release();
});

test("row 3 Notice Sent refuses invalid details and files, and handles duplicates", async ({ page, request, baseURL }) => {
  test.setTimeout(360_000);
  const rt = await runtimeFor(baseURL, request);
  await page.setViewportSize(DESKTOP);
  await signIn(page, { web: rt.web }, rt.credentials);
  const code = `N27S-${randomUUID().slice(0, 8).toUpperCase()}`;
  const matterId = await createMatterThroughUi(page, rt, stamp("Nov27 notice sent matter"), code);
  try {
    const policy = (await workspace(request, rt, matterId)).storage_governance;
    expect(policy.allowed_upload_extensions).toContain(".pdf");
    await page.goto(`${rt.web.origin}/app/matters/${matterId}/notices`);
    await page.getByTestId("notice-sent-tab").click();
    await expect(page.getByText("Upload Notice Sent")).toBeVisible();
    // The picker offers exactly the API's allow-list.
    await expect(page.getByTestId("matter-notice-file-input"))
      .toHaveAttribute("accept", policy.allowed_upload_extensions.join(","));

    const subject = stamp("Nov27 sent recovery");
    await fillSent(page, subject);

    // No notice document attached.
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-file-input", message: "Attach the notice document." }, 0);
    const body = `Sent notice ${subject}`;
    await page.getByTestId("matter-notice-file-input").setInputFiles(textFile(`${code.toLowerCase()}-sent.txt`, body));

    // Without Notice Sent Date.
    await page.getByTestId("matter-notice-sent-on").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-sent-on", message: "Enter the notice sent date." }, 0);
    // Invalid dates, typed, then a future date.
    expect(await typeDate(page, "matter-notice-sent-on", "02")).toEqual({ value: "", badInput: true });
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-sent-on", message: "Enter a real calendar date." }, 0);
    expect((await typeDate(page, "matter-notice-sent-on", "0230")).value).toBe("0001-03-02");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-sent-on", message: "Enter a date between 1900 and 2100." }, 0);
    await page.getByTestId("matter-notice-sent-on").fill(localDate(3));
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-sent-on", message: "Notice sent date cannot be in the future." }, 0);
    await page.getByTestId("matter-notice-sent-on").fill(localDate(-3));

    // Without Subject; with an empty Type of Notice.
    await page.getByTestId("matter-notice-subject").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-subject", message: "Enter the notice subject." }, 0);
    await page.getByTestId("matter-notice-subject").fill(subject);
    await page.getByTestId("matter-notice-type").fill("");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-type", message: "Enter the type of notice." }, 0);
    await page.getByTestId("matter-notice-type").fill("Recovery notice");

    // Negative Dispute Amount, negative Recovered Amount, Recovered above Dispute.
    await page.getByTestId("matter-notice-dispute-amount").fill("-15000");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-dispute-amount", message: "Dispute amount cannot be negative." }, 0);
    await page.getByTestId("matter-notice-dispute-amount").fill("15000");
    await page.getByTestId("matter-notice-recovered-amount").fill("-1");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-recovered-amount", message: "Recovered amount cannot be negative." }, 0);
    await page.getByTestId("matter-notice-recovered-amount").fill("15000.01");
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-recovered-amount", message: "Recovered amount cannot exceed the dispute amount." }, 0);
    await page.getByTestId("matter-notice-recovered-amount").fill("2500");

    // Unsupported file format; a file over the size limit.
    await page.getByTestId("matter-notice-file-input").setInputFiles(
      { name: "notice.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ executable") });
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-file-input", message: /^\.exe files are not supported\. Upload one of: / }, 0);
    await page.getByTestId("matter-notice-file-input").setInputFiles(
      { name: "oversize.pdf", mimeType: "application/pdf", buffer: Buffer.alloc(policy.max_upload_size_bytes + 1, 0x41) });
    await expectRefused(page, request, rt, matterId,
      { testId: "matter-notice-file-input", message: /upload limit\.$/ }, 0);

    // The corrected notice is accepted once.
    await page.getByTestId("matter-notice-file-input").setInputFiles(textFile(`${code.toLowerCase()}-sent.txt`, body));
    const first = page.waitForResponse((r) => isAttachmentPost(matterId)(r.request()));
    await page.getByTestId("matter-notice-upload").click();
    const original = await json<{ id: string; notice_dispute_amount_minor: number; notice_recovered_amount_minor: number }>(
      await first, "Upload the corrected sent notice");
    expect(original).toMatchObject({ notice_dispute_amount_minor: 1500000, notice_recovered_amount_minor: 250000 });
    await expect(page.getByTestId("matter-notice-row").filter({ hasText: subject })).toHaveCount(1);
    expect(await noticeCount(request, rt, matterId)).toBe(1);

    // Upload the same notice again: the same file is refused, with a link to it.
    await page.getByTestId("notice-sent-tab").click();
    await fillSent(page, stamp("Nov27 sent copy"));
    await page.getByTestId("matter-notice-file-input").setInputFiles(textFile("copy-of-sent.txt", body));
    const sameFile = page.waitForResponse((r) => isAttachmentPost(matterId)(r.request()));
    await page.getByTestId("matter-notice-upload").click();
    expect((await sameFile).status()).toBe(409);
    const panel = page.getByTestId("matter-notice-duplicate");
    await expect(panel).toContainText("This file is already attached to this matter as a notice.");
    await expect(panel.getByTestId("matter-notice-duplicate-link"))
      .toHaveAttribute("href", `/app/matters/${matterId}/documents/${original.id}/view`);
    await expect(panel.getByTestId("matter-notice-upload-anyway")).toHaveCount(0);
    expect(await noticeCount(request, rt, matterId)).toBe(1);
    // The link opens the existing notice.
    await panel.getByTestId("matter-notice-duplicate-link").click();
    await page.waitForURL(new RegExp(`/app/matters/${matterId}/documents/${original.id}/view$`));
    await expect(page.getByRole("heading", { name: "Document viewer" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Download" }))
      .toHaveAttribute("href", new RegExp(`/api/matters/${matterId}/attachments/${original.id}/download$`));
    await page.goto(`${rt.web.origin}/app/matters/${matterId}/notices`);
    await page.getByTestId("notice-sent-tab").click();

    // New bytes with the same direction, date, subject and counterparty: an
    // explicit, audited override is offered and used.
    await fillSent(page, subject);
    await page.getByTestId("matter-notice-file-input").setInputFiles(
      textFile("second-service.txt", `Second service copy ${subject}`));
    const sameDetails = page.waitForResponse((r) => isAttachmentPost(matterId)(r.request()));
    await page.getByTestId("matter-notice-upload").click();
    expect((await sameDetails).status()).toBe(409);
    await expect(panel).toContainText("same direction, date, subject and counterparty");
    expect(await noticeCount(request, rt, matterId)).toBe(1);
    const override = page.waitForResponse((r) => isAttachmentPost(matterId)(r.request()));
    await panel.getByTestId("matter-notice-upload-anyway").click();
    const overrideResponse = await override;
    // The identical submission was refused above; only the explicit override
    // (allow_duplicate) lets the API accept it. Browsers do not expose a
    // multipart body with a file to Playwright, so the 409 -> 200 pair is the proof.
    await json(overrideResponse, "Upload anyway as a separate notice");
    expect(await noticeCount(request, rt, matterId)).toBe(2);
    await expect(page.getByTestId("matter-notice-row").filter({ hasText: subject })).toHaveCount(2);
  } finally {
    await disposeMatter(page, rt, matterId, "Nov 27 notice sent validation journey");
  }
  await rt.release();
});
