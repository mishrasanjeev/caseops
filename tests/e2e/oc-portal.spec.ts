/**
 * Phase C-3 outside-counsel portal E2E (MOD-TS-016, 2026-04-25).
 *
 * Walks the OC portal end-to-end as a real signed-in OC user:
 *   1. owner bootstraps a workspace + creates a matter
 *   2. owner invites an OC portal user via the admin API
 *   3. consume the debug magic-link token (e2e env exposes it; prod
 *      sends via SendGrid only)
 *   4. land on /portal/oc with the assigned matter
 *   5. open the matter → upload work product → submit invoice → log time
 *
 * Anchor for the "test every UI feature E2E before shipping" hard
 * rule for the C-3 OC portal surface. Catches any regression where
 * the OC routes are silently broken (auth, scope, CSRF, multipart
 * upload, etc.) the unit tests can't detect.
 */
import { expect, request, test } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "OcPortalE2E!23";

async function bootstrapAndCreateMatter(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string; matterId: string }> {
  const boot = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "OC Portal E2E LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "OC Portal Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (boot.status() !== 200) {
    throw new Error(
      `Bootstrap failed: ${boot.status()} ${await boot.text()}`,
    );
  }
  const bootBody = await boot.json();
  const token = bootBody.access_token as string;

  const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      title: "OC e2e — work product",
      matter_code: `OCE-${Math.random().toString(36).slice(2, 6).toUpperCase()}`,
      client_name: "OC Test Client",
      opposing_party: "Counter Party",
      status: "active",
      practice_area: "Commercial",
      forum_level: "high_court",
    },
  });
  if (matterResp.status() !== 200) {
    throw new Error(
      `Matter create failed: ${matterResp.status()} ${await matterResp.text()}`,
    );
  }
  const m = await matterResp.json();
  return { token, matterId: m.id as string };
}

async function inviteOcPortalUser(
  api: APIRequestContext,
  token: string,
  matterId: string,
  email: string,
): Promise<string> {
  const resp = await api.post(`${apiBaseUrl}/api/admin/portal/invitations`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      email,
      full_name: "Counsel One",
      role: "outside_counsel",
      matter_ids: [matterId],
    },
  });
  if (resp.status() !== 201) {
    throw new Error(
      `Invite failed: ${resp.status()} ${await resp.text()}`,
    );
  }
  const body = await resp.json();
  if (!body.debug_token) {
    throw new Error("Expected debug_token from invitation in e2e env");
  }
  return body.debug_token as string;
}

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Phase C-3 outside-counsel portal", () => {
  test.setTimeout(180_000);

  test("invite OC → consume magic link → upload work product → submit invoice → log time", async ({
    page,
    context,
  }) => {
    const api = await request.newContext();
    const slug = unique("oc");
    const { token, matterId } = await bootstrapAndCreateMatter(api, slug);
    const ocEmail = `oc-${slug}@example.com`;
    const debugToken = await inviteOcPortalUser(api, token, matterId, ocEmail);

    // Sign in as the OC by hitting verify-link directly. Simpler than
    // walking the request-link UI; both code paths set the same
    // caseops_portal_session + caseops_portal_csrf cookies.
    const verifyResp = await api.post(
      `${apiBaseUrl}/api/portal/auth/verify-link`,
      { data: { token: debugToken } },
    );
    expect(verifyResp.status()).toBe(200);

    // Carry the portal-session cookies into the browser context. We
    // pull them from the api request context's cookie jar (they were
    // Set-Cookie'd by verify-link).
    const apiCookies = await api.storageState();
    const portalCookies = apiCookies.cookies.filter((c) =>
      c.name.startsWith("caseops_portal_"),
    );
    expect(
      portalCookies.length,
      "verify-link should set both portal-session + portal-csrf cookies",
    ).toBeGreaterThanOrEqual(2);
    await context.addCookies(portalCookies);

    // Land on the OC matters list.
    await page.goto("/portal/oc");
    await expect(
      page.getByText(/Welcome, Counsel/i),
    ).toBeVisible({ timeout: 15_000 });
    await expect(
      page.getByTestId(`portal-oc-matter-${matterId}`),
    ).toBeVisible({ timeout: 15_000 });

    // Open the matter detail.
    await page.goto(`/portal/oc/matters/${matterId}`);
    await expect(
      page.getByRole("heading", { name: /OC e2e — work product/i }),
    ).toBeVisible({ timeout: 15_000 });

    // --- Upload work product ---
    await page.getByRole("tab", { name: /work product/i }).click();
    const pdfBytes = Buffer.from(
      "%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj <<>> endobj\ntrailer<<>>\n%%EOF",
      "binary",
    );
    const fileInput = page.getByTestId("portal-oc-work-product-file");
    await fileInput.setInputFiles({
      name: "ocbrief.pdf",
      mimeType: "application/pdf",
      buffer: pdfBytes,
    });
    await page.getByTestId("portal-oc-work-product-submit").click();
    // Uploaded item appears in the list.
    await expect(page.getByText("ocbrief.pdf")).toBeVisible({
      timeout: 15_000,
    });

    // --- Submit invoice ---
    await page.getByRole("tab", { name: /invoices/i }).click();
    await page
      .getByTestId("portal-oc-invoice-number")
      .fill("OC-E2E-001");
    await page
      .getByTestId("portal-oc-invoice-description")
      .fill("Drafting brief on appeal — e2e");
    await page.getByTestId("portal-oc-invoice-amount").fill("500000");
    await page.getByTestId("portal-oc-invoice-submit").click();
    // Submitted invoice surfaces with needs_review badge.
    await expect(page.getByText(/OC-E2E-001/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText(/needs_review/i)).toBeVisible({
      timeout: 15_000,
    });

    // --- Log time entry ---
    await page.getByRole("tab", { name: /time/i }).click();
    await page
      .getByTestId("portal-oc-time-description")
      .fill("Reviewed lower-court order — e2e");
    await page.getByTestId("portal-oc-time-duration").fill("90");
    await page.getByTestId("portal-oc-time-submit").click();
    await expect(
      page.getByText(/Reviewed lower-court order — e2e/i),
    ).toBeVisible({ timeout: 15_000 });
  });
});
