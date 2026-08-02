import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const PASSWORD = "ProviderHealthProof2026!";

function unique(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

async function bootstrap(
  api: APIRequestContext,
  slug: string,
): Promise<{ token: string }> {
  const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Provider Health Proof LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "Provider Health Owner",
      owner_email: `owner-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  expect(response.status()).toBe(200);
  return { token: (await response.json()).access_token as string };
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`owner-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  const loginResponse = await loginResponsePromise;
  expect(
    loginResponse.status(),
    `Login failed: ${await loginResponse.text()}`,
  ).toBe(200);
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe("Ram 2026-08-02 provider health and replay foundation", () => {
  test.setTimeout(120_000);

  test("health fails closed without a recent success and remains usable at 360px", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("provider-health");
    const { token } = await bootstrap(api, slug);
    const healthResponse = await api.get(`${apiBaseUrl}/api/admin/integrations/health`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(healthResponse.status()).toBe(200);
    const health = await healthResponse.json();
    expect(health.health.length).toBeGreaterThan(0);
    for (const row of health.health) {
      if (
        row.configured_state === "configured" &&
        row.connected_state !== "disabled" &&
        !row.last_success_at
      ) {
        expect(row.operational_state).not.toBe("healthy");
        expect(row.freshness_state).toBe("never_succeeded");
      }
    }

    await signIn(page, slug);
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/admin/integrations");
    await expect(page.getByRole("heading", { name: "Integrations" })).toBeVisible();
    await expect(page.getByTestId("connector-health-summary")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);

    await page.goto("/app/admin/provider-operations");
    await expect(
      page.getByRole("heading", { name: "Provider operations", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByText("No provider operations need attention").or(
        page.locator('[data-testid^="provider-operation-"]').first(),
      ),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);
  });

  test("IPLF-002B shows stale tracking evidence and health-gates refresh at 360px", async ({
    page,
  }) => {
    const api = await request.newContext();
    const slug = unique("tracking-freshness");
    await bootstrap(api, slug);
    await signIn(page, slug);

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
    await page.route("**/api/case-tracking/support-matrix", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: '{"rows":[]}' }),
    );
    await page.route("**/api/case-tracking/bookmarks", (route) =>
      route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          bookmarks: [
            {
              id: "bm-iplf002b",
              company_id: "company-iplf002b",
              tracked_case_id: "case-iplf002b",
              created_by_membership_id: "membership-iplf002b",
              matter_id: null,
              name: "Synthetic stale tracking proof",
              notification_enabled: true,
              is_archived: false,
              created_at: "2026-08-02T10:00:00Z",
              updated_at: "2026-08-02T10:00:00Z",
              archived_at: null,
              update_count: 2,
              tracked_case: {
                id: "case-iplf002b",
                provider: "ecourtsindia",
                cnr_number: "E2E002B00000001",
                case_number: "E2E/002B/2026",
                court_code: "E2E",
                court_name: "Synthetic Test Court",
                case_title: "Synthetic stale tracking proof",
                party_names: [],
                current_status: "Pending",
                current_stage: "Test",
                next_hearing_on: null,
                last_provider_checked_at: "2026-07-31T10:00:00Z",
                last_provider_attempted_at: "2026-08-02T09:00:00Z",
                last_provider_successful_at: "2026-07-31T10:00:00Z",
                next_provider_refresh_at: "2026-08-03T11:00:00Z",
                freshness_status: "stale",
                response_class: "authentication",
                last_operation_id: "operation-iplf002b",
                provider_health: "unhealthy",
                manual_refresh_allowed: false,
                manual_refresh_disabled_reason: "Case tracking provider health is red.",
                refresh_cost_minor: 25,
                refresh_currency: "INR",
                last_error: "Provider authentication failed.",
                metadata: {},
              },
            },
          ],
        }),
      }),
    );
    await page.route("**/api/case-tracking/bookmarks/bm-iplf002b/updates", (route) =>
      route.fulfill({ status: 200, contentType: "application/json", body: '{"updates":[]}' }),
    );

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app/case-tracking");
    await expect(page.getByText("Synthetic stale tracking proof")).toBeVisible();
    await expect(page.getByText(/ecourtsindia · unhealthy/i)).toBeVisible();
    await expect(page.getByText(/Refresh cost INR 0.25/i)).toBeVisible();
    await expect(page.getByText(/Last good/i)).toBeVisible();
    await expect(page.getByText(/manual docketing/i)).toBeVisible();
    await expect(page.getByRole("button", { name: /Refresh/i })).toBeDisabled();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );
  });
});
