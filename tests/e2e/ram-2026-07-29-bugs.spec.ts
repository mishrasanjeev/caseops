/**
 * Ram 2026-07-29 workbook regressions.
 *
 * These checks start from the user-visible navigation surface and validate
 * the entire Admin landing-page action set at a narrow mobile viewport. A
 * route existing behind a direct URL is not sufficient proof of discoverable
 * Admin functionality.
 */
import { expect, request, test, type APIRequestContext, type Page } from "@playwright/test";

import {
  authenticateOrBootstrapLocalLegalTenant,
  LOCAL_LEGAL_PASSWORD,
} from "./support/local-legal-tenant";
import { apiBaseUrl } from "./support/env";

const COMPANY_SLUG = "legal";
const OWNER_EMAIL = "hari.gupta@gmail.com";

let api: APIRequestContext;

async function signIn(page: Page): Promise<void> {
  await page.goto("/sign-in");
  await page.locator("#company-slug").fill(COMPANY_SLUG);
  await page.locator("#email").fill(OWNER_EMAIL);
  await page.locator("#password").fill(LOCAL_LEGAL_PASSWORD);
  await page.getByRole("button", { name: /^Sign in$/ }).click();
  await page.waitForURL(/\/app(?:[/?]|$)/);
}

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

test.describe.serial("Ram 2026-07-29 workbook regressions", () => {
  test.beforeAll(async () => {
    api = await request.newContext();
    await authenticateOrBootstrapLocalLegalTenant(api, {
      companyName: "Legal - Ram July 29 local regression",
      ownerFullName: "Hari Gupta",
    });
  });

  test.afterAll(async () => {
    await api?.dispose();
  });

  test("BUG-001: Judge aliases remains discoverable in desktop and mobile navigation", async ({
    page,
  }) => {
    await signIn(page);

    await expect(
      page.getByRole("link", { name: "Judge aliases", exact: true }),
    ).toBeVisible();
    await page.getByRole("link", { name: "Judge aliases", exact: true }).click();
    await expect(page).toHaveURL(/\/app\/admin\/judge-aliases$/);
    await expect(page.getByRole("heading", { name: "Judge aliases" })).toBeVisible();

    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/app");
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
    await page.goto("/app/admin");

    for (const [label, href] of adminActions) {
      const link = page.getByRole("link", { name: label, exact: true });
      await expect(link, `${label} should be rendered on mobile Admin`).toBeVisible();
      await expect(link).toHaveAttribute("href", href);
      const box = await link.boundingBox();
      expect(box, `${label} should have a layout box`).not.toBeNull();
      test.info().annotations.push({
        type: "mobile-layout",
        description: `${label}: x=${box?.x} width=${box?.width} right=${box ? box.x + box.width : "n/a"}`,
      });
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width, `${label} should fit the 360px viewport`).toBeLessThanOrEqual(360);
    }
  });
});
