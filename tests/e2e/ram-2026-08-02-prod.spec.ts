import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const PROD_API_BASE_URL =
  process.env.PROD_API_BASE_URL ?? "https://api.caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL = process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) {
    throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  }
  return password;
}

async function signIn(page: Page): Promise<void> {
  await page.goto(`${PROD_BASE_URL}/sign-in`);
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(TESTER_EMAIL);
  await page.locator("#password").fill(requiredPassword());
  const login = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/login" &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  expect((await login).status()).toBe(200);
  await page.waitForURL(new RegExp(`${PROD_BASE_URL}/app(?:[/?]|$)`));
}

test.describe("Ram 2026-08-02 deployed provider health foundation", () => {
  test.setTimeout(120_000);

  test("production exposes fail-closed freshness at desktop and 360px", async ({
    page,
  }) => {
    await signIn(page);
    await page.goto(`${PROD_BASE_URL}/app/admin/integrations`);
    await expect(page.getByRole("heading", { name: "Integrations" })).toBeVisible();
    await expect(page.getByTestId("connector-health-summary")).toBeVisible({
      timeout: 30_000,
    });

    const healthResponse = await page.request.get(
      `${PROD_API_BASE_URL}/api/admin/integrations/health`,
    );
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
      }
    }

    await page.setViewportSize({ width: 360, height: 800 });
    await page.reload();
    await expect(page.getByTestId("connector-health-summary")).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);

    await page.goto(`${PROD_BASE_URL}/app/admin/provider-operations`);
    await expect(
      page.getByRole("heading", { name: "Provider operations", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth),
    ).toBeLessThanOrEqual(360);
  });

  test("IPLF-002B deployed tracking record exposes freshness, cost, and mobile controls", async ({
    page,
  }) => {
    await signIn(page);
    const suffix = Date.now().toString(36).toUpperCase();
    const title = `IPLF-002B synthetic ${suffix}`;
    const created = await page.request.post(`${PROD_API_BASE_URL}/api/case-tracking/bookmarks`, {
      data: {
        provider: "ecourtsindia",
        cnr_number: `E2E002B${suffix}`.slice(0, 32),
        case_number: `E2E/002B/${suffix}`,
        court_code: "E2E",
        court_name: "Synthetic Test Court",
        case_title: title,
        notification_enabled: false,
      },
    });
    expect(created.status()).toBe(201);
    const bookmark = await created.json();
    expect(bookmark.tracked_case.freshness_status).toBeTruthy();
    expect(typeof bookmark.tracked_case.refresh_cost_minor).toBe("number");

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app/case-tracking`);
    await expect(page.getByText(title)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Refresh cost INR/i).last()).toBeVisible();
    await expect(page.getByText(/Attempted/i).last()).toBeVisible();
    await expect(page.getByText(/Last good/i).last()).toBeVisible();
    await expect(page.getByText(/Next/i).last()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
      360,
    );

    const archived = await page.request.patch(
      `${PROD_API_BASE_URL}/api/case-tracking/bookmarks/${bookmark.id}`,
      { data: { is_archived: true } },
    );
    expect(archived.status()).toBe(200);
  });
});
