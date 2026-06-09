/**
 * Hari 2026-06-09 workbook regressions.
 *
 * Covers:
 * - BUG-054: tenant admin can save the default matter-billing profile.
 * - BUG-055: authorized matter billing user can download the invoice PDF.
 * - BUG-056: matter portfolio exposes a status update workflow.
 * - BUG-057: case-tracking source links are CaseOps API proxy links, not raw
 *   provider URLs. No court provider calls are made by this spec.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "HariJun09Bugs!";

function unique(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random()
    .toString(36)
    .slice(2, 8)}`;
}

function isoDate(offsetDays = 0): string {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + offsetDays);
  return date.toISOString().slice(0, 10);
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; ownerEmail: string }> {
  const ownerEmail = `owner-${slug}@example.com`;
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Hari 2026-06-09 LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Hari Jun09 Owner",
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
      title: `Hari Jun09 matter ${code}`,
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

async function createInvoice(
  api: APIRequestContext,
  token: string,
  matterId: string,
): Promise<{ id: string; invoiceNumber: string }> {
  const invoiceNumber = `HJ09/${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  const resp = await api.post(`${apiBaseUrl}/api/matters/${matterId}/invoices`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      invoice_number: invoiceNumber,
      issued_on: isoDate(),
      due_on: isoDate(30),
      status: "draft",
      include_uninvoiced_time_entries: false,
      manual_items: [{ description: "Manual professional fee", amount_minor: 250_000 }],
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

test.describe("Hari 2026-06-09 bugs", () => {
  test.setTimeout(120_000);

  test("BUG-054: tenant admin saves the default matter billing profile", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60954");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/admin/matter-billing");
    await page.getByLabel("GSTIN").fill("07ABCDE1234F1Z5");
    await page.getByLabel("PAN").fill("ABCDE1234F");
    await page.getByLabel("Place of supply").fill("Delhi");
    await page.getByLabel("Default SAC/HSN").fill("9982");
    await page.getByRole("button", { name: /Save default profile/i }).click();

    await expect(page.getByText("07ABCDE1234F1Z5")).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText("9982")).toBeVisible();
  });

  test("BUG-055: authorized matter billing user downloads invoice PDF", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60955");
    const { token, ownerEmail } = await bootstrap(api, slug);
    const matterId = await createMatter(api, token, "H609-55");
    const invoice = await createInvoice(api, token, matterId);
    await signIn(page, slug, ownerEmail);

    await page.goto(`/app/matters/${matterId}/billing`);
    await expect(page.getByText(invoice.invoiceNumber)).toBeVisible({
      timeout: 15_000,
    });
    const downloadPromise = page.waitForEvent("download");
    await page.getByTestId(`invoice-pdf-${invoice.id}`).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toMatch(/^caseops-matter-invoice-/);
  });

  test("BUG-056: matter portfolio can update matter status", async ({ page }) => {
    const api = await request.newContext();
    const slug = unique("h60956");
    const { token, ownerEmail } = await bootstrap(api, slug);
    await createMatter(api, token, "H609-56");
    await signIn(page, slug, ownerEmail);

    await page.goto("/app/matters");
    const statusSelect = page.getByLabel("Status for H609-56");
    await expect(statusSelect).toBeVisible({ timeout: 15_000 });
    await statusSelect.selectOption("disposed");
    await expect(statusSelect).toHaveValue("disposed");
  });

  test("BUG-057: case-tracking source link is a CaseOps proxy URL", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("h60957");
    const { ownerEmail } = await bootstrap(api, slug);
    await signIn(page, slug, ownerEmail);

    const providerUrl =
      "https://webapi.ecourtsindia.com/api/partner/case/DLHC010012342026/order/order-1.pdf";
    let providerCalls = 0;
    await page.route("**/webapi.ecourtsindia.com/**", (route) => {
      providerCalls += 1;
      return route.abort();
    });
    await page.route("**/api/case-tracking/status", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          enabled: true,
          provider: "ecourtsindia",
          configured: true,
          reason: null,
        }),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          bookmarks: [
            {
              id: "bm-h60957",
              company_id: "company-h60957",
              tracked_case_id: "tc-h60957",
              created_by_membership_id: "membership-h60957",
              matter_id: null,
              name: null,
              notification_enabled: true,
              is_archived: false,
              created_at: "2026-06-09T00:00:00Z",
              updated_at: "2026-06-09T00:00:00Z",
              archived_at: null,
              update_count: 1,
              tracked_case: {
                id: "tc-h60957",
                provider: "ecourtsindia",
                cnr_number: "DLHC010012342026",
                case_number: "WP(C) 1/2026",
                court_code: "DLHC",
                court_name: "Delhi High Court",
                case_title: "Example Petitioner v Example Respondent",
                party_names: ["Example Petitioner", "Example Respondent"],
                current_status: "Pending",
                current_stage: "Arguments",
                next_hearing_on: "2026-06-15",
                last_provider_checked_at: "2026-06-09T00:00:00Z",
                last_error: null,
                metadata: {},
              },
            },
          ],
        }),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks/bm-h60957/updates", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          updates: [
            {
              id: "upd-h60957",
              company_id: "company-h60957",
              tracked_case_id: "tc-h60957",
              update_type: "new_order",
              source_record_key: "order:1",
              title: "Order dated 9 June 2026",
              summary: "Source-backed case update summary for lawyer review.",
              ai_summary: {
                review_framing:
                  "Source-backed case update summary for lawyer review.",
                source_reference:
                  "/api/case-tracking/bookmarks/bm-h60957/updates/upd-h60957/source",
              },
              source_url:
                "/api/case-tracking/bookmarks/bm-h60957/updates/upd-h60957/source",
              order_date: "2026-06-09",
              hearing_date: null,
              provider_metadata: {},
              created_at: "2026-06-09T00:00:00Z",
            },
          ],
        }),
      }),
    );

    await page.goto("/app/case-tracking");
    await page.getByText("Example Petitioner v Example Respondent").click();
    await expect(page.getByText("Order dated 9 June 2026")).toBeVisible();
    await expect(page.getByRole("link", { name: /Source/i })).toHaveAttribute(
      "href",
      `${apiBaseUrl}/api/case-tracking/bookmarks/bm-h60957/updates/upd-h60957/source`,
    );
    await expect(page.locator("body")).not.toContainText(providerUrl);
    expect(providerCalls).toBe(0);
  });
});
