/**
 * Hari 2026-05-05 BUG-026/027 regression.
 *
 * The backend portal existed, but the staff-facing invite workflow was
 * not reachable from the app and outside-counsel magic-link verification
 * landed on the client portal. This spec proves the end-user workflow:
 * owner grants a matter from Admin, client signs in to /portal, and OC
 * signs in to /portal/oc.
 */
import { expect, request, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "PortalInviteAccess2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function signInOwner(page: Page, slug: string, email: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^sign in$/i }).click();
  await page.waitForURL(/\/app(\/|$)/, { timeout: 30_000 });
}

test.describe("Admin portal invitations", () => {
  test.setTimeout(180_000);

  test("owner invites client and outside counsel, both land on their scoped matter", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("portal-access");
    const ownerEmail = `owner-${slug}@example.com`;

    const boot = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
      data: {
        company_name: "Portal Access E2E LLP",
        company_slug: slug,
        company_type: "law_firm",
        owner_full_name: "Portal Access Owner",
        owner_email: ownerEmail,
        owner_password: PASSWORD,
      },
    });
    expect(boot.status()).toBe(200);
    const token = (await boot.json()).access_token as string;

    const matterResp = await api.post(`${apiBaseUrl}/api/matters/`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        title: "Portal invite scoped matter",
        matter_code: unique("PIA").toUpperCase(),
        client_name: "Portal Client",
        opposing_party: "Portal Respondent",
        status: "intake",
        practice_area: "Commercial",
        forum_level: "high_court",
      },
    });
    expect(matterResp.status()).toBe(200);
    const matterId = (await matterResp.json()).id as string;

    await signInOwner(page, slug, ownerEmail);
    await page.goto("/app/admin");

    const clientEmail = `client-${slug}@example.com`;
    await page.getByTestId("portal-invite-name").fill("Client Contact");
    await page.getByTestId("portal-invite-email").fill(clientEmail);
    await page.getByTestId("portal-invite-role").selectOption("client");
    await page.getByTestId("portal-invite-matter").selectOption(matterId);
    await page.getByTestId("portal-invite-submit").click();
    await expect(page.getByText(/Client Contact invited/i)).toBeVisible();

    const ocEmail = `oc-${slug}@example.com`;
    await page.getByTestId("portal-invite-name").fill("Outside Counsel");
    await page.getByTestId("portal-invite-email").fill(ocEmail);
    await page.getByTestId("portal-invite-role").selectOption("outside_counsel");
    await page.getByTestId("portal-invite-matter").selectOption(matterId);
    await expect(page.getByTestId("portal-invite-can-upload")).toBeChecked();
    await expect(page.getByTestId("portal-invite-can-invoice")).toBeChecked();
    await page.getByTestId("portal-invite-submit").click();
    await expect(page.getByText(/Outside Counsel invited/i)).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/portal/sign-in");
    await page.getByLabel(/workspace handle/i).fill(slug);
    await page.getByLabel(/^email$/i).fill(clientEmail);
    await page.getByTestId("portal-signin-submit").click();
    await page.waitForURL(/\/portal$/, { timeout: 30_000 });
    await expect(page.getByTestId(`portal-matter-${matterId}`)).toBeVisible();

    await page.context().clearCookies();
    await page.goto("/portal/sign-in");
    await page.getByLabel(/workspace handle/i).fill(slug);
    await page.getByLabel(/^email$/i).fill(ocEmail);
    await page.getByTestId("portal-signin-submit").click();
    await page.waitForURL(/\/portal\/oc$/, { timeout: 30_000 });
    await expect(page.getByTestId(`portal-oc-matter-${matterId}`)).toBeVisible();
  });
});
