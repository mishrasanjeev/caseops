import { expect, request, test } from "@playwright/test";
import type { APIRequestContext, Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

// Phase 11 gate: when /api/matters or /api/contracts fails, the workspace
// renders the branded QueryErrorState with a working Retry button — no
// Chromium error page, no silent blank.

const PASSWORD = "QueryStatesPass123!";

async function bootstrap(api: APIRequestContext, slug: string): Promise<void> {
  const resp = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
    data: {
      company_name: "Query States LLP",
      company_slug: slug,
      company_type: "law_firm",
      owner_full_name: "QS Owner",
      owner_email: `qs-${slug}@example.com`,
      owner_password: PASSWORD,
    },
  });
  if (resp.status() === 409) return;
  if (resp.status() !== 200) {
    throw new Error(
      `Bootstrap failed for ${slug}: ${resp.status()} ${await resp.text()}`,
    );
  }
}

async function signIn(page: Page, slug: string): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(slug);
  await page.locator("#email").fill(`qs-${slug}@example.com`);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app/);
}

function slug(prefix: string): string {
  return `${prefix}-${Math.random().toString(36).slice(2, 8)}`;
}

test.describe("Query error and recovery", () => {
  test("matters list surfaces retry on transient 500, recovers on retry", async ({
    page,
  }) => {
    const api = await request.newContext();
    const s = slug("qs-m");
    await bootstrap(api, s);
    await signIn(page, s);
    // Wait for the dashboard's initial matters query to settle before
    // arming the mock — the dashboard also calls /api/matters and would
    // otherwise burn our failure budget.
    await page.waitForURL(/\/app(?!\/matters)/, { timeout: 15_000 });
    await page.waitForLoadState("networkidle");

    // React Query's default `retry: 1` means we have to fail both the
    // first call and the auto-retry; only then does the UI enter the
    // error state. Any subsequent GET (the explicit Retry click) is
    // allowed through to the real API.
    let failed = 0;
    await page.route("**/api/matters/*", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      if (failed >= 2) return route.continue();
      failed += 1;
      await route.fulfill({
        status: 500,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Internal Server Error" }),
      });
    });

    await page.goto("/app/matters");

    await expect(
      page.getByRole("heading", { name: /Could not load matters/i }),
    ).toBeVisible();
    const retry = page.getByTestId("query-error-retry");
    await expect(retry).toBeVisible();

    await retry.click();

    // After retry, the matters portfolio heading must be visible (data
    // loaded successfully). We don't assert on the DataTable contents —
    // an empty workspace is legitimate and the EmptyState is the
    // recovery path we actually exercise.
    await expect(
      page.getByRole("heading", { name: /Matter portfolio/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /Could not load matters/i }),
    ).toHaveCount(0);
  });

  test("contracts list surfaces retry on 503", async ({ page }) => {
    const api = await request.newContext();
    const s = slug("qs-c");
    await bootstrap(api, s);
    await signIn(page, s);

    let failed = 0;
    await page.route("**/api/contracts/*", async (route) => {
      if (route.request().method() !== "GET") return route.continue();
      if (failed >= 2) return route.continue();
      failed += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ detail: "Upstream temporarily unavailable" }),
      });
    });

    await page.goto("/app/contracts");

    await expect(
      page.getByRole("heading", { name: /Could not load contracts/i }),
    ).toBeVisible();
    await expect(
      page.getByText(/Upstream temporarily unavailable/i),
    ).toBeVisible();

    await page.getByTestId("query-error-retry").click();

    await expect(
      page.getByRole("heading", { name: /Contract repository/i }),
    ).toBeVisible();
  });

  test("matter not-found renders branded page, not a 404 white screen", async ({
    page,
  }) => {
    const api = await request.newContext();
    const s = slug("qs-nf");
    await bootstrap(api, s);
    await signIn(page, s);

    // Valid-shaped but non-existent matter id.
    await page.goto("/app/matters/00000000-0000-0000-0000-000000000000");

    await expect(
      page.getByRole("heading", { name: /Matter not found/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Back to matter portfolio/i }),
    ).toBeVisible();
  });
});
