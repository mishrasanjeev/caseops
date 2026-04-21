import { chromium } from "playwright";

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.goto("https://caseops.ai/sign-in", { waitUntil: "load" });
await page.locator("#company-slug").fill("aster-demo");
await page.locator("#email").fill("sanjeev@aster-demo.in");
await page.locator("#password").fill("Aster-Demo-2026!");
await Promise.all([
  page.waitForURL(/\/app(?!\/sign-in)/, { timeout: 30000 }),
  page.locator('button[type="submit"]').first().click(),
]);
await page.goto(
  "https://caseops.ai/app/matters/310b7c38-47ad-461b-9ebf-7bb59e9c8667/hearings",
  { waitUntil: "load" },
);
await page.waitForTimeout(5000);

const byTestId = page.locator('[data-testid="schedule-hearing-open"]');
console.log("schedule-hearing-open count:", await byTestId.count());
if (await byTestId.count() > 0) {
  console.log("visible:", await byTestId.first().isVisible());
}

const buttons = await page.locator("button").allTextContents();
console.log(
  "buttons on page:",
  buttons.filter((b) => b.trim()).slice(0, 25),
);
await page.screenshot({
  path: "C:/Users/mishr/caseops/tmp/bug_verify_2026_04_21/04_hearings_full.png",
  fullPage: true,
});
await browser.close();
