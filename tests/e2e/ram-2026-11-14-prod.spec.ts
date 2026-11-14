/** Official references are read-only; this never searches an external register. */
import { expect, test } from "@playwright/test";

import { prepareTester } from "./support/ram-bugs4";

test.use({ trace: "off", screenshot: "off", video: "off", storageState: { cookies: [], origins: [] } });

for (const phone of [false, true]) for (const path of ["/app/ip/registry", "/app/ip/patents"]) {
  test(`${phone ? "[mobile] " : ""}IP India content and form references ${path} ${phone ? "phone" : "desktop"}`, async ({ page, request, baseURL }) => {
    const runtime = await prepareTester(page, request, baseURL, { width: phone ? 390 : 1440, height: 900 });
    const external: string[] = [];
    await page.route("**/*", async (route) => {
      const url = new URL(route.request().url());
      if (url.hostname === "ipindia.gov.in" || url.hostname.endsWith(".ipindia.gov.in")) {
        external.push(url.hostname);
        await route.abort();
      } else await route.continue();
    });
    await page.goto(`${runtime.web.origin}${path}`);
    const panel = page.getByTestId("ipindia-sources");
    await panel.locator("summary").first().click();
    await expect(panel.getByRole("status")).toHaveText("7 of 7 references");
    await expect(panel).toContainText("not live patent, trademark or design records");
    await panel.getByLabel("Search official references").fill("nationality");
    await expect(panel.getByRole("status")).toHaveText("1 of 7 references");
    await expect(panel.getByText("Applicant name, nationality and address", { exact: true })).toBeVisible();
    await expect(panel).toContainText("claims are not applicable to a provisional specification");
    await expect(panel).toContainText("not a completed form or filing validation");
    await expect(panel.getByRole("link", { name: /Patent Form 2/ })).toHaveAttribute("href", "https://www.ipindia.gov.in/storage/uploads/docs-operator/ee69dc48-77c4-4900-b222-154573143a4f.pdf");
    await panel.getByLabel("Search official references").fill("");
    await panel.getByLabel("Source type").selectOption("register");
    await expect(panel.getByRole("status")).toHaveText("3 of 7 references");
    await expect(panel).toContainText("OTP and CAPTCHA");
    for (const link of await panel.getByRole("link").all()) {
      await expect(link).toHaveAttribute("rel", "noopener noreferrer");
      await expect(link).toHaveAttribute("referrerpolicy", "no-referrer");
      const box = await link.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThan(20);
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual((page.viewportSize()?.width ?? 0) + 1);
    }
    await panel.getByLabel("Search official references").fill("unknown-right-999");
    await expect(panel.getByRole("status")).toHaveText("0 of 7 references");
    await expect(panel).toContainText("does not mean a right or official record does not exist");
    await page.reload();
    await panel.locator("summary").first().click();
    await expect(panel.getByRole("status")).toHaveText("7 of 7 references");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect(external).toEqual([]);
    await runtime.release();
  });
}
