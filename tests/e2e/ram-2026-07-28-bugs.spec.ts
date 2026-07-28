/**
 * Ram 2026-07-28 navigation regression.
 *
 * The Judge Aliases route existed and the Admin landing page linked to it,
 * but the shared workspace navigation omitted it. This spec verifies the
 * user-visible contract on both desktop and the mobile navigation drawer.
 */
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import { apiBaseUrl } from "./support/env";

const COMPANY_SLUG = "legal";
const OWNER_EMAIL = "hari.gupta@gmail.com";
const OWNER_PASSWORD =
  process.env.CASEOPS_RAM_LOCAL_PASSWORD ?? "RamLocalRegression0728!";

let api: APIRequestContext;

async function signIn(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(OWNER_EMAIL);
  await page.locator("#password").fill(OWNER_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

test.describe.serial("Ram 2026-07-28 workbook regressions", () => {
  test.beforeAll(async () => {
    api = await request.newContext();
    const response = await api.post(`${apiBaseUrl}/api/bootstrap/company`, {
      data: {
        company_name: "Legal - Ram July 28 local regression",
        company_slug: COMPANY_SLUG,
        company_type: "law_firm",
        owner_full_name: "Hari Gupta",
        owner_email: OWNER_EMAIL,
        owner_password: OWNER_PASSWORD,
      },
    });
    expect(response.status(), await response.text()).toBe(200);
  });

  test.afterAll(async () => {
    await api?.dispose();
  });

  test("BUG-001: Judge Aliases is discoverable in desktop and mobile Admin navigation", async ({
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
    await page.goto("/app");
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
