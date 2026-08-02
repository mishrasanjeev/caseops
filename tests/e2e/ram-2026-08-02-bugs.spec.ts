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
  await page.getByRole("button", { name: /^Sign in$/ }).click();
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
});
