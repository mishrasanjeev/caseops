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
    const primary = path === "/app/ip/registry"
      ? page.getByRole("combobox", { name: "IP docket", exact: true })
      : page.getByRole("textbox", { name: "Family title", exact: true });
    const returnName = path === "/app/ip/registry" ? "Return to Registry" : "Return to Patent families";
    const referenceLink = page.getByRole("link", { name: "IP India official references", exact: true });
    await expect(primary).toBeInViewport({ ratio: 0.5 });
    if (path === "/app/ip/patents") await primary.fill("Unsubmitted family search");
    const primaryValue = await primary.inputValue();
    await expect(panel).not.toHaveAttribute("open", "");
    await referenceLink.focus();
    await page.keyboard.press("Enter");
    await expect(panel.locator("summary").first()).toBeInViewport({ ratio: 0.5 });
    await expect(panel.locator("summary").first()).toBeFocused();
    await page.keyboard.press("Space");
    await expect(panel.getByRole("status")).toHaveText("7 of 7 references");
    await expect(panel).toContainText("not live patent, trademark or design records");
    await panel.getByLabel("Search official references").fill("nationality");
    await expect(panel.getByRole("status")).toHaveText("1 of 7 references");
    await expect(panel.getByText("Applicant name, nationality and address", { exact: true })).toBeVisible();
    await expect(panel).toContainText("claims are not applicable to a provisional specification");
    await expect(panel).toContainText("not a completed form or filing validation");
    await expect(panel.getByRole("link", { name: /Patent Form 2/ })).toHaveAttribute("href", "https://www.ipindia.gov.in/storage/uploads/docs-operator/ee69dc48-77c4-4900-b222-154573143a4f.pdf");
    const returns = panel.getByRole("link", { name: returnName, exact: true });
    await expect(returns).toHaveCount(2);
    await returns.first().focus();
    await page.keyboard.press("Enter");
    const returnTarget = page.locator(path === "/app/ip/registry" ? "#registry-controls" : "#patent-family-controls");
    await expect(returnTarget).toBeFocused();
    const firstControl = returnTarget.locator('input:not([type="hidden"])').first();
    await expect(firstControl).toBeEnabled();
    await page.keyboard.press("Tab");
    await expect(firstControl).toBeFocused();
    await expect(primary).toBeInViewport({ ratio: 0.5 });
    await expect(primary).toHaveValue(primaryValue);
    await referenceLink.click();
    await expect(panel.getByLabel("Search official references")).toHaveValue("nationality");
    await panel.getByLabel("Search official references").fill("");
    await panel.getByLabel("Source type").selectOption("register");
    await expect(panel.getByRole("status")).toHaveText("3 of 7 references");
    await expect(panel).toContainText("OTP and CAPTCHA");
    const officialLinks = panel.locator('a[href^="https://"]');
    await expect(officialLinks).toHaveCount(6);
    for (const link of await officialLinks.all()) {
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
    await returns.last().click();
    await expect(primary).toBeInViewport({ ratio: 0.5 });
    await expect(primary).toHaveValue(primaryValue);
    const widths = phone ? [360, 390, 400] : [639, 640, 641, 767, 768, 769, 1279, 1280, 1281, 1440];
    for (const width of widths) {
      await page.setViewportSize({ width, height: 900 });
      await referenceLink.click();
      await expect(panel.locator("summary").first()).toBeInViewport({ ratio: 0.5 });
      await expect(panel.getByLabel("Search official references")).toHaveValue("unknown-right-999");
      await returns.first().click();
      await expect(primary).toBeInViewport({ ratio: 0.5 });
      await expect(primary).toHaveValue(primaryValue);
      const box = await primary.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.width).toBeGreaterThan(160);
      expect(box!.x).toBeGreaterThanOrEqual(0);
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    }
    await page.reload();
    await referenceLink.focus();
    await page.keyboard.press("Enter");
    await expect(panel.locator("summary").first()).toBeFocused();
    await page.keyboard.press("Space");
    await expect(panel.getByRole("status")).toHaveText("7 of 7 references");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)).toBe(true);
    expect(external).toEqual([]);
    await runtime.release();
  });
}
