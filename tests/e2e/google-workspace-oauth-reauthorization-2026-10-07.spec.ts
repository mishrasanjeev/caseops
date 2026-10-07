import { expect, request, test, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const localPassword = "WorkspaceReauth123!";
const now = "2026-10-07T00:00:00Z";

async function signInFreshTenant(page: Page, provider: string): Promise<void> {
  const slug = `workspace-reauth-${provider}-${Date.now().toString(36)}`;
  const email = `owner-${slug}@example.com`;
  const api = await request.newContext();
  const bootstrap = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: `Workspace reauth ${provider}`,
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Workspace Reauth Test",
      owner_email: email,
      owner_password: localPassword,
    },
  });
  expect(bootstrap.status(), await bootstrap.text()).toBe(200);
  await api.dispose();

  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(localPassword);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:\/|$)/);
}

function mailboxStatus(connectionStatus: "connected" | "error") {
  return {
    provider: "gmail",
    configured: true,
    webhook_configured: false,
    connections: [
      {
        id: "mailbox-connection",
        company_id: "test-company",
        membership_id: "test-membership",
        provider: "gmail",
        provider_account_id: "google-account",
        display_email: "connected@example.test",
        status: connectionStatus,
        scopes: [],
        connected_at: now,
        created_at: now,
        updated_at: now,
      },
    ],
  };
}

function driveStatus(connectionStatus: "connected" | "error") {
  return {
    provider: "google_drive",
    configured: true,
    connections: [
      {
        id: "drive-connection",
        company_id: "test-company",
        membership_id: "test-membership",
        provider: "google_drive",
        provider_account_id: "google-account",
        display_email: "connected@example.test",
        status: connectionStatus,
        scopes: [],
        connected_at: now,
        last_list_at: null,
        created_at: now,
        updated_at: now,
      },
    ],
  };
}

test.describe("Google Workspace reauthorization does not expire CaseOps login", () => {
  test("Gmail 409 keeps the user in the mailbox and offers reconnect", async ({ page }) => {
    let connectionStatus: "connected" | "error" = "connected";
    await signInFreshTenant(page, "gmail");
    await page.route("**/api/mailbox/gmail/status*", (route) =>
      route.fulfill({ json: mailboxStatus(connectionStatus) }),
    );
    await page.route("**/api/mailbox/imports**", (route) =>
      route.fulfill({
        json: {
          summary: {
            imported: 0,
            unmatched: 0,
            duplicate: 0,
            failed: 0,
            attachment_candidates: 0,
          },
          imports: [],
        },
      }),
    );
    await page.route("**/api/mailbox/gmail/import", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      connectionStatus = "error";
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Google authorization expired or was revoked. Reconnect this account.",
        }),
      });
    });

    await page.goto("/app/mailbox");
    const sync = page.getByRole("button", { name: "Sync Gmail" });
    await expect(sync).toBeEnabled();
    await sync.click();

    await expect(page).toHaveURL(/\/app\/mailbox$/);
    await expect(page.getByRole("button", { name: "Reconnect Gmail" })).toBeEnabled();
    await expect(sync).toBeDisabled();
  });

  test("Drive 409 keeps the user in the review queue and offers reconnect", async ({ page }) => {
    let connectionStatus: "connected" | "error" = "connected";
    await signInFreshTenant(page, "drive");
    await page.route("**/api/drive/google/status*", (route) =>
      route.fulfill({ json: driveStatus(connectionStatus) }),
    );
    await page.route("**/api/drive/candidates**", (route) =>
      route.fulfill({ json: { pending_count: 0, candidates: [] } }),
    );
    await page.route("**/api/drive/google/candidates/sync", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      connectionStatus = "error";
      await route.fulfill({
        status: 409,
        contentType: "application/json",
        body: JSON.stringify({
          detail: "Google authorization expired or was revoked. Reconnect this account.",
        }),
      });
    });

    await page.goto("/app/drive");
    const sync = page.getByRole("button", { name: "Sync Google Drive" });
    await expect(sync).toBeEnabled();
    await sync.click();

    await expect(page).toHaveURL(/\/app\/drive$/);
    await expect(page.getByRole("button", { name: "Reconnect Google Drive" })).toBeEnabled();
    await expect(sync).toBeDisabled();
  });
});
