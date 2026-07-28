/**
 * Deployed-production proof for Ram 2026-07-28 BUG-001.
 *
 * Authenticates explicitly with the tester account supplied for this run and
 * checks the shared desktop sidebar, mobile drawer, and real Judge Aliases
 * page. No credentials are stored in source or diagnostics.
 */
import { expect, test } from "@playwright/test";

const PROD_BASE_URL = process.env.PROD_BASE_URL ?? "https://caseops.ai";
const COMPANY_SLUG = process.env.CASEOPS_RAM_PROD_SLUG ?? "legal";
const TESTER_EMAIL =
  process.env.CASEOPS_RAM_PROD_EMAIL ?? "hari.gupta@gmail.com";

function requiredPassword(): string {
  const password = process.env.CASEOPS_RAM_PROD_PASSWORD?.trim() ?? "";
  if (!password) {
    throw new Error("CASEOPS_RAM_PROD_PASSWORD is required for production proof.");
  }
  return password;
}

async function signIn(page: import("@playwright/test").Page): Promise<void> {
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

test.describe("Ram 2026-07-28 deployed production regressions", () => {
  test.setTimeout(120_000);

  test("BUG-001: Judge Aliases is discoverable from desktop and mobile Admin navigation", async ({
    page,
  }) => {
    await signIn(page);

    const desktopLink = page.getByRole("link", {
      name: "Judge aliases",
      exact: true,
    });
    await expect(desktopLink).toBeVisible();
    await expect(desktopLink).toHaveAttribute(
      "href",
      "/app/admin/judge-aliases",
    );
    await desktopLink.click();
    await expect(page).toHaveURL(/\/app\/admin\/judge-aliases$/);
    await expect(
      page.getByRole("heading", { name: "Judge aliases" }),
    ).toBeVisible();

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto(`${PROD_BASE_URL}/app`);
    await page.getByTestId("mobile-nav-trigger").click();
    const drawer = page.getByRole("dialog", { name: "Workspace navigation" });
    const mobileLink = drawer.getByRole("link", {
      name: "Judge aliases",
      exact: true,
    });
    await expect(mobileLink).toBeVisible();
    await mobileLink.click();
    await expect(page).toHaveURL(/\/app\/admin\/judge-aliases$/);
    await expect(
      page.getByRole("heading", { name: "Judge aliases" }),
    ).toBeVisible();
  });
});
