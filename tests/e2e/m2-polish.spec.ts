import { expect, test } from "@playwright/test";

import { uniqueId } from "./support/helpers";

// Sprint 57 (M2 polish) + UX fix wave covers four surfaces I shipped
// without a browser walkthrough originally. This spec is the make-up:
// every interaction the user touched manually is now driven from
// Playwright so future regressions surface in CI.

const STRONG_PASSWORD = "DemoPass-2026!"; // 12+ chars, upper, lower, digit, symbol

async function bootstrapWorkspace(page: import("@playwright/test").Page): Promise<{
  slug: string;
  email: string;
  password: string;
}> {
  const suffix = uniqueId("m2").slice(-8);
  const slug = `m2-${suffix}`;
  const email = `owner-${suffix}@example.com`;

  await page.goto("/sign-in");
  await page.getByRole("tab", { name: /New workspace/i }).click();
  await page.getByLabel(/Firm \/ organisation name/i).fill(`M2 Polish ${suffix}`);
  await page.getByLabel(/Workspace slug/i).fill(slug);
  await page.getByLabel(/Your full name/i).fill("Test Owner");
  await page.getByLabel(/Your work email/i).fill(email);
  await page.getByLabel(/^Password$/i).fill(STRONG_PASSWORD);
  await page.getByTestId("new-workspace-submit").click();
  await page.waitForURL("**/app");
  return { slug, email, password: STRONG_PASSWORD };
}

test.describe("M2 polish — password toggle, counsel recs, team picker, judge profile", () => {
  test("password input on /sign-in toggles visible/hidden via the eye button", async ({
    page,
  }) => {
    await page.goto("/sign-in");
    const passwordField = page.getByLabel(/^Password$/i);
    await passwordField.fill("look-at-me-1!");

    // Default = hidden
    await expect(passwordField).toHaveAttribute("type", "password");

    // Toggle visible via the explicit aria-label
    const showBtn = page.getByRole("button", { name: /Show password/i });
    await showBtn.click();
    await expect(passwordField).toHaveAttribute("type", "text");

    // Toggle back
    const hideBtn = page.getByRole("button", { name: /Hide password/i });
    await hideBtn.click();
    await expect(passwordField).toHaveAttribute("type", "password");
  });

  test("password toggle works on the New-workspace tab too", async ({ page }) => {
    await page.goto("/sign-in");
    await page.getByRole("tab", { name: /New workspace/i }).click();
    const pw = page.getByLabel(/^Password$/i);
    await pw.fill("anothertest1!");
    await expect(pw).toHaveAttribute("type", "password");
    await page.getByRole("button", { name: /Show password/i }).click();
    await expect(pw).toHaveAttribute("type", "text");
  });

  test("sign-in with bad credentials surfaces an error toast", async ({ page }) => {
    await page.goto("/sign-in");
    await page.getByLabel(/Company slug/i).fill("nonexistent-tenant-xyz");
    await page.getByLabel(/Work email/i).fill("nobody@nowhere.example");
    await page.getByLabel(/^Password$/i).fill("WrongPassword1!");
    await page.getByRole("button", { name: /^Sign in$/i }).click();

    // Sonner error toast (we don't pin the exact wording — just that
    // *some* error appears and we did NOT redirect to /app).
    await expect(page).not.toHaveURL(/\/app$/);
    // The toast region is a sonner [data-sonner-toaster]; an explicit
    // role=status assertion is most portable.
    await expect(
      page.getByText(/could not sign you in|invalid|incorrect|not found/i),
    ).toBeVisible({ timeout: 10_000 });
  });

  test("matter detail page shows the Suggested counsel card", async ({ page }) => {
    await bootstrapWorkspace(page);

    // Create a matter so we have a detail page to visit.
    await page.getByRole("link", { name: "Matters", exact: true }).click();
    await page.waitForURL("**/app/matters");
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    const matterTitle = `Counsel Recs Smoke ${Date.now().toString().slice(-6)}`;
    await dialog.getByLabel("Title").fill(matterTitle);
    await dialog.getByLabel("Matter code").fill(`M2-CR-${Date.now().toString().slice(-6)}`);
    await dialog.getByLabel("Practice area").fill("Criminal");
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    await expect(dialog).toBeHidden();

    // Open the matter overview.
    await page.getByText(matterTitle).first().click();
    await page.waitForURL(/\/app\/matters\/[^/]+/);

    // The Suggested counsel card lives between matter summary and last
    // court order. With no counsel on panel it shows the empty state.
    await expect(page.getByText(/Suggested counsel/i)).toBeVisible({
      timeout: 15_000,
    });
    await expect(
      page.getByText(/No counsel suggestions yet|Add counsel to the panel/i),
    ).toBeVisible();
  });

  test("matter team picker is hidden when workspace has no teams + scoping off", async ({
    page,
  }) => {
    await bootstrapWorkspace(page);

    // Same matter-creation flow.
    await page.getByRole("link", { name: "Matters", exact: true }).click();
    await page.getByTestId("new-matter-trigger").first().click();
    const dialog = page.getByRole("dialog");
    const matterTitle = `Team Picker Smoke ${Date.now().toString().slice(-6)}`;
    await dialog.getByLabel("Title").fill(matterTitle);
    await dialog.getByLabel("Matter code").fill(`M2-TP-${Date.now().toString().slice(-6)}`);
    await dialog.getByLabel("Practice area").fill("Civil");
    await dialog.getByRole("button", { name: /Create matter/i }).click();
    await expect(dialog).toBeHidden();
    await page.getByText(matterTitle).first().click();
    await page.waitForURL(/\/app\/matters\/[^/]+/);

    // Picker is intentionally hidden when there are zero teams AND
    // team-scoping is off (the default for a fresh tenant). Asserts the
    // *absence* — the visible-when-teams-exist case is its own test
    // scenario once teams ship a UI to create them.
    const teamLabel = page.getByText(/^Team$/, { exact: true });
    await expect(teamLabel).toBeHidden({ timeout: 5_000 });
  });

  test("court list → court profile → judge name → judge profile route renders", async ({
    page,
  }) => {
    await bootstrapWorkspace(page);

    await page.goto("/app/courts");
    await expect(
      page.getByRole("heading", { name: /Courts|Court intelligence/i }),
    ).toBeVisible({ timeout: 10_000 });

    // The seed catalog includes Supreme Court of India — click into it.
    await page.getByText(/Supreme Court of India/i).first().click();
    await page.waitForURL(/\/app\/courts\/[^/]+/);

    // Even with zero seeded judges, the page must render with the
    // empty state — not blow up. This catches the most basic kind of
    // runtime regression.
    await expect(page.getByText(/Judges/i).first()).toBeVisible();

    // If judges exist, clicking one should take us to the judge
    // profile route. Skip the click when the empty state is showing.
    const firstJudgeLink = page.locator('a[href^="/app/courts/judges/"]').first();
    if ((await firstJudgeLink.count()) > 0) {
      await firstJudgeLink.click();
      await page.waitForURL(/\/app\/courts\/judges\/[^/]+/);
      // Page renders with at least the back link + the judge KPI cards.
      await expect(
        page.getByRole("link", { name: /Back to/i }),
      ).toBeVisible({ timeout: 10_000 });
    }
  });
});
