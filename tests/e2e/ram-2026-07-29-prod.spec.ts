/**
 * Deployed-production proof for the Ram 2026-07-29 Admin regressions.
 * Credentials are supplied only through the process environment.
 */
import { expect, test, type Page } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL =
  process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

const adminActions = [
  ["Notifications", "/app/admin/notifications"],
  ["Integrations", "/app/admin/integrations"],
  ["Provider ops", "/app/admin/provider-operations"],
  ["Outlook", "/app/admin/outlook"],
  ["Employees", "/app/admin/employees"],
  ["Roles", "/app/admin/roles"],
  ["Manage teams", "/app/admin/teams"],
  ["Judge aliases", "/app/admin/judge-aliases"],
] as const;

function requiredPassword(): string {
  const value = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!value) {
    throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  }
  return value;
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

test.describe("Ram 2026-07-29 deployed production regressions", () => {
  test.setTimeout(120_000);

  test("BUG-001: Judge aliases is discoverable from desktop and mobile navigation", async ({
    page,
  }) => {
    await signIn(page);
    const desktopLink = page.getByRole("link", {
      name: "Judge aliases",
      exact: true,
    });
    await expect(desktopLink).toBeVisible();
    await desktopLink.click();
    await expect(page).toHaveURL(/\/app\/admin\/judge-aliases$/);
    await expect(page.getByRole("heading", { name: "Judge aliases" })).toBeVisible();

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app`);
    await page.getByTestId("mobile-nav-trigger").click();
    const drawer = page.getByRole("dialog", { name: "Workspace navigation" });
    await expect(
      drawer.getByRole("link", { name: "Judge aliases", exact: true }),
    ).toBeVisible();
  });

  test("BUG-002: the full Admin action set stays visible and within the mobile viewport", async ({
    page,
  }) => {
    await signIn(page);
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app/admin`);

    for (const [label, href] of adminActions) {
      const link = page.getByRole("link", { name: label, exact: true });
      await expect(link, `${label} should be rendered on mobile Admin`).toBeVisible();
      await expect(link).toHaveAttribute("href", href);
      const box = await link.boundingBox();
      expect(box, `${label} should have a layout box`).not.toBeNull();
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(
        box!.x + box!.width,
        `${label} should fit the 360px viewport`,
      ).toBeLessThanOrEqual(360);
    }
  });
});
