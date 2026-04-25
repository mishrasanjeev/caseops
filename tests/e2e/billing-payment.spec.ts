/* P0-005 (2026-04-24, QG-PAY-001/-002):
 *
 * The earlier version of this spec wrapped both the invoice-only UI
 * path AND the (not-yet-wired) Pine Labs payment-link path in a
 * single test that skipped when CASEOPS_PINE_LABS_API_KEY was
 * absent. As a result, the default E2E run skipped the invoice UI
 * entirely on every PR — release sign-off had no proof the billing
 * UI works end to end. This split fixes that:
 *
 * - "Matter billing — invoice" runs on EVERY E2E pass, no skip.
 *   No Pine Labs API call inside; only verifies that an
 *   API-created invoice surfaces on the billing tab.
 * - "Matter billing — Pine Labs payment link" skips when the
 *   sandbox key is absent (default local) but runs in UAT /
 *   release sign-off where the secret is provisioned.
 *
 * Both blocks share the bootstrap helper. The provider block is
 * intentionally separate so the report distinguishes "invoice UI
 * skipped" from "provider path skipped."
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";
import { plusDays } from "./support/helpers";
import { requireProviderCredentialOrSkip } from "./support/provider-gating";

const PASSWORD = "BillingPass123!";

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ slug: string; token: string }> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Billing Test LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Billing Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() !== 200) {
    throw new Error(`Bootstrap failed: ${resp.status()} ${await resp.text()}`);
  }
  const body = (await resp.json()) as { access_token: string };
  return { slug, token: body.access_token };
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function createMatterAndInvoice(
  api: APIRequestContext,
  slug: string,
): Promise<{ matterId: string; invoiceNumber: string }> {
  const { token } = await bootstrap(api, slug);
  const authHeaders = { Authorization: `Bearer ${token}` };
  const matterCode = `BL-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: authHeaders,
    data: {
      title: "Billing e2e matter",
      matter_code: matterCode,
      practice_area: "commercial",
      forum_level: "high_court",
      status: "active",
    },
  });
  expect(matterResp.status()).toBe(200);
  const matter = (await matterResp.json()) as { id: string };

  const invoiceNumber = `INV-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  const invoiceResp = await api.post(
    `${apiBaseUrl}/api/matters/${matter.id}/invoices`,
    {
      headers: authHeaders,
      data: {
        invoice_number: invoiceNumber,
        issued_on: plusDays(0),
        due_on: plusDays(30),
        status: "draft",
        include_uninvoiced_time_entries: false,
        manual_items: [
          {
            description: "Advisory — BNSS s.483 analysis",
            amount_minor: 500_000,
          },
        ],
      },
    },
  );
  expect(invoiceResp.status()).toBe(200);
  return { matterId: matter.id, invoiceNumber };
}

async function uiSignIn(
  page: import("@playwright/test").Page,
  slug: string,
): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

// ---------- Invoice-only path (always runs) ----------

test.describe("Matter billing — invoice (default E2E)", () => {
  test.setTimeout(120_000);

  test("issue invoice via API, see row on billing tab", async ({ page }) => {
    const api = await request.newContext();
    const slug = unique("bl");
    const { matterId, invoiceNumber } = await createMatterAndInvoice(
      api,
      slug,
    );
    await uiSignIn(page, slug);

    await page.goto(`/app/matters/${matterId}/billing`);
    await expect(
      page.getByRole("heading", { name: /^Invoices$/ }),
    ).toBeVisible({ timeout: 15_000 });
    await expect(page.getByText(invoiceNumber)).toBeVisible({
      timeout: 15_000,
    });
  });
});

// ---------- Pine Labs provider path (UAT/release only) ----------

test.describe("Matter billing — Pine Labs payment link (provider-gated)", () => {
  test.setTimeout(120_000);

  // AQ-006 (2026-04-25): under CASEOPS_RELEASE_MODE=true, missing
  // credentials FAIL the test instead of silently skipping. Default
  // (laptop, normal PR CI) keeps the existing skip behavior. See
  // tests/e2e/support/provider-gating.ts for the contract.
  requireProviderCredentialOrSkip(test, {
    provider: "Pine Labs",
    envVar: "CASEOPS_PINE_LABS_API_KEY",
  });

  test("create invoice + payment link, payment link reachable", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("pl");
    const { matterId, invoiceNumber } = await createMatterAndInvoice(
      api,
      slug,
    );
    await uiSignIn(page, slug);
    await page.goto(`/app/matters/${matterId}/billing`);
    await expect(page.getByText(invoiceNumber)).toBeVisible({
      timeout: 15_000,
    });
    // Send-payment-link CTA (visible only when CASEOPS_PINE_LABS_API_KEY
    // is configured server-side; the test runs in environments where
    // both key and webhook secret exist).
    const sendBtn = page.getByRole("button", {
      name: /send payment link/i,
    });
    await expect(sendBtn.first()).toBeVisible({ timeout: 15_000 });
    await sendBtn.first().click();
    await expect(
      page.getByText(/payment link sent|payment link generated/i),
    ).toBeVisible({ timeout: 30_000 });
  });
});
