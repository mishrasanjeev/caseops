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
});
