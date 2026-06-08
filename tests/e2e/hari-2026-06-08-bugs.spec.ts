/**
 * Hari 2026-06-08 workbook regressions:
 * - BUG-051: uploaded hearing order compliance extraction state is visible.
 * - BUG-052: matter invoice PDF receipt download works for authorized users.
 * - BUG-053: Google Calendar is surfaced as a fail-closed OAuth connector
 *   with safe .ics fallback when provider configuration is absent; Gmail
 *   mailbox and Google Drive are also fail-closed without provider
 *   configuration.
 * - Hearing cancellation: a cancelled hearing leaves upcoming buckets and
 *   remains visible only in the cancelled-history section.
 *
 * The spec uses local app/API fixtures only. It does not call Google,
 * Microsoft, Pine Labs, SMS, WhatsApp, or court providers.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { makeUploadFixture, plusDays } from "./support/helpers";

const PASSWORD = "HariJun08Bugs!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-08 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Owner",
      owner_email: ownerEmail,
      owner_password: PASSWORD,
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return { token: (await resp.json()).access_token as string, ownerEmail };
}

async function createMatter(
  api: APIRequestContext,
  token: string,
  code: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: `Hari bug matter ${code}`,
      matter_code: code,
      practice_area: "commercial",
      forum_level: "high_court",
      status: "intake",
      court_name: "Delhi High Court",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return (await resp.json()).id as string;
}

async function createHearing(
  api: APIRequestContext,
  token: string,
  matterId: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/matters/${matterId}/hearings`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      hearing_on: plusDays(20),
      forum_name: "Delhi High Court",
      purpose: "Cancellation regression hearing",
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  return (await resp.json()).id as string;
}

async function createInvoice(
  api: APIRequestContext,
  token: string,
  matterId: string,
): Promise<{ id: string; invoiceNumber: string }> {
  const invoiceNumber = `HARI/${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  const resp = await api.post(`${apiBaseUrl}/api/matters/${matterId}/invoices`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      invoice_number: invoiceNumber,
      issued_on: plusDays(0),
      due_on: plusDays(30),
      status: "draft",
      include_uninvoiced_time_entries: false,
      manual_items: [
        {
          description: "Manual professional fee",
          amount_minor: 250_000,
        },
      ],
    },
  });
  expect(resp.status(), await resp.text()).toBe(200);
  const body = (await resp.json()) as { id: string; invoice_number: string };
  return { id: body.id, invoiceNumber: body.invoice_number };
}

async function signIn(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

test.describe("Hari 2026-06-08 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-051: uploaded court order exposes compliance extraction status and retry action", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60851");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H608-51");
    await signIn(page, slug, ownerEmail);

    await page.goto(`/app/matters/${matterId}/hearings`);
    await expect(page.getByTestId("matter-compliance-panel")).toBeVisible();
    await page.getByTestId("add-court-order-open").first().click();
    await page.getByTestId("add-court-order-date").fill("2026-06-08");
    await page.getByTestId("add-court-order-kind").selectOption("daily_order");
    await page
      .getByTestId("add-court-order-title")
      .fill("Order directing compliance affidavit");
    await page
      .getByTestId("add-court-order-summary")
      .fill("Respondent to file compliance affidavit before next date.");
    const orderPath = makeUploadFixture(
      `hari-0608-order-${slug}.pdf`,
      "%PDF-1.4\n1 0 obj <<>> endobj\ntrailer <<>>\n%%EOF\n",
    );
    await page.getByTestId("add-court-order-file").setInputFiles(orderPath);
    await page.getByTestId("add-court-order-submit").click();

    await expect(page.getByRole("dialog")).toBeHidden({ timeout: 15_000 });
    const runList = page.getByTestId("matter-compliance-run-list");
    await expect(runList).toBeVisible({ timeout: 15_000 });
    await expect(runList).toContainText(/Uploaded order document|Court order/);
    await expect(runList).toContainText(/text_extraction_pending|order_text_missing/);
  });

  test("BUG-052: authorized matter billing user downloads a professional PDF receipt", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60852");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H608-52");
    const invoice = await createInvoice(api, token, matterId);
    await signIn(page, slug, ownerEmail);

    await page.goto(`/app/matters/${matterId}/billing`);
    await expect(page.getByText(invoice.invoiceNumber)).toBeVisible({
      timeout: 15_000,
    });
    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId(`invoice-pdf-${invoice.id}`).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(
      /^caseops-matter-invoice-HARI-[A-Z0-9]+\.pdf$/,
    );
  });

  test("BUG-053: Google Calendar appears fail-closed with safe .ics fallback", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60853");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H608-53");
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/calendar");
    await expect(page.getByTestId("calendar-google-panel")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("calendar-google-panel")).toContainText(
      "Google Calendar OAuth is not configured.",
    );
    await expect(
      page.getByTestId("calendar-google-provider-config-status"),
    ).toContainText("GOOGLE_CALENDAR_CLIENT_ID");
    await expect(page.getByTestId("calendar-google-connect")).toBeDisabled();
    await expect(page.getByTestId("calendar-google-ics-download")).toHaveAttribute(
      "download",
      "caseops-calendar.ics",
    );
    await expect(page.getByTestId("calendar-google-integrations-link")).toHaveAttribute(
      "href",
      "/app/admin/integrations",
    );
    await expect(page.getByTestId("calendar-gmail-panel")).toBeVisible();
    await expect(page.getByTestId("calendar-gmail-panel")).toContainText(
      "Gmail OAuth is not configured.",
    );
    await expect(
      page.getByTestId("calendar-gmail-provider-config-status"),
    ).toContainText("GMAIL_CLIENT_ID");
    await expect(page.getByTestId("calendar-gmail-connect")).toBeDisabled();
    await expect(page.getByTestId("calendar-gmail-panel")).not.toContainText(
      /access_token|refresh_token|gmail-access|gmail-refresh|gross profit|gross margin|internal cost|provider fee/i,
    );

    await page.goto(`/app/matters/${matterId}/documents`);
    await expect(page.getByTestId("matter-google-drive-panel")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("matter-google-drive-panel")).toContainText(
      "Google Drive OAuth is not configured.",
    );
    await expect(page.getByTestId("matter-google-drive-connect")).toBeDisabled();
    await expect(page.getByTestId("matter-google-drive-panel")).not.toContainText(
      /access_token|refresh_token|encrypted_token_ref|gross profit|gross margin|internal cost|provider fee/i,
    );
  });

  test("hearing cancellation leaves upcoming buckets and remains in cancelled history", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h608cancel");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H608-CANCEL");
    const hearingId = await createHearing(api, token, matterId);
    await signIn(page, slug, ownerEmail);

    await page.goto(`/app/matters/${matterId}/hearings`);
    await expect(page.getByText("Cancellation regression hearing")).toBeVisible({
      timeout: 15_000,
    });
    await page.getByTestId(`hearing-cancel-${hearingId}`).click();
    await expect(page.getByTestId(`cancelled-hearing-${hearingId}`)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId(`cancelled-hearing-${hearingId}`)).toContainText(
      "Cancellation regression hearing",
    );
    await expect(page.getByTestId(`hearing-cancel-${hearingId}`)).toHaveCount(0);

    await page.goto(`/app/matters/${matterId}`);
    await expect(page.getByTestId("matter-overview-no-hearings")).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId("matter-overview-no-hearings")).not.toContainText(
      "Cancellation regression hearing",
    );
  });
});
