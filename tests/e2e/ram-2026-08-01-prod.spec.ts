import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL = process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
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

test.describe("Ram 2026-08-01 deployed IP slices", () => {
  test.setTimeout(120_000);

  test("exact production revision keeps the unentitled IP workspace fail-closed at desktop and 360px", async ({
    page,
  }) => {
    await signIn(page);
    const docketRequests: string[] = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/ip/dockets") {
        docketRequests.push(request.url());
      }
    });
    const readinessRequest = page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/ip/readiness" &&
        response.request().method() === "GET",
    );
    await page.goto(`${PROD_BASE_URL}/app/ip`);
    const readinessResponse = await readinessRequest;
    expect(readinessResponse.status()).toBe(200);
    const readiness = (await readinessResponse.json()) as {
      workspace_available: boolean;
      features: Array<{ feature_id: string; available: boolean; reason: string }>;
    };
    expect(readiness.workspace_available).toBe(false);
    expect(readiness.features.some((feature) => feature.feature_id === "workspace_core")).toBe(true);

    await expect(page.getByRole("heading", { name: "IP workspace setup" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Readiness checks" })).toBeVisible();
    await expect(page.getByTestId("ip-readiness-workspace_core")).toContainText("Disabled");
    await expect(page.getByRole("button", { name: "New trademark" })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Trademark docket" })).toHaveCount(0);
    expect(docketRequests).toEqual([]);

    await page.setViewportSize({ width: 360, height: 800 });
    await page.reload();
    await expect(page.getByRole("heading", { name: "IP workspace setup" })).toBeVisible();
    for (const feature of readiness.features) {
      const row = page.getByTestId(`ip-readiness-${feature.feature_id}`);
      await row.scrollIntoViewIfNeeded();
      await expect(row).toBeVisible();
      const box = await row.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(360);
    }
    await expect(page.getByRole("button", { name: "New trademark" })).toHaveCount(0);
    expect(docketRequests).toEqual([]);
  });
});
